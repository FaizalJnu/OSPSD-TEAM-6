"""A fake ApiClient for the agent tests: per-user data, recorded calls, planned failures.

Like the real API service, ``execute`` checks the approval against the proposal and
the user again, and refuses a mismatch. ``token`` stands for the credential a real
client holds; tests check it never reaches a record.
"""

from collections.abc import Mapping

from meeting_prep.agent.api_client import (
    ActionOutcome,
    ApiError,
    Document,
    OpenIssue,
    OutcomeStatus,
    UpcomingEvent,
)
from meeting_prep.agent.proposals import Approval, Proposal, approval_matches


class FakeApi:
    token = "api-token-SECRET-123"

    def __init__(self) -> None:
        self.issues: dict[str, list[OpenIssue]] = {
            "user-a": [OpenIssue("card-2", "Release checklist"), OpenIssue("card-1", "Fix login")],
            "user-b": [OpenIssue("card-9", "B's private issue")],
        }
        self.events: dict[str, list[UpcomingEvent]] = {
            "user-a": [
                UpcomingEvent(
                    "evt-1", "Sprint review", "2026-11-20T20:00:00Z", "2026-11-20T20:30:00Z"
                )
            ]
        }
        self.documents: dict[tuple[str, str], str] = {
            ("user-a", "/reviews/notes.md"): "# Notes\n- ship it\n",
        }
        self.calls: list[tuple[str, str, object]] = []
        self.failures: dict[str, ApiError] = {}
        self.outcome: OutcomeStatus = "succeeded"

    async def list_open_issues(self, user: str, limit: int) -> list[OpenIssue]:
        self._call("list_open_issues", user, limit)
        return self.issues.get(user, [])[:limit]

    async def list_upcoming_events(self, user: str, days: int) -> list[UpcomingEvent]:
        self._call("list_upcoming_events", user, days)
        return self.events.get(user, [])

    async def read_document(self, user: str, path: str) -> Document:
        self._call("read_document", user, path)
        content = self.documents.get((user, path))
        if content is None:
            raise ApiError("not_found", "no document at that path")
        return Document(path, content)

    async def execute(
        self, user: str, proposal: Proposal, approval: Approval
    ) -> list[ActionOutcome]:
        self._call("execute", user, proposal.id)
        if not approval_matches(approval, proposal, user):
            raise ApiError("approval_required", "the approval does not match")
        details: Mapping[str, object] = {"run_id": "3f9a1c0d7b2e", "status": self.outcome}
        return [
            ActionOutcome(index, action.kind, self.outcome, details)
            for index, action in enumerate(proposal.actions)
        ]

    def executed(self) -> list[tuple[str, object]]:
        return [(user, arg) for name, user, arg in self.calls if name == "execute"]

    def _call(self, name: str, user: str, arg: object) -> None:
        self.calls.append((name, user, arg))
        failure = self.failures.pop(name, None)
        if failure is not None:
            raise failure
