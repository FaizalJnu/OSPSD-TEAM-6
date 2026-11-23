"""Words the person sees: step names and what to do after each error.

This module only translates. It holds no product rules: whether a step ran,
failed, or may have happened always comes from the API service.
"""

from dataclasses import dataclass

from meeting_interface.api_client import API_UNREACHABLE, BAD_RESPONSE
from meeting_interface.models import StepStatus

STEP_LABELS = {
    "read_issues": "Read open issues",
    "find_event": "Find the review event",
    "book_event": "Book the review event",
    "save_agenda": "Save the agenda",
    "link_agenda": "Link the agenda on the event and issue",
}

STATUS_LABELS = {
    StepStatus.PENDING: "Waiting",
    StepStatus.RUNNING: "Working",
    StepStatus.SUCCEEDED: "Done",
    StepStatus.FAILED: "Failed",
    StepStatus.UNCERTAIN: "Not sure",
    StepStatus.SKIPPED: "Not run",
}


@dataclass(frozen=True)
class ErrorHelp:
    title: str
    next_step: str


# One entry per code in the API's error model (docs/API.md), plus the two the
# interface raises itself. tests/test_errors.py fails if a code is missing.
ERROR_HELP = {
    "invalid_request": ErrorHelp(
        "Something in the form is not valid.",
        "Check the fields named below, fix them, and run it again.",
    ),
    "permission_denied": ErrorHelp(
        "A connected service refused access.",
        "Reconnect that service from your connections page, then run it again.",
    ),
    "not_found": ErrorHelp(
        "Something the run needs does not exist.",
        "Check the project and meeting date, then run it again.",
    ),
    "conflict": ErrorHelp(
        "Part of this already exists.",
        "Open the existing item from the links above instead of creating it again.",
    ),
    "file_too_large": ErrorHelp(
        "The agenda is too large to save.",
        "Shorten the agenda, then run it again.",
    ),
    "provider_error": ErrorHelp(
        "A connected service refused the request.",
        "Try again later. If it keeps failing, tell the team which step failed.",
    ),
    "provider_unavailable": ErrorHelp(
        "A connected service could not be reached.",
        "Wait a minute and run it again. Steps marked Done will not be repeated.",
    ),
    "route_not_found": ErrorHelp(
        "This page asked the service for something it does not offer.",
        "Reload the page. If it happens again, tell the team.",
    ),
    "method_not_allowed": ErrorHelp(
        "This page asked the service for something it does not offer.",
        "Reload the page. If it happens again, tell the team.",
    ),
    "internal_error": ErrorHelp(
        "The service failed unexpectedly.",
        "Check the links above before retrying: a step may have finished.",
    ),
    API_UNREACHABLE: ErrorHelp(
        "The service could not be reached.",
        "Check your connection and run it again in a minute.",
    ),
    BAD_RESPONSE: ErrorHelp(
        "The service sent a reply this page does not understand.",
        "Run it again. If it keeps happening, tell the team.",
    ),
}

UNKNOWN_ERROR = ErrorHelp(
    "Something went wrong.",
    "Run it again. If it keeps happening, tell the team which step failed.",
)


def step_label(step: str) -> str:
    return STEP_LABELS.get(step, step.replace("_", " ").capitalize())


def status_label(status: StepStatus) -> str:
    return STATUS_LABELS[status]


def error_help(code: str) -> ErrorHelp:
    return ERROR_HELP.get(code, UNKNOWN_ERROR)
