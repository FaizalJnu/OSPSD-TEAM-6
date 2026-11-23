"""A stand-in for the API service, for tests and for trying the pages locally.

With no scripted reply, the project name picks a scenario, so a person can see
each outcome by hand: include "fail" for a partial failure, "unsure" for an
uncertain step, "down" for an unreachable service.
"""

from meeting_interface.api_client import API_UNREACHABLE, ApiError
from meeting_interface.models import RunRequest, RunResult, StepOutcome, StepStatus


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
        return _demo(request)

    def get_run(self, run_id: str) -> RunResult:
        if self.next_result is None:
            raise ApiError("not_found", f"no run {run_id}")
        return self.next_result


def _demo(request: RunRequest) -> RunResult:
    name = request.project.lower()
    issues = StepOutcome("read_issues", StepStatus.SUCCEEDED, "3 open issues")
    if "down" in name:
        raise ApiError(API_UNREACHABLE, "the service could not be reached")
    if "fail" in name:
        raise ApiError(
            "provider_unavailable",
            "the calendar could not be reached",
            step="book_event",
            steps=[
                issues,
                StepOutcome("book_event", StepStatus.FAILED),
                StepOutcome("save_agenda", StepStatus.SKIPPED),
                StepOutcome("link_agenda", StepStatus.SKIPPED),
            ],
        )
    event = StepOutcome("book_event", StepStatus.SUCCEEDED, None, "https://calendar.example/event")
    agenda_status = StepStatus.UNCERTAIN if "unsure" in name else StepStatus.SUCCEEDED
    if agenda_status is StepStatus.UNCERTAIN:
        agenda = StepOutcome("save_agenda", agenda_status, "the save timed out; it may have run")
    else:
        agenda = StepOutcome("save_agenda", agenda_status, None, "https://storage.example/agenda")
    return RunResult(
        run_id="demo-run",
        status="partial" if "unsure" in name else "succeeded",
        steps=[issues, event, agenda, StepOutcome("link_agenda", StepStatus.SUCCEEDED)],
    )
