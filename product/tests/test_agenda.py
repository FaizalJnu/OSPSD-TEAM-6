"""The agenda document (design §1.3): its path, its slug, and its exact bytes."""

import pytest

from meeting_prep.agenda import agenda_path, render, slug
from meeting_prep.orchestrator import validate
from meeting_prep.run_record import run_id_for
from tests.fake_adapters import START

BODY = {
    "title": "Storage v0.2.0 release review",
    "start": "2026-11-20T15:00:00-05:00",
    "end": "2026-11-20T15:30:00-05:00",
    "agenda": ["Folder delete results on OCI", "Open bugs", "Release go or no-go"],
}
REQUEST = validate(BODY, START)
RUN_ID = run_id_for(REQUEST)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Storage v0.2.0 release review", "storage-v0-2-0-release-review"),
        ("Sprint  12 -- Retro!!", "sprint-12-retro"),
        ("Revue de l'équipe", "revue-de-l-quipe"),  # non-ASCII becomes "-"
        ("Café", "caf"),  # a trailing "-" is removed
        ("!!!", "review"),
        ("日本語", "review"),
        ("a" * 39 + " b", "a" * 39),  # cut to 40, then the trailing "-" removed
        ("x" * 60, "x" * 40),
    ],
)
def test_slug(title, expected):
    assert slug(title) == expected


def test_the_path_is_the_utc_date_then_the_slug_then_the_run_id():
    assert agenda_path(REQUEST, RUN_ID) == (
        f"/reviews/2026-11-20-storage-v0-2-0-release-review-{RUN_ID}.md"
    )


def test_the_path_uses_the_utc_date_not_the_local_one():
    late = validate(
        {**BODY, "start": "2026-11-20T22:00:00-05:00", "end": "2026-11-20T22:30:00-05:00"}, START
    )

    assert agenda_path(late, run_id_for(late)).startswith("/reviews/2026-11-21-")


def test_the_agenda_bytes_follow_the_design():
    content = render(REQUEST, RUN_ID, issue_id="6b01c2", event_id="evt-9")

    assert (
        content
        == (
            "# Review: Storage v0.2.0 release review\n"
            "\n"
            "- When: 2026-11-20T20:00:00Z to 2026-11-20T20:30:00Z\n"
            "- Calendar event: evt-9\n"
            "- Tracker issue: 6b01c2\n"
            f"- Run: {RUN_ID}\n"
            "\n"
            "## Agenda\n"
            "\n"
            "1. Folder delete results on OCI\n"
            "2. Open bugs\n"
            "3. Release go or no-go\n"
        ).encode()
    )


def test_the_same_inputs_always_give_the_same_bytes():
    first = render(REQUEST, RUN_ID, issue_id="a", event_id="b")

    assert render(validate(BODY, START), RUN_ID, issue_id="a", event_id="b") == first


def test_an_empty_agenda_says_so():
    empty = validate({**BODY, "agenda": []}, START)

    assert render(empty, run_id_for(empty), issue_id="a", event_id="b").endswith(
        b"## Agenda\n\nNo agenda items.\n"
    )


def test_non_ascii_text_is_utf8():
    request = validate({**BODY, "agenda": ["Résumé"]}, START)

    assert "1. Résumé\n".encode() in render(request, RUN_ID, issue_id="a", event_id="b")
