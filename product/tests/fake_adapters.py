"""Test stand-ins for the adapters, over the #108 fakes, until the real adapters land.

They translate the fakes' contract errors into StepError with the rows of design
§1.5 that the orchestrator tests need, and nothing more. The real translation, and
its tests, belong to the adapters (design §5).

``StorageSteps.at(operation, n, action)`` runs ``action`` just before the nth call to
``operation``: to arm a planned failure (``fake.failures.fail_next``) for that call,
or to move the clock forward during it.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from calendar_contract import CalendarError, CreateEvent
from calendar_contract import ErrorCode as CalendarCode
from cloud_storage_api import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
)
from issue_tracker_contract import ErrorCode as TrackerCode
from issue_tracker_contract import ServiceError

from meeting_prep.adapters import IssueSummary, Step, StepError
from meeting_prep.fakes import FakeCalendar, FakeStorage, FakeTracker


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


START = datetime(2026, 11, 18, 21, 0, 0, tzinfo=UTC)


class StorageSteps:
    def __init__(self, fake: FakeStorage) -> None:
        self.fake = fake
        self._counts: dict[str, int] = {}
        self._actions: dict[tuple[str, int], Callable[[], None]] = {}

    def at(self, operation: str, n: int, action: Callable[[], None]) -> None:
        self._actions[(operation, n)] = action

    def create(self, step: Step, path: str, content: bytes) -> bool:
        self._before("create")
        try:
            self.fake.create(path, content)
        except ConflictError:
            return False
        except Exception as error:
            raise _storage_error(step, error, write=True) from None
        return True

    def replace(self, step: Step, path: str, content: bytes) -> None:
        self._before("replace")
        try:
            self.fake.replace(path, content)
        except Exception as error:
            raise _storage_error(step, error, write=True) from None

    def download(self, step: Step, path: str) -> bytes:
        self._before("download")
        try:
            return self.fake.download(path)
        except Exception as error:
            raise _storage_error(step, error, write=False) from None

    def _before(self, operation: str) -> None:
        self._counts[operation] = self._counts.get(operation, 0) + 1
        action = self._actions.pop((operation, self._counts[operation]), None)
        if action is not None:
            action()


class TrackerSteps:
    def __init__(self, fake: FakeTracker) -> None:
        self.fake = fake
        self.on_create: Callable[[], None] | None = None

    def create_issue(self, title: str, token: str) -> str:
        if self.on_create is not None:
            self.on_create()
        try:
            return self.fake.create_issue(title).id
        except Exception as error:
            raise _tracker_error(error, write=True) from None

    def recover_issue(self, token: str, title_marker: str) -> str | None:
        return next((i.id for i in self.list_issues(100) if title_marker in i.title), None)

    def list_issues(self, limit: int) -> list[IssueSummary]:
        try:
            return [IssueSummary(i.id, i.title) for i in self.fake.list_issues(limit=limit)]
        except Exception as error:
            raise _tracker_error(error, write=False) from None


class CalendarSteps:
    def __init__(self, fake: FakeCalendar) -> None:
        self.fake = fake

    def create(self, title: str, start: str, end: str) -> str:
        try:
            return self.fake.create(CreateEvent(title=title, start=start, end=end)).id
        except Exception as error:
            raise _calendar_error(error) from None


def _storage_error(step: Step, error: Exception, *, write: bool) -> StepError:
    name = type(error).__name__
    if isinstance(error, PermissionDeniedError):
        return StepError(step, "permission_denied", retryable=False, may_have_applied=False)
    if isinstance(error, NotFoundError):
        return StepError(step, "run_record_invalid", retryable=False, may_have_applied=False)
    if isinstance(error, ProviderUnavailableError):
        return StepError(
            step, "provider_unavailable", retryable=True, may_have_applied=write, provider_code=name
        )
    if isinstance(error, ProviderError):
        return StepError(
            step, "provider_error", retryable=False, may_have_applied=write, provider_code=name
        )
    if isinstance(error, InvalidRequestError):
        return StepError(step, "internal_error", retryable=False, may_have_applied=False)
    return StepError(step, "internal_error", retryable=False, may_have_applied=write)


def _tracker_error(error: Exception, *, write: bool) -> StepError:
    if not isinstance(error, ServiceError):
        return StepError("create_issue", "internal_error", retryable=False, may_have_applied=write)
    code = error.code.name
    if error.code == TrackerCode.ACCESS_DENIED:
        return StepError(
            "create_issue",
            "permission_denied",
            retryable=False,
            may_have_applied=False,
            provider_code=code,
        )
    if error.code == TrackerCode.SERVICE_NOT_CONFIGURED:
        return StepError(
            "create_issue",
            "provider_unavailable",
            retryable=False,
            may_have_applied=False,
            provider_code=code,
        )
    if error.code == TrackerCode.PROVIDER_ERROR:
        may = write and bool(error.may_have_applied)
        return StepError(
            "create_issue",
            "provider_error",
            retryable=may,
            may_have_applied=may,
            provider_code=code,
        )
    return StepError("create_issue", "internal_error", retryable=False, may_have_applied=False)


def _calendar_error(error: Exception) -> StepError:
    if isinstance(error, TimeoutError):
        return StepError(
            "create_event",
            "provider_error",
            retryable=False,
            may_have_applied=True,
            provider_code="TimeoutError",
        )
    if not isinstance(error, CalendarError):
        return StepError("create_event", "internal_error", retryable=False, may_have_applied=True)
    code = error.code.name
    if error.code == CalendarCode.ACCESS_DENIED:
        return StepError(
            "create_event",
            "permission_denied",
            retryable=False,
            may_have_applied=False,
            provider_code=code,
        )
    if error.code == CalendarCode.PROVIDER_UNAVAILABLE:
        return StepError(
            "create_event",
            "provider_unavailable",
            retryable=error.retryable,
            may_have_applied=False,
            provider_code=code,
        )
    if error.code == CalendarCode.PROVIDER_ERROR:
        return StepError(
            "create_event",
            "provider_error",
            retryable=False,
            may_have_applied=True,
            provider_code=code,
        )
    return StepError("create_event", "internal_error", retryable=False, may_have_applied=False)
