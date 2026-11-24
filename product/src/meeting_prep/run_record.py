"""The run record (design §1.6): its JSON shape, the step states, and the resume rules.

Pure: no I/O, and the caller passes the time. The orchestrator stores the record at
``/review-runs/<run_id>.json`` and rewrites it between steps (design §2.2), so after
any failure it says which steps finished, which one was in flight, and which never
started.

Step states:

* ``pending``: not started.
* ``attempting``: this step's write was about to be sent. For ``create_issue`` and
  ``create_event`` it is also a lease: for 120 seconds after ``updated_at``, the run
  belongs to the request that wrote it.
* ``done``: finished, with the provider's ID for the issue and the event.
* ``unknown``: the write may have happened.
* ``not_applied``: the write was refused, or never sent.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Literal, cast

VERSION = 1
RUN_ID_LENGTH = 12
LEASE = timedelta(seconds=120)
# A tracker or calendar write starts only if fewer than this many seconds have
# passed since the record write that took the lease (design §2.2).
GUARD = timedelta(seconds=20)

StepState = Literal["pending", "attempting", "done", "unknown", "not_applied"]
RunState = Literal["in_progress", "completed"]
STEP_STATES: tuple[StepState, ...] = ("pending", "attempting", "done", "unknown", "not_applied")
RUN_STATES: tuple[RunState, ...] = ("in_progress", "completed")
RecordedStep = Literal["create_issue", "create_event", "write_agenda"]
RECORDED_STEPS: tuple[RecordedStep, ...] = ("create_issue", "create_event", "write_agenda")
# Steps that call a partner, and so take the lease while attempting.
LEASED_STEPS: tuple[RecordedStep, ...] = ("create_issue", "create_event")

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class InvalidRecord(ValueError):
    """The bytes at a run's path are not a record for that run."""


@dataclass(frozen=True)
class MeetingRequest:
    """A validated request, normalized: title trimmed, times in UTC (``...Z``)."""

    title: str
    start: str
    end: str
    agenda: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {"title": self.title, "start": self.start, "end": self.end, "agenda": [*self.agenda]}


@dataclass(frozen=True)
class StepRecord:
    state: StepState
    id: str | None = None


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    request: MeetingRequest
    state: RunState
    updated_at: datetime
    steps: dict[RecordedStep, StepRecord]

    def step(self, name: RecordedStep) -> StepRecord:
        return self.steps[name]

    def with_step(
        self, name: RecordedStep, state: StepState, now: datetime, *, id: str | None = None
    ) -> RunRecord:
        return self.with_steps(now, **{name: StepRecord(state, id)})

    def with_steps(self, now: datetime, **changes: StepRecord) -> RunRecord:
        steps = dict(self.steps)
        for name, step in changes.items():
            steps[cast(RecordedStep, name)] = step
        return replace(self, steps=steps, updated_at=_whole_seconds(now))

    def completed(self, now: datetime) -> RunRecord:
        return replace(self, state="completed", updated_at=_whole_seconds(now))


def request_token(request: MeetingRequest) -> str:
    """The full SHA-256 (64 hex characters) of the request's canonical JSON (design §1.3).

    The times are already in UTC, so requests that differ only in their offset get the
    same token. Tagged tracker recovery (design §2.3) searches for it.
    """
    canonical = json.dumps(
        {
            "title": request.title,
            "start_utc": request.start,
            "end_utc": request.end,
            "agenda": [*request.agenda],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def run_id_for(request: MeetingRequest) -> str:
    """The run ID: the first 12 characters of the request's token."""
    return request_token(request)[:RUN_ID_LENGTH]


def record_path(run_id: str) -> str:
    return f"/review-runs/{run_id}.json"


def marker(run_id: str) -> str:
    """The marker in the issue and event titles, which tracker recovery searches for."""
    return f"[{run_id}]"


def meeting_title(request: MeetingRequest, run_id: str) -> str:
    """The issue's and the event's title: ``Review: <title> [<run_id>]``."""
    return f"Review: {request.title} {marker(run_id)}"


def new_record(request: MeetingRequest, run_id: str, now: datetime) -> RunRecord:
    """The record step 1 creates: every step pending, and create_issue attempting."""
    return RunRecord(
        run_id=run_id,
        request=request,
        state="in_progress",
        updated_at=_whole_seconds(now),
        steps={
            "create_issue": StepRecord("attempting"),
            "create_event": StepRecord("pending"),
            "write_agenda": StepRecord("pending"),
        },
    )


# --- Resume rules (design §2.2, §2.3) ---


@dataclass(frozen=True)
class Lease:
    """A live request owns the run. Retry after ``retry_after`` whole seconds."""

    step: RecordedStep
    retry_after: int


def live_lease(record: RunRecord, now: datetime) -> Lease | None:
    """The lease another request holds, if a partner step is attempting and under 120 s old."""
    age = now - record.updated_at
    if record.state == "completed" or age >= LEASE:
        return None
    for name in LEASED_STEPS:
        if record.step(name).state == "attempting":
            return Lease(name, max(1, ceil((LEASE - age).total_seconds())))
    return None


def issue_needs_search(record: RunRecord) -> bool:
    """An earlier create_issue may have made a card: search for the marker before creating."""
    return record.step("create_issue").state in ("attempting", "unknown")


def event_outcome_unknown(record: RunRecord, now: datetime) -> bool:
    """The event may exist with no known ID. Never create it again automatically.

    True when the step is unknown, or attempting after its lease: the request that
    started it stopped, and its call has finished by now (design §2.2).
    """
    step = record.step("create_event")
    expired = now - record.updated_at >= LEASE
    return step.state == "unknown" or (step.state == "attempting" and expired)


def resolve_event(record: RunRecord, event_id: str | None, now: datetime) -> RunRecord:
    """Record an operator's answer for an unknown calendar step (scripts/resolve_run.py).

    With an event ID, the step is done and the next same request writes the agenda.
    With None (the operator found no event), it is not_applied and the next same
    request creates the event. Raises ValueError if there is nothing to resolve.
    """
    if record.state == "completed" or not event_outcome_unknown(record, now):
        raise ValueError(
            "the run's calendar step is not unknown; if it is attempting, "
            "wait until its 120-second lease has passed"
        )
    if event_id is None:
        return record.with_step("create_event", "not_applied", now)
    if not event_id.strip():
        raise ValueError("the event ID must not be blank")
    return record.with_steps(
        now,
        create_event=StepRecord("done", event_id.strip()),
        write_agenda=StepRecord("pending"),
    )


# --- JSON ---


def to_bytes(record: RunRecord) -> bytes:
    document = {
        "version": VERSION,
        "run_id": record.run_id,
        "request": record.request.as_json(),
        "state": record.state,
        "updated_at": record.updated_at.strftime(_TIME_FORMAT),
        "steps": {
            name: {"state": step.state} | ({} if step.id is None else {"id": step.id})
            for name, step in record.steps.items()
        },
    }
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def from_bytes(data: bytes, run_id: str) -> RunRecord:
    """Parse a record and check it belongs to ``run_id``. Raises InvalidRecord.

    The caller compares ``request`` with its own: a record for the same path but a
    different request is invalid too.
    """
    try:
        document = json.loads(data.decode("utf-8"))
        if not isinstance(document, dict) or document.get("version") != VERSION:
            raise InvalidRecord("not a version 1 run record")
        if document.get("run_id") != run_id:
            raise InvalidRecord("the record names a different run")
        state = document["state"]
        if state not in RUN_STATES:
            raise InvalidRecord("unknown run state")
        return RunRecord(
            run_id=run_id,
            request=_request(document["request"]),
            state=state,
            updated_at=datetime.strptime(document["updated_at"], _TIME_FORMAT).replace(tzinfo=UTC),
            steps={
                name: _step(document["steps"][name], has_id=name in LEASED_STEPS)
                for name in RECORDED_STEPS
            },
        )
    except InvalidRecord:
        raise
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
        raise InvalidRecord("the run record cannot be read") from error


def _request(value: object) -> MeetingRequest:
    if not isinstance(value, dict):
        raise InvalidRecord("the record has no request")
    title, start, end, agenda = value["title"], value["start"], value["end"], value["agenda"]
    texts = [title, start, end, *agenda] if isinstance(agenda, list) else None
    if texts is None or not all(isinstance(text, str) for text in texts):
        raise InvalidRecord("the record's request is malformed")
    return MeetingRequest(title=title, start=start, end=end, agenda=tuple(agenda))


def _step(value: object, *, has_id: bool) -> StepRecord:
    """One step. The issue and event steps hold an ID when done, and only then."""
    if not isinstance(value, dict) or value.get("state") not in STEP_STATES:
        raise InvalidRecord("unknown step state")
    step_id = value.get("id")
    expects_id = has_id and value["state"] == "done"
    if (step_id is not None or expects_id) and not (expects_id and isinstance(step_id, str)):
        raise InvalidRecord("a done issue or event step needs an ID, and only it has one")
    return StepRecord(value["state"], step_id)


def _whole_seconds(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(microsecond=0)
