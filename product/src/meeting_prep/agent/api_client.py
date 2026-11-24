"""What the agent needs from our API service: per-user reads and one execute call.

The agent never calls a provider. Its tools read through this interface, and an
approved proposal is executed only through ``execute``, which the API service checks
against the approval again before it changes anything (remaining-work.md, D). The API
service's client implements this protocol; tests use a fake.

``user`` is always our internal user ID, taken from the signed-in session, never from
the model or the request body.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from meeting_prep.agent.proposals import Approval, Proposal

OutcomeStatus = Literal["succeeded", "failed", "uncertain"]


@dataclass(frozen=True)
class OpenIssue:
    id: str
    title: str


@dataclass(frozen=True)
class UpcomingEvent:
    id: str
    title: str
    start: str
    end: str


@dataclass(frozen=True)
class Document:
    path: str
    content: str


@dataclass(frozen=True)
class ActionOutcome:
    """What happened to one action. ``detail`` is the API's structured answer."""

    index: int
    kind: str
    status: OutcomeStatus
    detail: Mapping[str, object] = field(default_factory=dict)


class ApiError(Exception):
    """The API service refused or failed. ``code`` is one of its error codes.

    ``may_have_applied`` is true when an execute call failed without saying what it did.
    """

    def __init__(self, code: str, message: str, *, may_have_applied: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.may_have_applied = may_have_applied


class ApiClient(Protocol):
    async def list_open_issues(self, user: str, limit: int) -> list[OpenIssue]: ...

    async def list_upcoming_events(self, user: str, days: int) -> list[UpcomingEvent]: ...

    async def read_document(self, user: str, path: str) -> Document: ...

    async def execute(
        self, user: str, proposal: Proposal, approval: Approval
    ) -> list[ActionOutcome]:
        """Execute an approved proposal and return each action's outcome, in order.

        The API service checks the approval against the proposal and the user again.
        """
        ...
