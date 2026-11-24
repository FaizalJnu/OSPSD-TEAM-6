"""The agenda document (design §1.3): its path and its Markdown bytes.

Pure. The bytes depend only on the request, the run ID and the recorded IDs, so a
resumed run writes exactly the same document (design §2.3).
"""

import re

from meeting_prep.run_record import MeetingRequest

SLUG_LENGTH = 40
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def slug(title: str) -> str:
    """Lowercase ASCII letters and digits; anything else becomes one "-". At most 40 characters.

    A trailing "-" is removed, and a title with nothing left becomes "review".
    """
    text = _NOT_SLUG.sub("-", title.lower())[:SLUG_LENGTH].rstrip("-")
    return text or "review"


def agenda_path(request: MeetingRequest, run_id: str) -> str:
    """``/reviews/<UTC date>-<slug>-<run_id>.md``."""
    return f"/reviews/{request.start[:10]}-{slug(request.title)}-{run_id}.md"


def render(request: MeetingRequest, run_id: str, *, issue_id: str, event_id: str) -> bytes:
    lines = [
        f"# Review: {request.title}",
        "",
        f"- When: {request.start} to {request.end}",
        f"- Calendar event: {event_id}",
        f"- Tracker issue: {issue_id}",
        f"- Run: {run_id}",
        "",
        "## Agenda",
        "",
    ]
    if request.agenda:
        lines += [f"{number}. {item}" for number, item in enumerate(request.agenda, start=1)]
    else:
        lines.append("No agenda items.")
    return ("\n".join(lines) + "\n").encode("utf-8")
