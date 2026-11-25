"""Issue tracker translation and recovery through the configured contract."""

import re
from typing import Protocol, runtime_checkable

from issue_tracker_contract import ErrorCode, Issue, IssueProvider, ServiceError

from meeting_prep.adapters.base import IssueSummary, Step, StepError

_PROVIDER_STATUS = re.compile(r"provider_status=[1-5][0-9]{2}")


@runtime_checkable
class _TaggedTracker(Protocol):
    def create_tagged_issue(self, title: str, creation_token: str) -> Issue: ...

    def find_tagged_issue(self, creation_token: str) -> Issue | None: ...


class IssueTrackerAdapter:
    def __init__(self, tracker: IssueProvider) -> None:
        self._tracker = tracker
        self._tagged = tracker if isinstance(tracker, _TaggedTracker) else None

    @property
    def tagged(self) -> bool:
        return self._tagged is not None

    def create_tagged_issue(self, step: Step, title: str, token: str) -> str:
        assert self._tagged is not None
        try:
            return self._tagged.create_tagged_issue(title, token).id
        except Exception as error:
            raise _translate(step, error, write=True) from None

    def find_tagged_issue(self, step: Step, token: str) -> str | None:
        assert self._tagged is not None
        try:
            issue = self._tagged.find_tagged_issue(token)
            return issue.id if issue is not None else None
        except Exception as error:
            raise _translate(step, error, write=False) from None

    def create_issue(self, title: str) -> str:
        try:
            return self._tracker.create_issue(title).id
        except Exception as error:
            raise _translate("create_issue", error, write=True) from None

    def list_issues(self, limit: int) -> list[IssueSummary]:
        try:
            return [IssueSummary(i.id, i.title) for i in self._tracker.list_issues(limit=limit)]
        except Exception as error:
            raise _translate("create_issue", error, write=False) from None


def _translate(step: Step, error: Exception, *, write: bool) -> StepError:
    if not isinstance(error, ServiceError):
        return StepError(
            step,
            "internal_error",
            retryable=False,
            may_have_applied=write,
            provider_code=type(error).__name__,
        )
    code = error.code.name
    if error.code == ErrorCode.ACCESS_DENIED:
        return StepError(
            step, "permission_denied", retryable=False, may_have_applied=False, provider_code=code
        )
    if error.code == ErrorCode.SERVICE_NOT_CONFIGURED:
        return StepError(
            step,
            "provider_unavailable",
            retryable=False,
            may_have_applied=False,
            provider_code=code,
        )
    if error.code == ErrorCode.PROVIDER_ERROR:
        # Only a known refusal proves that a write did not happen.
        uncertain = write and error.may_have_applied
        cause = error.cause
        status = cause if isinstance(cause, str) and _PROVIDER_STATUS.fullmatch(cause) else None
        return StepError(
            step,
            "provider_error",
            retryable=uncertain,
            may_have_applied=uncertain,
            provider_code=code,
            provider_cause=status,
        )
    return StepError(
        step,
        "internal_error",
        retryable=False,
        may_have_applied=write and error.may_have_applied,
        provider_code=code,
    )
