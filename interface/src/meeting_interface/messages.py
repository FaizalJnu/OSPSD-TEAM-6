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


# Why a run ended without a reply (agent service stop reasons, product/docs/agent.md).
STOP_REASONS = {
    "max_steps": "The agent took too many steps without finishing. Try a more specific request.",
    "timeout": "The agent ran out of time. Try again, or ask for less at once.",
    "token_limit": "The agent ran out of room for this request. Try a shorter request.",
    "cancelled": "The request was stopped before the agent finished.",
    "rate_limited": "The language model is busy. Wait a minute and send it again.",
    "model_error": "The language model failed. Send it again in a minute.",
}
UNKNOWN_STOP = "The agent stopped without an answer. Send it again."

# The agent service's error codes. Approving and rejecting are decided there,
# never here: these only say what happened and what to do next.
AGENT_HELP = {
    "stale_proposal": ErrorHelp(
        "This proposal changed since you saw it.",
        "Review the newest proposal in the chat and approve that one.",
    ),
    "proposal_superseded": ErrorHelp(
        "A newer proposal replaced this one.",
        "Review the newer proposal in the chat and approve that one.",
    ),
    "proposal_rejected": ErrorHelp(
        "This proposal was rejected.",
        "Ask the agent for a new proposal if you still want the meeting.",
    ),
    "proposal_not_pending": ErrorHelp(
        "This proposal is no longer waiting for a decision.",
        "Reload the chat to see what happened to it.",
    ),
    "execution_failed": ErrorHelp(
        "The approved changes could not be made.",
        "Approve again to retry. Nothing that already exists is created twice.",
    ),
    "rate_limited": ErrorHelp(
        "You sent several messages in a short time.",
        "Wait, then send your message again.",
    ),
    "busy": ErrorHelp(
        "The agent is busy with other requests.",
        "Wait, then send your message again.",
    ),
    "payload_too_large": ErrorHelp(
        "That message is too long.",
        "Shorten it to under 4,000 characters and send it again.",
    ),
    "not_found": ErrorHelp(
        "That conversation or proposal was not found.",
        "Reload the chat and start again.",
    ),
    "unauthorized": ErrorHelp(
        "You are not signed in.",
        "Sign in, then send your message again.",
    ),
    "invalid_request": ErrorHelp(
        "The agent could not read that request.",
        "Reload the page and try again.",
    ),
}


def stop_reason_text(reason: str) -> str:
    return STOP_REASONS.get(reason, UNKNOWN_STOP)


def agent_help(code: str) -> ErrorHelp:
    return AGENT_HELP.get(code) or ERROR_HELP.get(code, UNKNOWN_ERROR)
