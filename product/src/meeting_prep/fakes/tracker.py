"""In-memory ``IssueProvider`` (issue-tracker-contract v1.1.0).

Issue IDs look like Trello card IDs (24 hexadecimal characters), and
``list_issues`` returns the newest first, as the contract requires.
"""

import re

from issue_tracker_contract import (
    MAX_LIST_LIMIT,
    MAX_TITLE_LENGTH,
    ErrorCode,
    Issue,
    IssueProvider,
    IssueUpdate,
    ServiceError,
)

from meeting_prep.fakes._failures import FakeBase


class FakeTracker(FakeBase, IssueProvider):
    """Issues in a dict, in creation order."""

    OPERATIONS = frozenset(
        {"get_issue", "update_issue", "delete_issue", "create_issue", "list_issues"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.issues: dict[str, Issue] = {}
        self._created = 0

    def get_issue(self, issue_id: str, *, fresh: bool = False) -> Issue:
        with self._lock:
            failure = self._start("get_issue", issue_id, fresh)
            issue = self._lookup(issue_id)
            self._finish(failure)
            return issue

    def update_issue(self, issue_id: str, changes: IssueUpdate) -> Issue:
        with self._lock:
            failure = self._start("update_issue", issue_id, changes)
            issue = self._lookup(issue_id)
            if changes.title is not None:
                issue = Issue(id=issue.id, title=_checked_title(changes.title))
                self.issues[issue_id] = issue
            self._finish(failure)
            return issue

    def delete_issue(self, issue_id: str) -> None:
        with self._lock:
            failure = self._start("delete_issue", issue_id)
            self._lookup(issue_id)
            del self.issues[issue_id]
            self._finish(failure)

    def create_issue(self, title: str) -> Issue:
        with self._lock:
            failure = self._start("create_issue", title)
            self._created += 1
            issue = Issue(id=f"{self._created:024x}", title=_checked_title(title))
            self.issues[issue.id] = issue
            self._finish(failure)
            return issue

    def list_issues(self, *, limit: int) -> list[Issue]:
        with self._lock:
            failure = self._start("list_issues", limit)
            if not 1 <= limit <= MAX_LIST_LIMIT:
                # The contract says the caller has already checked the limit.
                raise ValueError(f"limit must be 1 to {MAX_LIST_LIMIT}")
            newest_first = list(reversed(self.issues.values()))[:limit]
            self._finish(failure)
            return newest_first

    def _lookup(self, issue_id: str) -> Issue:
        issue = self.issues.get(issue_id)
        if issue is None:
            raise ServiceError(
                ErrorCode.NOT_FOUND,
                "Issue not found",
                provider_involved=True,
                cause="fake_missing_issue",
            )
        return issue


def failing_tracker() -> FakeTracker:
    """A tracker that refuses every call and writes nothing (registry name ``fake-failing``)."""
    tracker = FakeTracker()
    tracker.failures.fail_always(
        ServiceError(
            ErrorCode.PROVIDER_ERROR,
            "The issue tracker is currently unavailable",
            provider_involved=True,
            cause="fake_failing",
            may_have_applied=False,
        )
    )
    return tracker


def _checked_title(title: str) -> str:
    """Reject a title the contract's IssueTitle would reject: our caller has a bug."""
    if not 1 <= len(title) <= MAX_TITLE_LENGTH or not re.search(r"\S", title):
        raise ServiceError(
            ErrorCode.INVALID_INPUT,
            f"Title must be 1 to {MAX_TITLE_LENGTH} characters and not blank",
            cause="fake_invalid_title",
            may_have_applied=False,
        )
    return title
