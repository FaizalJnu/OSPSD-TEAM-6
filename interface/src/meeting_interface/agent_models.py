"""Shapes the interface reads from the agent service (product/docs/agent.md).

The interface displays them. Whether a change was approved, ran, or may have run
always comes from the agent service and the API behind it.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class OutcomeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"

    @classmethod
    def parse(cls, value: object) -> "OutcomeStatus":
        # A status we do not know is never shown as done.
        try:
            return cls(str(value))
        except ValueError:
            return cls.UNCERTAIN


@dataclass(frozen=True)
class Action:
    kind: str
    operation: str | None
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Outcome:
    index: int
    kind: str
    status: OutcomeStatus
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Proposal:
    id: str
    status: str  # pending, approved, executed, rejected or superseded
    proposal_hash: str
    actions: list[Action]
    outcomes: list[Outcome] = field(default_factory=list)
    supersedes: str | None = None

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "Proposal":
        return cls(
            id=str(body["id"]),
            status=str(body["status"]),
            proposal_hash=str(body["proposal_hash"]),
            actions=[
                Action(
                    kind=str(a["kind"]),
                    operation=None if a.get("operation") is None else str(a["operation"]),
                    arguments=dict(a.get("arguments") or {}),
                )
                for a in body["actions"]
            ],
            outcomes=[
                Outcome(
                    index=int(o["index"]),
                    kind=str(o["kind"]),
                    status=OutcomeStatus.parse(o.get("status")),
                    detail=dict(o.get("detail") or {}),
                )
                for o in body.get("outcomes", [])
            ],
            supersedes=None if body.get("supersedes") is None else str(body["supersedes"]),
        )


@dataclass(frozen=True)
class ChatLine:
    role: str  # user or assistant
    content: str


@dataclass(frozen=True)
class Conversation:
    id: str
    time_zone: str
    messages: list[ChatLine]
    pending_proposal: Proposal | None

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "Conversation":
        pending = body.get("pending_proposal")
        return cls(
            id=str(body["id"]),
            time_zone=str(body.get("time_zone", "UTC")),
            messages=[ChatLine(str(m["role"]), str(m["content"])) for m in body["messages"]],
            pending_proposal=Proposal.from_json(pending) if isinstance(pending, dict) else None,
        )


@dataclass(frozen=True)
class MessageReply:
    text: str | None
    stop_reason: str
    run_id: str | None
    proposal: Proposal | None
    retry_after: int | None

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "MessageReply":
        proposal = body.get("proposal")
        reply = body.get("reply")
        retry = body.get("retry_after")
        return cls(
            text=None if reply is None else str(reply),
            stop_reason=str(body["stop_reason"]),
            run_id=None if body.get("run_id") is None else str(body["run_id"]),
            proposal=Proposal.from_json(proposal) if isinstance(proposal, dict) else None,
            retry_after=retry if isinstance(retry, int) else None,
        )
