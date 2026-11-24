"""The run record (design §1.6), the run ID, and the lease and resume rules (design §2.2)."""

import hashlib
import json
from datetime import timedelta

import pytest

from meeting_prep.orchestrator import validate
from meeting_prep.run_record import (
    InvalidRecord,
    StepRecord,
    event_outcome_unknown,
    from_bytes,
    live_lease,
    new_record,
    record_path,
    resolve_event,
    run_id_for,
    to_bytes,
)
from tests.fake_adapters import START

BODY = {
    "title": "Storage v0.2.0 release review",
    "start": "2026-11-20T15:00:00-05:00",
    "end": "2026-11-20T15:30:00-05:00",
    "agenda": ["Open bugs"],
}
REQUEST = validate(BODY, START)
RUN_ID = run_id_for(REQUEST)


def run_id(**changes: object) -> str:
    return run_id_for(validate({**BODY, **changes}, START))


def test_the_run_id_is_the_first_12_hex_of_sha256_over_the_canonical_json():
    canonical = json.dumps(
        {
            "agenda": ["Open bugs"],
            "end_utc": "2026-11-20T20:30:00Z",
            "start_utc": "2026-11-20T20:00:00Z",
            "title": "Storage v0.2.0 release review",
        },
        separators=(",", ":"),
    ).encode("utf-8")

    assert RUN_ID == hashlib.sha256(canonical).hexdigest()[:12]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-20T20:00:00Z", "2026-11-20T20:30:00Z"),
        ("2026-11-20T20:00:00+00:00", "2026-11-20T20:30:00+00:00"),
        ("2026-11-21T01:30:00+05:30", "2026-11-21T02:00:00+05:30"),
    ],
)
def test_the_same_instants_in_another_offset_are_the_same_run(start, end):
    assert run_id(start=start, end=end) == RUN_ID


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Storage v0.2.1 release review"},
        {"agenda": ["Open bugs", "Release"]},
        {"agenda": []},
        {"end": "2026-11-20T15:31:00-05:00"},
    ],
)
def test_a_different_title_agenda_or_time_is_a_different_run(changes):
    assert run_id(**changes) != RUN_ID


def test_surrounding_spaces_in_the_title_are_the_same_run():
    assert run_id(title="  Storage v0.2.0 release review ") == RUN_ID


def test_non_ascii_text_is_hashed_as_utf8():
    request = validate({**BODY, "title": "Revue de l'équipe"}, START)
    canonical = json.dumps(
        {
            "agenda": ["Open bugs"],
            "end_utc": request.end,
            "start_utc": request.start,
            "title": "Revue de l'équipe",
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    assert run_id_for(request) == hashlib.sha256(canonical).hexdigest()[:12]


def test_the_record_has_the_design_shape():
    record = new_record(REQUEST, RUN_ID, START)

    assert record_path(RUN_ID) == f"/review-runs/{RUN_ID}.json"
    assert json.loads(to_bytes(record)) == {
        "version": 1,
        "run_id": RUN_ID,
        "request": {
            "title": "Storage v0.2.0 release review",
            "start": "2026-11-20T20:00:00Z",
            "end": "2026-11-20T20:30:00Z",
            "agenda": ["Open bugs"],
        },
        "state": "in_progress",
        "updated_at": "2026-11-18T21:00:00Z",
        "steps": {
            "create_issue": {"state": "attempting"},
            "create_event": {"state": "pending"},
            "write_agenda": {"state": "pending"},
        },
    }


def test_a_record_round_trips_with_ids_and_whole_seconds():
    later = START + timedelta(seconds=5, microseconds=700)
    record = (
        new_record(REQUEST, RUN_ID, START)
        .with_steps(later, create_issue=StepRecord("done", "card-1"))
        .with_steps(later, create_event=StepRecord("done", "event-1"))
        .with_step("write_agenda", "done", later)
        .completed(later)
    )

    parsed = from_bytes(to_bytes(record), RUN_ID)

    assert parsed == record
    assert parsed.updated_at == START + timedelta(seconds=5)


@pytest.mark.parametrize(
    "edit",
    [
        lambda doc: doc.update(version=2),
        lambda doc: doc.update(run_id="000000000000"),
        lambda doc: doc.update(state="stuck"),
        lambda doc: doc["steps"]["create_issue"].update(state="maybe"),
        lambda doc: doc["steps"]["create_event"].update(state="done"),  # no ID
        lambda doc: doc["steps"]["create_issue"].update(id="card"),  # ID while attempting
        lambda doc: doc["steps"]["write_agenda"].update(state="done", id="x"),
        lambda doc: doc["request"].update(agenda="Open bugs"),
        lambda doc: doc.update(updated_at="yesterday"),
        lambda doc: doc["steps"].pop("write_agenda"),
    ],
)
def test_a_record_that_is_not_one_for_this_run_is_invalid(edit):
    document = json.loads(to_bytes(new_record(REQUEST, RUN_ID, START)))
    edit(document)

    with pytest.raises(InvalidRecord):
        from_bytes(json.dumps(document).encode(), RUN_ID)


@pytest.mark.parametrize("data", [b"", b"\xff\xfe", b"[]", b"null"])
def test_bytes_that_are_not_a_record_are_invalid(data):
    with pytest.raises(InvalidRecord):
        from_bytes(data, RUN_ID)


# --- The lease ---


def test_an_attempting_partner_step_holds_the_lease_for_120_seconds():
    record = new_record(REQUEST, RUN_ID, START)  # create_issue attempting

    lease = live_lease(record, START + timedelta(seconds=30.2))

    assert lease is not None and (lease.step, lease.retry_after) == ("create_issue", 90)
    assert live_lease(record, START + timedelta(seconds=119.5)) is not None
    assert live_lease(record, START + timedelta(seconds=120)) is None


def test_the_agenda_step_and_a_completed_run_take_no_lease():
    record = new_record(REQUEST, RUN_ID, START).with_steps(
        START,
        create_issue=StepRecord("done", "card"),
        create_event=StepRecord("done", "event"),
        write_agenda=StepRecord("attempting"),
    )

    assert live_lease(record, START) is None
    assert live_lease(new_record(REQUEST, RUN_ID, START).completed(START), START) is None


# --- An unknown calendar step ---


def _calendar(state: str) -> object:
    return new_record(REQUEST, RUN_ID, START).with_steps(
        START,
        create_issue=StepRecord("done", "card"),
        create_event=StepRecord(state),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("state", "age", "unknown"),
    [
        ("unknown", 0, True),
        ("attempting", 120, True),
        ("attempting", 119, False),
        ("not_applied", 500, False),
        ("pending", 500, False),
    ],
)
def test_when_the_calendar_outcome_is_unknown(state, age, unknown):
    record = _calendar(state)

    assert event_outcome_unknown(record, START + timedelta(seconds=age)) is unknown  # type: ignore[arg-type]


def test_resolving_with_an_event_id_marks_it_done():
    resolved = resolve_event(_calendar("unknown"), " event-7 ", START)  # type: ignore[arg-type]

    assert resolved.step("create_event") == StepRecord("done", "event-7")
    assert resolved.step("write_agenda").state == "pending"


def test_resolving_with_no_event_lets_the_next_request_create_it():
    resolved = resolve_event(_calendar("unknown"), None, START)  # type: ignore[arg-type]

    assert resolved.step("create_event").state == "not_applied"


@pytest.mark.parametrize("state", ["done", "pending", "not_applied", "attempting"])
def test_there_is_nothing_to_resolve_unless_the_calendar_is_unknown(state):
    record = _calendar(state)
    if state == "done":
        record = new_record(REQUEST, RUN_ID, START).with_steps(
            START, create_event=StepRecord("done", "event")
        )

    with pytest.raises(ValueError):
        resolve_event(record, "event", START)  # type: ignore[arg-type]


def test_a_blank_event_id_is_refused():
    with pytest.raises(ValueError, match="blank"):
        resolve_event(_calendar("unknown"), "  ", START)  # type: ignore[arg-type]
