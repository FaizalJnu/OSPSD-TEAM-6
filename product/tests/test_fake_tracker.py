"""The in-memory IssueProvider follows issue-tracker-contract v1.1.0."""

import pytest
from issue_tracker_contract import ErrorCode, IssueProvider, IssueUpdate, ServiceError

from meeting_prep.fakes import FakeTracker, failing_tracker


@pytest.fixture
def tracker():
    return FakeTracker()


def test_it_is_an_issue_provider(tracker):
    assert isinstance(tracker, IssueProvider)


def test_create_then_get_returns_the_title_exactly(tracker):
    issue = tracker.create_issue("Review: release [3f9a1c0d7b2e]")

    assert len(issue.id) == 24
    assert tracker.get_issue(issue.id, fresh=True) == issue


def test_list_is_newest_first_and_limited(tracker):
    ids = [tracker.create_issue(f"Issue {n}").id for n in range(3)]

    assert [issue.id for issue in tracker.list_issues(limit=2)] == [ids[2], ids[1]]
    assert tracker.list_issues(limit=100)[-1].id == ids[0]


def test_a_limit_outside_the_contract_is_a_bug_in_the_caller(tracker):
    with pytest.raises(ValueError):
        tracker.list_issues(limit=101)


def test_update_and_delete(tracker):
    issue = tracker.create_issue("Old title")

    assert tracker.update_issue(issue.id, IssueUpdate(title="New title")).title == "New title"
    tracker.delete_issue(issue.id)

    with pytest.raises(ServiceError) as error:
        tracker.get_issue(issue.id)
    assert error.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize("title", ["", "   ", "x" * 257])
def test_a_title_the_contract_forbids_is_refused_without_writing(tracker, title):
    with pytest.raises(ServiceError) as error:
        tracker.create_issue(title)

    assert error.value.code == ErrorCode.INVALID_INPUT
    assert tracker.issues == {}


def test_a_lost_create_response_leaves_the_issue_for_recovery_to_find(tracker):
    lost = ServiceError(ErrorCode.PROVIDER_ERROR, "no response", may_have_applied=True)
    tracker.failures.fail_next("create_issue", lost, applied=True)

    with pytest.raises(ServiceError):
        tracker.create_issue("Review: x [3f9a1c0d7b2e]")

    assert [issue.title for issue in tracker.list_issues(limit=100)] == ["Review: x [3f9a1c0d7b2e]"]


def test_the_failing_tracker_refuses_every_call_and_says_nothing_was_written():
    tracker = failing_tracker()

    with pytest.raises(ServiceError) as error:
        tracker.create_issue("Review")

    assert error.value.code == ErrorCode.PROVIDER_ERROR
    assert error.value.may_have_applied is False
    assert tracker.issues == {}
