"""Design §3.1 on fakes: each failure, what the caller sees, what is left, and the resume.

Every test runs the orchestrator over the #108 fakes, injects one failure through
their failure plan (``fail_next``, ``applied=True`` for a lost response,
``fail_always`` for an outage), then usually sends the same request again. A fake
clock drives the 120-second lease and the 20-second guard. The HTTP rows (invalid
body, bad key) are tested at the HTTP layer.
"""

import importlib.util
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from calendar_contract import CalendarError
from calendar_contract import ErrorCode as CalendarCode
from cloud_storage_api import ProviderUnavailableError
from issue_tracker_contract import ErrorCode as TrackerCode
from issue_tracker_contract import ServiceError

from meeting_prep.agenda import agenda_path, render
from meeting_prep.fakes import FakeCalendar, FakeStorage, FakeTracker
from meeting_prep.orchestrator import (
    InProcessRunLocks,
    Orchestrator,
    ReviewMeetingError,
    RunResult,
    validate,
)
from meeting_prep.run_record import (
    RunRecord,
    StepRecord,
    from_bytes,
    meeting_title,
    new_record,
    record_path,
    run_id_for,
    to_bytes,
)
from tests.fake_adapters import START, CalendarSteps, FakeClock, StorageSteps, TrackerSteps

TITLE = "Storage v0.2.0 release review"
BODY = {
    "title": TITLE,
    "start": "2026-11-20T15:00:00-05:00",
    "end": "2026-11-20T15:30:00-05:00",
    "agenda": ["Folder delete results on OCI", "Open bugs", "Release go or no-go"],
}
REQUEST = validate(BODY, START)
RUN_ID = run_id_for(REQUEST)
RECORD = record_path(RUN_ID)
AGENDA = agenda_path(REQUEST, RUN_ID)
UNAVAILABLE = ProviderUnavailableError("down")


class World:
    """The three fakes, their adapters, a clock and the orchestrator over them."""

    def __init__(self, locks: object | None = None) -> None:
        self.storage, self.tracker, self.calendar = FakeStorage(), FakeTracker(), FakeCalendar()
        self.storage_steps = StorageSteps(self.storage)
        self.tracker_steps = TrackerSteps(self.tracker)
        self.clock = FakeClock(START)
        self.orchestrator = Orchestrator(
            self.storage_steps,
            self.tracker_steps,
            CalendarSteps(self.calendar),
            clock=self.clock,
            locks=locks,  # type: ignore[arg-type]
        )

    def run(self) -> RunResult:
        return self.orchestrator.run(BODY)

    def fails(self) -> ReviewMeetingError:
        with pytest.raises(ReviewMeetingError) as caught:
            self.run()
        error = caught.value
        # Invariant 7: no title or agenda item in a message.
        assert TITLE not in error.message and "Open bugs" not in error.message
        return error

    def record(self) -> RunRecord:
        return from_bytes(self.storage.files[RECORD].content, RUN_ID)

    def put_record(self, record: RunRecord) -> None:
        """A record left by another request or a stopped process."""
        self.storage.create(RECORD, to_bytes(record))
        self.storage.calls.clear()

    def calls(self, fake: FakeStorage | FakeTracker | FakeCalendar, name: str) -> int:
        return fake.operations_called().count(name)


@pytest.fixture
def world() -> World:
    return World()


def step_status(run: dict[str, object] | None, name: str) -> object:
    assert run is not None
    steps = run["steps"]
    assert isinstance(steps, list)
    return next(step["status"] for step in steps if step["name"] == name)


def assert_completed_once(world: World, result: RunResult) -> None:
    """One card, one event, the agenda's exact bytes, and a completed record."""
    assert result.run["status"] == "completed"
    assert len(world.tracker.issues) == 1 and len(world.calendar.events) == 1
    (issue_id,) = world.tracker.issues
    (event_id,) = world.calendar.events
    assert result.run["issue"] == {"id": issue_id}
    assert result.run["event"] == {"id": event_id, "start": REQUEST.start, "end": REQUEST.end}
    assert result.run["agenda"] == {"path": AGENDA}
    expected = render(REQUEST, RUN_ID, issue_id=issue_id, event_id=event_id)
    assert world.storage.files[AGENDA].content == expected
    assert world.record().state == "completed"


# --- The path with no failure ---


def test_a_new_run_makes_one_of_each_in_order_and_completes(world):
    result = world.run()

    assert result.replayed is False
    assert_completed_once(world, result)
    assert result.body()["status"] == "completed" and result.body()["replayed"] is False
    assert [step_status(result.run, n) for n in ("claim_run", "finish_run")] == ["ok", "ok"]
    # claim, record after the issue, record after the event, agenda, finish.
    assert world.storage.operations_called() == [
        "create",
        "replace",
        "replace",
        "create",
        "replace",
    ]
    (issue,) = world.tracker.issues.values()
    (event,) = world.calendar.events.values()
    assert issue.title == event.title == meeting_title(REQUEST, RUN_ID)


# --- Storage at claim_run ---


def test_claim_fails(world):
    world.storage.failures.fail_next("create", UNAVAILABLE)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == ("provider_unavailable", "claim_run", True)
    assert error.run is not None and error.run["status"] == "failed"
    assert step_status(error.run, "claim_run") == "unknown"  # a create may have applied
    assert world.tracker.calls == [] and RECORD not in world.storage.files
    assert_completed_once(world, world.run())


def test_a_claim_whose_record_landed_is_resumed_after_its_lease(world):
    world.storage.failures.fail_next("create", UNAVAILABLE, applied=True)
    world.fails()

    assert world.fails().code == "run_in_progress"  # the record says create_issue attempting
    world.clock.advance(121)
    result = world.run()

    assert_completed_once(world, result)
    assert world.tracker.operations_called() == ["list_issues", "create_issue"]


# --- The lease and the 20-second guard ---


@pytest.mark.parametrize(
    ("steps", "age", "step", "retry_after"),
    [
        ({"create_issue": StepRecord("attempting")}, 30, "create_issue", 90),
        (
            {"create_issue": StepRecord("done", "card"), "create_event": StepRecord("attempting")},
            100.5,
            "create_event",
            20,
        ),
    ],
    ids=["tracker", "calendar"],
)
def test_live_lease_returns_409(world, steps, age, step, retry_after):
    seed = new_record(REQUEST, RUN_ID, START).with_steps(START, **steps)
    world.put_record(seed)
    world.clock.advance(age)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == ("run_in_progress", step, True)
    assert error.retry_after == retry_after  # the rest of the lease, rounded up
    assert world.tracker.calls == [] and world.calendar.calls == []
    assert world.record() == seed


def test_slow_record_write_skips_the_tracker(world):
    world.storage_steps.at("create", 1, lambda: world.clock.advance(25))  # the claim

    error = world.fails()

    assert (error.code, error.step) == ("provider_unavailable", "create_issue")
    assert (error.retryable, error.may_have_applied) == (True, False)
    assert error.run is not None and error.run["status"] == "failed"
    assert world.tracker.calls == []
    assert world.record().step("create_issue").state == "not_applied"
    assert_completed_once(world, world.run())


def test_slow_record_write_skips_the_calendar(world):
    world.storage_steps.at("replace", 1, lambda: world.clock.advance(25))  # after the issue

    error = world.fails()

    assert (error.code, error.step, error.retryable) == (
        "provider_unavailable",
        "create_event",
        True,
    )
    assert error.run is not None and error.run["status"] == "partial"
    assert world.calendar.calls == []
    assert world.record().step("create_event").state == "not_applied"
    assert_completed_once(world, world.run())
    assert world.calls(world.tracker, "create_issue") == 1


# --- Replay ---


def test_replay_writes_nothing(world):
    first = world.run()
    for fake in (world.storage, world.tracker, world.calendar):
        fake.calls.clear()

    again = world.run()

    assert again.replayed is True and again.run == first.run
    assert again.body()["replayed"] is True
    # One refused claim and one download of the record; no partner call.
    assert world.storage.operations_called() == ["create", "download"]
    assert world.tracker.calls == [] and world.calendar.calls == []


# --- Tracker ---


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (TrackerCode.ACCESS_DENIED, "permission_denied"),
        (TrackerCode.SERVICE_NOT_CONFIGURED, "provider_unavailable"),
    ],
)
def test_tracker_refuses(world, code, expected):
    world.tracker.failures.fail_next("create_issue", ServiceError(code, "no"))

    error = world.fails()

    assert (error.code, error.step, error.retryable) == (expected, "create_issue", False)
    assert error.run is not None and error.run["status"] == "failed"
    assert world.record().step("create_issue").state == "not_applied"
    assert world.calendar.calls == []
    # The operator fixes the credentials or the list; the same request then completes.
    assert_completed_once(world, world.run())


@pytest.mark.parametrize("card_was_made", [True, False], ids=["card made", "no card"])
def test_tracker_lost_response_adopts_card(world, card_was_made):
    lost = ServiceError(TrackerCode.PROVIDER_ERROR, "no response", may_have_applied=True)
    world.tracker.failures.fail_next("create_issue", lost, applied=card_was_made)

    error = world.fails()

    assert (error.code, error.step) == ("provider_error", "create_issue")
    assert (error.retryable, error.may_have_applied) == (True, True)
    assert error.run is not None and error.run["status"] == "partial"
    assert world.record().step("create_issue").state == "unknown"
    world.tracker.calls.clear()

    result = world.run()

    assert_completed_once(world, result)
    expected = ["list_issues"] if card_was_made else ["list_issues", "create_issue"]
    assert world.tracker.operations_called() == expected


def test_a_failed_search_leaves_the_issue_unknown(world):
    lost = ServiceError(TrackerCode.PROVIDER_ERROR, "no response", may_have_applied=True)
    world.tracker.failures.fail_next("create_issue", lost, applied=True)
    world.fails()
    world.tracker.failures.fail_next("list_issues", ServiceError(TrackerCode.PROVIDER_ERROR, "x"))

    error = world.fails()

    assert (error.step, error.may_have_applied, error.retryable) == ("create_issue", True, True)
    assert world.record().step("create_issue").state == "unknown"
    assert_completed_once(world, world.run())


# --- Calendar ---


def test_calendar_refuses(world):
    denied = CalendarError(CalendarCode.ACCESS_DENIED, "no", retryable=False)
    world.calendar.failures.fail_next("create", denied)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == ("permission_denied", "create_event", False)
    assert error.run is not None and error.run["status"] == "partial"
    (issue_id,) = world.tracker.issues
    assert error.run["issue"] == {"id": issue_id} and error.run["event"] is None
    world.tracker.calls.clear()

    assert_completed_once(world, world.run())
    assert world.tracker.calls == []  # only the event and later steps run


def test_calendar_auth_expired(world):
    expired = CalendarError(CalendarCode.PROVIDER_UNAVAILABLE, "reauthorize", retryable=False)
    world.calendar.failures.fail_next("create", expired)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == (
        "provider_unavailable",
        "create_event",
        False,
    )
    assert error.run is not None and error.run["status"] == "partial"
    assert world.record().step("create_event").state == "not_applied"
    assert_completed_once(world, world.run())


def test_calendar_unavailable_then_resume(world):
    outage = CalendarError(CalendarCode.PROVIDER_UNAVAILABLE, "down", retryable=True)
    world.calendar.failures.fail_always(outage)

    first = world.fails()
    second = world.fails()
    world.calendar.failures.fail_always(None)
    result = world.run()

    assert (first.code, first.retryable, first.may_have_applied) == (
        "provider_unavailable",
        True,
        False,
    )
    assert second.run is not None and first.run is not None
    assert second.run["issue"] == first.run["issue"]
    assert_completed_once(world, result)
    assert result.run["issue"] == first.run["issue"]  # the same issue, no second card


def _resolve_run_main() -> Callable[..., int]:
    path = Path(__file__).resolve().parents[1] / "scripts" / "resolve_run.py"
    spec = importlib.util.spec_from_file_location("resolve_run", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main: Callable[..., int] = module.main
    return main


@pytest.mark.parametrize("event_was_made", [True, False], ids=["event made", "no event"])
def test_calendar_unknown_blocks_until_resolved(world, event_was_made, capsys):
    lost = CalendarError(CalendarCode.PROVIDER_ERROR, "no response", retryable=False)
    world.calendar.failures.fail_next("create", lost, applied=event_was_made)

    error = world.fails()

    assert (error.code, error.step) == ("provider_error", "create_event")
    assert (error.retryable, error.may_have_applied) == (False, True)
    assert error.run is not None and error.run["event"] is None
    blocked = world.fails()
    assert (blocked.code, blocked.step, blocked.retryable) == (
        "outcome_unknown",
        "create_event",
        False,
    )
    assert world.calls(world.calendar, "create") == 1  # never created again automatically

    # The operator checks the calendar for the marker and records the answer.
    resolve = _resolve_run_main()
    answer = (
        [f"--event-id={next(iter(world.calendar.events))}"] if event_was_made else ["--no-event"]
    )
    assert resolve([RUN_ID, *answer], storage=world.storage, clock=world.clock) == 0
    assert "Send the same request again" in capsys.readouterr().out

    assert_completed_once(world, world.run())
    assert world.calls(world.calendar, "create") == (1 if event_was_made else 2)
    assert world.calls(world.tracker, "create_issue") == 1


def test_calendar_timeout_is_unknown(world):
    world.calendar.failures.fail_next("create", TimeoutError("timed out"))

    error = world.fails()

    assert (error.code, error.step) == ("provider_error", "create_event")
    assert (error.retryable, error.may_have_applied) == (False, True)
    assert world.record().step("create_event").state == "unknown"
    assert world.fails().code == "outcome_unknown"


# --- A process that stopped during a partner call ---


def test_expired_attempting_calendar_is_unknown(world):
    seed = new_record(REQUEST, RUN_ID, START).with_steps(
        START, create_issue=StepRecord("done", "card"), create_event=StepRecord("attempting")
    )
    world.put_record(seed)
    world.clock.advance(120)

    error = world.fails()

    assert (error.code, error.step) == ("outcome_unknown", "create_event")
    assert world.calendar.calls == []
    assert world.record().step("create_event").state == "unknown"


def test_expired_attempting_issue_is_searched_for_and_adopted(world):
    card = world.tracker.create_issue(meeting_title(REQUEST, RUN_ID))
    world.tracker.calls.clear()
    world.put_record(new_record(REQUEST, RUN_ID, START))  # create_issue attempting
    world.clock.advance(121)

    result = world.run()

    assert_completed_once(world, result)
    assert result.run["issue"] == {"id": card.id}
    assert world.tracker.operations_called() == ["list_issues"]


# --- Record writes, the agenda and the finish ---


def test_record_write_fails_after_issue(world):
    arm = lambda: world.storage.failures.fail_next("replace", UNAVAILABLE)  # noqa: E731
    world.storage_steps.at("replace", 1, arm)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == (
        "provider_unavailable",
        "create_issue",
        True,
    )
    assert error.run is not None and error.run["status"] == "partial"
    (issue_id,) = world.tracker.issues
    assert error.run["issue"] == {"id": issue_id}  # it exists, though the record missed it
    assert world.record().step("create_issue").state == "attempting"
    assert world.fails().code == "run_in_progress"
    world.clock.advance(121)
    assert_completed_once(world, world.run())  # recovery adopts the card


def test_record_write_fails_after_event(world):
    arm = lambda: world.storage.failures.fail_next("replace", UNAVAILABLE)  # noqa: E731
    world.storage_steps.at("replace", 2, arm)

    error = world.fails()

    assert (error.code, error.step) == ("provider_unavailable", "create_event")
    assert error.run is not None
    (event_id,) = world.calendar.events
    assert error.run["event"] is not None and error.run["event"]["id"] == event_id
    assert world.record().step("create_event").state == "attempting"
    world.clock.advance(121)
    # The record cannot say whether the event exists: the unknown-calendar row.
    assert world.fails().code == "outcome_unknown"
    assert world.calls(world.calendar, "create") == 1


@pytest.mark.parametrize("agenda_landed", [False, True], ids=["not written", "written"])
def test_agenda_fails_then_resume(world, agenda_landed):
    arm = lambda: world.storage.failures.fail_next("create", UNAVAILABLE, applied=agenda_landed)  # noqa: E731
    world.storage_steps.at("create", 2, arm)

    error = world.fails()

    assert (error.code, error.step) == ("provider_unavailable", "write_agenda")
    assert (error.retryable, error.may_have_applied) == (True, True)
    assert error.run is not None and error.run["status"] == "partial"
    assert error.run["issue"] is not None and error.run["event"] is not None
    assert error.run["agenda"] is None
    assert world.record().step("write_agenda").state == "unknown"
    world.tracker.calls.clear()
    world.calendar.calls.clear()

    result = world.run()

    assert_completed_once(world, result)
    assert world.tracker.calls == [] and world.calendar.calls == []
    assert [p for p in world.storage.files if p.startswith("/reviews/")] == [AGENDA]


def test_finish_fails_then_resume(world):
    arm = lambda: world.storage.failures.fail_next("replace", UNAVAILABLE)  # noqa: E731
    world.storage_steps.at("replace", 3, arm)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == ("provider_unavailable", "finish_run", True)
    assert error.run is not None and error.run["status"] == "partial"
    assert error.run["agenda"] == {"path": AGENDA}
    assert step_status(error.run, "finish_run") == "failed"
    assert world.record().state == "in_progress"

    assert_completed_once(world, world.run())


# --- An unusable record ---


def _other_request_record() -> bytes:
    other = validate({**BODY, "title": "Another meeting"}, START)
    data = to_bytes(new_record(other, run_id_for(other), START))
    return data.replace(run_id_for(other).encode(), RUN_ID.encode())


@pytest.mark.parametrize(
    "content",
    [b"not json", b'{"version": 2}', _other_request_record()],
    ids=["unreadable", "wrong version", "different request"],
)
def test_record_invalid(world, content):
    world.storage.create(RECORD, content)

    error = world.fails()

    assert (error.code, error.retryable) == ("run_record_invalid", False)
    assert world.storage.files[RECORD].content == content  # unchanged
    assert world.tracker.calls == []


def test_a_record_removed_mid_run_is_invalid(world):
    world.tracker_steps.on_create = lambda: world.storage.delete(RECORD)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == (
        "run_record_invalid",
        "create_issue",
        False,
    )


# --- Two identical requests at once ---


class SignallingLocks:
    """The in-process locks, signalling once a second request is waiting for the run."""

    def __init__(self) -> None:
        self.inner = InProcessRunLocks()
        self.second_is_waiting = threading.Event()
        self._count = 0
        self._guard = threading.Lock()

    @contextmanager
    def hold(self, run_id: str) -> Iterator[None]:
        with self._guard:
            self._count += 1
            if self._count == 2:
                self.second_is_waiting.set()
        with self.inner.hold(run_id):
            yield


def test_per_run_lock_serializes():
    locks = SignallingLocks()
    world = World(locks=locks)

    # The first request holds the run while the second arrives.
    def wait_for_the_second() -> None:
        locks.second_is_waiting.wait(timeout=5)

    world.tracker_steps.on_create = wait_for_the_second
    results: list[RunResult] = []
    threads = [threading.Thread(target=lambda: results.append(world.run())) for _ in range(2)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(result.replayed for result in results) == [False, True]
    assert world.calls(world.tracker, "create_issue") == 1
    assert world.calls(world.calendar, "create") == 1


def test_the_lock_map_is_empty_after_concurrent_requests_for_a_run_finish():
    locks = SignallingLocks()
    world = World(locks=locks)
    in_flight: list[int] = []

    def wait_for_the_second() -> None:
        locks.second_is_waiting.wait(timeout=5)
        in_flight.append(len(locks.inner))  # one holds the run's lock, one waits for it

    world.tracker_steps.on_create = wait_for_the_second
    threads = [threading.Thread(target=world.run) for _ in range(2)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert in_flight == [1]
    assert len(locks.inner) == 0


def test_a_lock_is_released_from_the_map_even_when_the_run_fails(world):
    locks = InProcessRunLocks()
    world.orchestrator.locks = locks
    world.storage.failures.fail_next("create", UNAVAILABLE)

    world.fails()

    assert len(locks) == 0


# --- A bug ---


def test_unexpected_exception_in_an_implementation_is_internal_error(world):
    world.tracker.failures.fail_next("create_issue", RuntimeError("bug"), applied=True)

    error = world.fails()

    assert (error.code, error.step, error.retryable) == ("internal_error", "create_issue", False)
    assert world.record().step("create_issue").state == "unknown"
    assert world.calendar.calls == []


def test_unexpected_exception_in_an_adapter_propagates_and_the_record_says_where(world):
    def broken() -> None:
        raise RuntimeError("adapter bug")

    world.tracker_steps.on_create = broken

    with pytest.raises(RuntimeError):
        world.run()

    assert world.record().step("create_issue").state == "attempting"
    assert world.calendar.calls == []
