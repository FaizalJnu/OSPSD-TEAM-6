"""Words the person sees: step names and what to do after each error.

This module only translates. It holds no product rules: whether a step ran,
failed, or may have happened, and whether a retry is safe, always come from the
API service.
"""

from dataclasses import dataclass

from meeting_interface.api_client import API_UNREACHABLE, BAD_RESPONSE
from meeting_interface.models import StepStatus

# design §1.3: the five steps, in order.
STEP_LABELS = {
    "claim_run": "Start the run",
    "create_issue": "Open the tracker issue",
    "create_event": "Book the calendar event",
    "write_agenda": "Save the agenda",
    "finish_run": "Finish",
}

STATUS_LABELS = {
    StepStatus.OK: "Done",
    StepStatus.FAILED: "Failed",
    StepStatus.UNKNOWN: "Not sure",
    StepStatus.PENDING: "Not run",
}


@dataclass(frozen=True)
class ErrorHelp:
    title: str
    next_step: str


# One entry per code in design §1.4, plus the two the interface raises itself.
# tests/test_errors.py fails if a code is missing.
ERROR_HELP = {
    "invalid_request": ErrorHelp(
        "Something in the form is not valid.",
        "Fix the field named below and send it again.",
    ),
    "unauthorized": ErrorHelp(
        "This page is not allowed to use the service.",
        "Tell the team: the interface's API key is missing or wrong.",
    ),
    "permission_denied": ErrorHelp(
        "A connected service refused access.",
        "Tell the team which step failed. They need to fix that service's access first.",
    ),
    "run_in_progress": ErrorHelp(
        "Another request is already working on this meeting.",
        "Wait, then press Try again. Nothing will be created twice.",
    ),
    "outcome_unknown": ErrorHelp(
        "We could not tell whether the calendar event was created.",
        "A team member must check the calendar before this meeting can continue. "
        "Tell the team the run ID below.",
    ),
    "run_record_invalid": ErrorHelp(
        "This meeting's saved progress cannot be read.",
        "Tell the team the run ID below.",
    ),
    "provider_error": ErrorHelp(
        "A connected service failed.",
        "Follow the advice below. If it keeps failing, tell the team which step failed.",
    ),
    "provider_unavailable": ErrorHelp(
        "A connected service could not be reached.",
        "Follow the advice below. Steps marked Done will not be repeated.",
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
        "Check the steps below before trying again: a step may have finished.",
    ),
    API_UNREACHABLE: ErrorHelp(
        "The service could not be reached.",
        "Check your connection and try again in a minute.",
    ),
    BAD_RESPONSE: ErrorHelp(
        "The service sent a reply this page does not understand.",
        "Try again. If it keeps happening, tell the team.",
    ),
}

UNKNOWN_ERROR = ErrorHelp(
    "Something went wrong.",
    "Try again. If it keeps happening, tell the team which step failed.",
)


def step_label(name: str) -> str:
    return STEP_LABELS.get(name, name.replace("_", " ").capitalize())


def status_label(status: StepStatus) -> str:
    return STATUS_LABELS[status]


def error_help(code: str) -> ErrorHelp:
    return ERROR_HELP.get(code, UNKNOWN_ERROR)
