"""A stand-in for the API service, for tests and for trying the pages locally.

With no scripted reply, a word in the meeting title picks the outcome, so a
person can see each case by hand. The replies follow design §1.4.
"""

from meeting_interface.api_client import API_UNREACHABLE, ApiError
from meeting_interface.models import Run, RunRequest, RunResult, Step, StepStatus

STEPS = ("claim_run", "create_issue", "create_event", "write_agenda", "finish_run")


def run_with(*statuses: StepStatus, status: str, **ids: str | None) -> Run:
    """A run whose five steps have these statuses, in order; missing ones are pending."""
    padded = [*statuses, *[StepStatus.PENDING] * (len(STEPS) - len(statuses))]
    return Run(
        run_id="3f9a1c0d7b2e",
        status=status,
        steps=[Step(name, s) for name, s in zip(STEPS, padded, strict=True)],
        **ids,
    )


OK, FAILED, UNKNOWN = StepStatus.OK, StepStatus.FAILED, StepStatus.UNKNOWN
COMPLETED = run_with(
    OK,
    OK,
    OK,
    OK,
    OK,
    status="completed",
    issue_id="6b01c2",
    event_id="evt-81",
    event_start="2026-11-27T20:00:00Z",
    event_end="2026-11-27T20:30:00Z",
    agenda_path="/reviews/2026-11-27-sprint-review-3f9a1c0d7b2e.md",
)


class FakeApiClient:
    def __init__(self) -> None:
        self.requests: list[RunRequest] = []
        self.next_result: RunResult | None = None
        self.next_error: ApiError | None = None

    def run_review_meeting(self, request: RunRequest) -> RunResult:
        self.requests.append(request)
        if self.next_error is not None:
            raise self.next_error
        if self.next_result is not None:
            return self.next_result
        return _demo(request.title.lower())


def _demo(title: str) -> RunResult:
    if "down" in title:
        raise ApiError(API_UNREACHABLE, "the service could not be reached")
    if "fail" in title:
        raise ApiError(
            "provider_unavailable",
            "The calendar could not be reached. Send the same request again later.",
            step="create_event",
            retryable=True,
            run=run_with(OK, OK, FAILED, status="partial", issue_id="6b01c2"),
        )
    if "unsure" in title:
        raise ApiError(
            "provider_error",
            "The calendar did not confirm the event. It may have been created.",
            step="create_event",
            may_have_applied=True,
            run=run_with(OK, OK, UNKNOWN, status="partial", issue_id="6b01c2"),
        )
    if "busy" in title:
        raise ApiError(
            "run_in_progress",
            "Another request is working on this run.",
            retry_after=87,
            run=run_with(OK, UNKNOWN, status="partial"),
        )
    if "stuck" in title:
        raise ApiError(
            "outcome_unknown",
            "An earlier attempt may have created the event.",
            step="create_event",
            run=run_with(OK, OK, UNKNOWN, status="partial", issue_id="6b01c2"),
        )
    return RunResult(replayed="again" in title, run=COMPLETED)
