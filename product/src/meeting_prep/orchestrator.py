"""POST /v1/review-meetings without the web: validate, claim the run, run the steps, report.

Design §1.3 traces one run, §2.2 and §2.3 give the lease and the resume rules, and
§3.1 lists what each failure leaves behind. In order:

0. ``validate`` the body, with no provider call. The run ID and every path and
   title follow from it.
1. claim_run: create the run record. If it exists, read it and resume: a completed
   run is replayed, a live lease is ``run_in_progress``, and an unknown calendar
   outcome is ``outcome_unknown``.
2. create_issue: recover a possibly created card before attempting another write.
3. create_event: never retried once its outcome is unknown.
4. write_agenda, then 5. finish_run, which marks the record completed.

Before each partner write the record says attempting, and after it the record
holds the ID. Nothing after a failed step runs. The response is built from the
record. The orchestrator calls only the adapters (``meeting_prep.adapters``) and
imports no web framework; the HTTP layer maps each code to a status.
"""

import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from meeting_prep.adapters import (
    CalendarAdapter,
    Step,
    StepError,
    StorageAdapter,
    TrackerAdapter,
)
from meeting_prep.agenda import agenda_path, render
from meeting_prep.run_record import (
    GUARD,
    RECORDED_STEPS,
    InvalidRecord,
    MeetingRequest,
    RecordedStep,
    RunRecord,
    StepRecord,
    StepState,
    creation_token_for,
    event_outcome_unknown,
    from_bytes,
    issue_needs_search,
    live_lease,
    marker,
    meeting_title,
    new_record,
    record_path,
    run_id_for,
    to_bytes,
)

TITLE_LENGTH = 120
AGENDA_ITEMS = 20
AGENDA_ITEM_LENGTH = 200
LONGEST_MEETING = timedelta(hours=8)
FURTHEST_START = timedelta(days=365)

_FIELDS = ("title", "start", "end", "agenda")
# RFC 3339 with whole seconds and an explicit offset ("Z" or "+hh:mm").
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})")
_STORAGE_STEPS = ("claim_run", "write_agenda", "finish_run")

Clock = Callable[[], datetime]


class ReviewMeetingError(Exception):
    """The operation failed. The HTTP layer turns ``code`` into a status (design §1.4).

    ``run`` is the run as the record says, or None when the request was rejected
    before step 1. ``retry_after`` is set for ``run_in_progress``. ``message`` never
    holds provider text, a credential, a title or an agenda item.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        step: Step | None = None,
        retryable: bool = False,
        may_have_applied: bool = False,
        run: dict[str, object] | None = None,
        retry_after: int | None = None,
        provider_code: str | None = None,
        provider_cause: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.step = step
        self.retryable = retryable
        self.may_have_applied = may_have_applied
        self.run = run
        self.retry_after = retry_after
        self.provider_code = provider_code
        self.provider_cause = provider_cause

    def body(self) -> dict[str, object]:
        """The error body: the HW1 envelope plus step, retryable and may_have_applied."""
        error = {
            "code": self.code,
            "message": self.message,
            "step": self.step,
            "retryable": self.retryable,
            "may_have_applied": self.may_have_applied,
        }
        return {"error": error, "run": self.run}


@dataclass(frozen=True)
class RunResult:
    """A completed run. ``replayed`` is true when an earlier request completed it."""

    replayed: bool
    run: dict[str, object]

    def body(self) -> dict[str, object]:
        return {
            "status": self.run["status"],
            "run_id": self.run["run_id"],
            "replayed": self.replayed,
            **{key: value for key, value in self.run.items() if key not in ("status", "run_id")},
        }


class RunLocks(Protocol):
    def hold(self, run_id: str) -> AbstractContextManager[None]:
        """Hold the run's lock: one request at a time works on a run in this process."""
        ...


class InProcessRunLocks:
    """One lock per run ID. With one worker process this closes the create race (design §2.2).

    A run's lock is kept only while a request holds it or waits for it, so the map
    holds the runs in flight, not every run ever seen.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        # Each run's lock, and how many requests hold it or wait for it.
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

    def __len__(self) -> int:
        """How many runs have a request holding or waiting for their lock."""
        with self._guard:
            return len(self._locks)

    @contextmanager
    def hold(self, run_id: str) -> Iterator[None]:
        with self._guard:
            lock, users = self._locks.get(run_id, (threading.Lock(), 0))
            self._locks[run_id] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                lock, users = self._locks[run_id]
                if users == 1:
                    del self._locks[run_id]  # nobody else holds it or waits for it
                else:
                    self._locks[run_id] = (lock, users - 1)


def utc_now() -> datetime:
    return datetime.now(UTC)


def validate(body: Mapping[str, object], now: datetime) -> MeetingRequest:
    """Step 0: check the whole body and normalize it. Raises invalid_request.

    The strictest rule from each contract, plus ours: a trimmed title of 1 to 120
    characters; start and end in RFC 3339 with an offset and whole seconds, end after
    start and at most 8 hours later, start within the next 365 days; 0 to 20 agenda
    items of 1 to 200 characters. Messages name the field, never its value.
    """
    unknown = sorted(set(body) - set(_FIELDS))
    if unknown:
        raise _invalid(f"unknown field: {unknown[0]}")
    missing = [name for name in _FIELDS if name not in body]
    if missing:
        raise _invalid(f"{missing[0]} is required")

    title = body["title"]
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= TITLE_LENGTH:
        raise _invalid(f"title must be 1 to {TITLE_LENGTH} characters after trimming")
    start, end = _instant(body, "start"), _instant(body, "end")
    if end <= start:
        raise _invalid("end must be after start")
    if end - start > LONGEST_MEETING:
        raise _invalid("the meeting must be at most 8 hours long")
    if not now <= start <= now + FURTHEST_START:
        raise _invalid("start must be within the next 365 days")

    agenda = body["agenda"]
    if not isinstance(agenda, list) or len(agenda) > AGENDA_ITEMS:
        raise _invalid(f"agenda must be a list of at most {AGENDA_ITEMS} items")
    for item in agenda:
        if not isinstance(item, str) or not 1 <= len(item) <= AGENDA_ITEM_LENGTH:
            raise _invalid(f"each agenda item must be 1 to {AGENDA_ITEM_LENGTH} characters")

    return MeetingRequest(
        title=title.strip(), start=_utc_text(start), end=_utc_text(end), agenda=tuple(agenda)
    )


class Orchestrator:
    """Runs the review-meeting workflow over three adapters. Build one per process."""

    def __init__(
        self,
        storage: StorageAdapter,
        tracker: TrackerAdapter,
        calendar: CalendarAdapter,
        *,
        clock: Clock = utc_now,
        locks: RunLocks | None = None,
    ) -> None:
        self.storage = storage
        self.tracker = tracker
        self.calendar = calendar
        self.clock = clock
        self.locks = locks if locks is not None else InProcessRunLocks()

    def run(self, body: Mapping[str, object]) -> RunResult:
        """Run or resume the request's run. Raises ReviewMeetingError."""
        request = validate(body, self.clock())
        run_id = run_id_for(request)
        with self.locks.hold(run_id):
            return _Attempt(self, request, run_id).execute()


class _Attempt:
    """One request's pass over a run. ``record`` is what this request knows to be true."""

    def __init__(self, deps: Orchestrator, request: MeetingRequest, run_id: str) -> None:
        self.deps = deps
        self.request = request
        self.run_id = run_id
        self.creation_token = creation_token_for(request)
        self.path = record_path(run_id)
        self.record: RunRecord | None = None
        # The partner step whose lease this request wrote, and when (for the 20 s guard).
        self.leased: RecordedStep | None = None
        self.leased_at = datetime.min.replace(tzinfo=UTC)

    def execute(self) -> RunResult:
        replay = self._claim()
        if replay is not None:
            return replay
        self._create_issue()
        self._create_event()
        self._write_agenda_and_finish()
        return RunResult(replayed=False, run=self._view())

    # --- Step 1 ---

    def _claim(self) -> RunResult | None:
        now = self.deps.clock()
        fresh = new_record(self.request, self.run_id, now)
        try:
            created = self.deps.storage.create("claim_run", self.path, to_bytes(fresh))
        except StepError as error:
            raise self._failure(error, claim_failed=True) from None
        if created:
            self.record, self.leased, self.leased_at = fresh, "create_issue", now
            return None

        self.record = self._load()
        if self.record.state == "completed":
            return RunResult(replayed=True, run=self._view())
        now = self.deps.clock()
        lease = live_lease(self.record, now)
        if lease is not None:
            raise ReviewMeetingError(
                "run_in_progress",
                "Another request is working on this run. Send the same request again later.",
                step=lease.step,
                retryable=True,
                run=self._view(),
                retry_after=lease.retry_after,
            )
        if event_outcome_unknown(self.record, now):
            if self.record.step("create_event").state == "attempting":
                # The request that started the create stopped; its call has finished.
                unknown = self.record.with_step("create_event", "unknown", now)
                self._save_once("create_event", unknown)
            raise self._outcome_unknown()
        return None

    def _load(self) -> RunRecord:
        try:
            data = self.deps.storage.download("claim_run", self.path)
        except StepError as error:
            raise self._failure(error, claim_failed=True) from None
        try:
            record = from_bytes(data, self.run_id)
        except InvalidRecord:
            raise self._record_invalid() from None
        if record.request != self.request:
            raise self._record_invalid()
        return record

    # --- Steps 2 and 3 ---

    def _create_issue(self) -> None:
        record = self._current()
        if record.step("create_issue").state == "done":
            return
        search = self.leased != "create_issue" and issue_needs_search(record)
        self._take_lease("create_issue")
        issue_id = self._find_issue() if search else None
        if issue_id is None:
            try:
                issue_id = self.deps.tracker.create_issue(
                    meeting_title(self.request, self.run_id), self.creation_token
                )
            except StepError as error:
                self._record_partner_failure("create_issue", error)
                raise self._failure(error) from None
        self._finish_partner_step("create_issue", issue_id, then="create_event")

    def _find_issue(self) -> str | None:
        """Look for the previous card before another create (design §2.3)."""
        try:
            return self.deps.tracker.recover_issue(self.creation_token, marker(self.run_id))
        except StepError as error:
            # The earlier attempt's card may still exist, so the step stays unknown.
            self._save_once(
                "create_issue",
                self._current().with_step("create_issue", "unknown", self.deps.clock()),
            )
            raise self._failure(error, may_have_applied=True, lookup_failed=True) from None

    def _create_event(self) -> None:
        record = self._current()
        if record.step("create_event").state == "done":
            return
        self._take_lease("create_event")
        try:
            event_id = self.deps.calendar.create(
                meeting_title(self.request, self.run_id), self.request.start, self.request.end
            )
        except StepError as error:
            self._record_partner_failure("create_event", error)
            raise self._failure(error) from None
        self._finish_partner_step("create_event", event_id, then="write_agenda")

    def _take_lease(self, step: RecordedStep) -> None:
        """Write attempting, unless this request already did, then apply the 20 s guard."""
        if self.leased != step:
            now = self.deps.clock()
            before = self._current()
            self._save(step, before.with_step(step, "attempting", now), truth=before)
            self.leased, self.leased_at = step, now
        if self.deps.clock() - self.leased_at >= GUARD:
            # The record write took too long for the lease to cover the partner call.
            skipped = self._current().with_step(step, "not_applied", self.deps.clock())
            self._save_once(step, skipped)
            raise self._failure(
                StepError(step, "provider_unavailable", retryable=True, may_have_applied=False)
            )

    def _record_partner_failure(self, step: RecordedStep, error: StepError) -> None:
        state = _failed_state(error)
        self._save_once(step, self._current().with_step(step, state, self.deps.clock()))

    def _finish_partner_step(self, step: RecordedStep, step_id: str, *, then: RecordedStep) -> None:
        """Record the ID and, in the same write, mark the next step attempting."""
        now = self.deps.clock()
        record = self._current()
        truth = record.with_steps(now, **{step: StepRecord("done", step_id)})
        written = truth.with_steps(now, **{then: StepRecord("attempting")})
        self._save(step, written, truth=truth)
        self.leased, self.leased_at = (then, now) if then == "create_event" else (None, now)

    # --- Steps 4 and 5 ---

    def _write_agenda_and_finish(self) -> None:
        record = self._current()
        issue_id, event_id = record.step("create_issue").id, record.step("create_event").id
        assert issue_id is not None and event_id is not None  # both steps are done
        path = agenda_path(self.request, self.run_id)
        content = render(self.request, self.run_id, issue_id=issue_id, event_id=event_id)
        storage = self.deps.storage
        try:
            # On a resume the agenda may exist: replace it with the same bytes.
            if not storage.create("write_agenda", path, content):
                storage.replace("write_agenda", path, content)
        except StepError as error:
            state = _failed_state(error)
            self._save_once(
                "write_agenda", record.with_step("write_agenda", state, self.deps.clock())
            )
            raise self._failure(error) from None
        now = self.deps.clock()
        truth = record.with_step("write_agenda", "done", now)
        self._save("finish_run", truth.completed(now), truth=truth)

    # --- Writing the record ---

    def _save(self, step: Step, record: RunRecord, *, truth: RunRecord) -> None:
        """Replace the record. If that fails, raise, keeping ``truth`` for the response."""
        try:
            self.deps.storage.replace(step, self.path, to_bytes(record))
        except StepError as error:
            self.record = truth
            raise self._failure(error) from None
        self.record = record

    def _save_once(self, step: Step, record: RunRecord) -> None:
        """Try once to record a failure. The response reports it even if the write fails."""
        self.record = record
        try:
            self.deps.storage.replace(step, self.path, to_bytes(record))
        except StepError:
            pass

    def _current(self) -> RunRecord:
        assert self.record is not None  # set by the claim
        return self.record

    # --- Errors and the response ---

    def _failure(
        self,
        error: StepError,
        *,
        claim_failed: bool = False,
        may_have_applied: bool = False,
        lookup_failed: bool = False,
    ) -> ReviewMeetingError:
        may_have_applied = may_have_applied or error.may_have_applied
        retryable = _retryable(
            error.step,
            error.code,
            may_have_applied,
            error.retryable or (lookup_failed and error.code == "provider_error"),
        )
        if claim_failed:
            run = self._view(claim="unknown" if may_have_applied else "failed")
        else:
            run = self._view(failed=error.step)
        return ReviewMeetingError(
            error.code,
            _message(error.step, error.code, may_have_applied, retryable),
            step=error.step,
            retryable=retryable,
            may_have_applied=may_have_applied,
            run=run,
            provider_code=error.provider_code,
            provider_cause=error.provider_cause,
        )

    def _outcome_unknown(self) -> ReviewMeetingError:
        return ReviewMeetingError(
            "outcome_unknown",
            "An earlier attempt may have created the calendar event. An operator must check "
            "the calendar and record the answer before this run can continue.",
            step="create_event",
            may_have_applied=True,
            run=self._view(),
        )

    def _record_invalid(self) -> ReviewMeetingError:
        return ReviewMeetingError(
            "run_record_invalid",
            "The run record cannot be read, or belongs to a different request. "
            "An operator must inspect it.",
            step="claim_run",
            run=self._view(claim="failed"),
        )

    def _view(self, *, claim: str = "ok", failed: Step | None = None) -> dict[str, object]:
        """The run as the record says (design §1.4): status, each step, and the known IDs."""
        record = self.record
        if record is None:
            return {
                "run_id": self.run_id,
                "status": "failed",
                "steps": [
                    {"name": name, "status": claim if name == "claim_run" else "pending"}
                    for name in STEP_NAMES
                ],
                "issue": None,
                "event": None,
                "agenda": None,
                "record": {"path": self.path},
            }
        issue, event, agenda = (record.step(name) for name in RECORDED_STEPS)
        if record.state == "completed":
            finish = "ok"
        else:
            finish = "failed" if failed == "finish_run" else "pending"
        may_exist = {"done", "attempting", "unknown"}
        if record.state == "completed":
            status = "completed"
        elif issue.state in may_exist or event.state in may_exist:
            status = "partial"
        else:
            status = "failed"
        return {
            "run_id": self.run_id,
            "status": status,
            "steps": [
                {"name": "claim_run", "status": "ok"},
                *(
                    {"name": name, "status": _STATUS[record.step(name).state]}
                    for name in RECORDED_STEPS
                ),
                {"name": "finish_run", "status": finish},
            ],
            "issue": {"id": issue.id} if issue.state == "done" else None,
            "event": (
                {"id": event.id, "start": self.request.start, "end": self.request.end}
                if event.state == "done"
                else None
            ),
            "agenda": (
                {"path": agenda_path(self.request, self.run_id)} if agenda.state == "done" else None
            ),
            "record": {"path": self.path},
        }


STEP_NAMES: tuple[Step, ...] = (
    "claim_run",
    "create_issue",
    "create_event",
    "write_agenda",
    "finish_run",
)
# How a record's step state appears in a response. attempting means the write may
# have been sent, so the response cannot say more than unknown.
_STATUS = {
    "pending": "pending",
    "attempting": "unknown",
    "done": "ok",
    "unknown": "unknown",
    "not_applied": "failed",
}

_SUBJECT = {
    "claim_run": "Claiming the run record",
    "create_issue": "Creating the tracker issue",
    "create_event": "Booking the calendar event",
    "write_agenda": "Saving the agenda document",
    "finish_run": "Marking the run complete",
}
_REASON = {
    "permission_denied": "the provider refused this service's credentials or permissions",
    "provider_error": "the provider failed or gave an unusable answer",
    "provider_unavailable": "the provider could not be reached",
    "run_record_invalid": "the run record was removed or replaced during the run",
    "internal_error": "the service failed unexpectedly",
}


def _failed_state(error: StepError) -> StepState:
    """A failed write's state: unknown if it may have happened, else not_applied."""
    return "unknown" if error.may_have_applied else "not_applied"


def _retryable(step: Step, code: str, may_have_applied: bool, adapter_says: bool) -> bool:
    """Whether sending the same request again is safe and resumes the run (design §3.1)."""
    if code in ("permission_denied", "run_record_invalid", "internal_error"):
        return False  # a person has to act first
    if step == "create_event" and may_have_applied:
        return False  # the run stops at outcome_unknown
    if step == "create_issue" and may_have_applied:
        return adapter_says  # a retry must first recover the previous tracker write
    if step in _STORAGE_STEPS:
        return True  # repeating a claim, an agenda or a finish is harmless
    return adapter_says  # a refused partner write: retryable if the provider says so


def _message(step: Step, code: str, may_have_applied: bool, retryable: bool) -> str:
    text = f"{_SUBJECT[step]} failed: {_REASON[code]}."
    if may_have_applied:
        text += " It may have been applied."
    if retryable:
        text += " Send the same request again to resume the run."
    elif step == "create_issue" and code == "provider_error":
        text += " Check the tracker settings or wait for a rate limit to clear before resending."
    else:
        text += " An operator must act before the run can continue."
    return text


def _instant(body: Mapping[str, object], name: str) -> datetime:
    value = body[name]
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise _invalid(f"{name} must be RFC 3339 with whole seconds and an explicit offset")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise _invalid(f"{name} is not a real date and time") from None


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _invalid(message: str) -> ReviewMeetingError:
    return ReviewMeetingError("invalid_request", message)
