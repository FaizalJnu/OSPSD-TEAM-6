"""Calendar writes distinguish refusal from an unknown outcome."""

from calendar_contract import CalendarError, CalendarService, CreateEvent, ErrorCode

from meeting_prep.adapters.base import Step, StepError


class EventCalendarAdapter:
    def __init__(self, calendar: CalendarService) -> None:
        self._calendar = calendar

    def create(self, title: str, start: str, end: str) -> str:
        try:
            return self._calendar.create(CreateEvent(title=title, start=start, end=end)).id
        except Exception as error:
            raise _translate(error) from None


def _translate(error: Exception) -> StepError:
    step: Step = "create_event"
    if isinstance(error, TimeoutError):
        return StepError(
            step,
            "provider_error",
            retryable=False,
            may_have_applied=True,
            provider_code="TimeoutError",
        )
    if not isinstance(error, CalendarError):
        return StepError(
            step,
            "internal_error",
            retryable=False,
            may_have_applied=True,
            provider_code=type(error).__name__,
        )
    code = error.code.name
    if error.code == ErrorCode.ACCESS_DENIED:
        return StepError(
            step, "permission_denied", retryable=False, may_have_applied=False, provider_code=code
        )
    if error.code == ErrorCode.PROVIDER_UNAVAILABLE:
        return StepError(
            step,
            "provider_unavailable",
            retryable=error.retryable,
            may_have_applied=False,
            provider_code=code,
        )
    if error.code == ErrorCode.PROVIDER_ERROR:
        return StepError(
            step, "provider_error", retryable=False, may_have_applied=True, provider_code=code
        )
    return StepError(
        step, "internal_error", retryable=False, may_have_applied=False, provider_code=code
    )
