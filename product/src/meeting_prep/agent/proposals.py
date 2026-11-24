"""Proposals and approvals, agent side. Pure: no I/O.

A proposal holds the exact actions and arguments the agent wants to run for one user,
and a SHA-256 hash of their canonical JSON. An approval is stored against the
proposal's ID, that hash and the user. A changed proposal is a new proposal with a new
hash, and the old one is superseded, so an approval can never cover changes the person
did not see. Execution checks ``approval_matches`` on every path, retries included.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# The one write the agent can propose: the fixed review-meeting workflow.
REVIEW_MEETING = "create_review_meeting"
OPERATIONS = {REVIEW_MEETING: "POST /v1/review-meetings"}

ProposalStatus = Literal["pending", "approved", "executed", "rejected", "superseded"]


@dataclass(frozen=True)
class Action:
    """One change: an API operation (``kind``) and its exact arguments."""

    kind: str
    arguments: Mapping[str, object]

    def as_json(self) -> dict[str, object]:
        return {"kind": self.kind, "arguments": dict(self.arguments)}


@dataclass(frozen=True)
class Proposal:
    id: str
    user_id: str
    conversation_id: str
    actions: tuple[Action, ...]
    hash: str
    status: ProposalStatus
    created_at: datetime
    supersedes: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class Approval:
    id: str
    proposal_id: str
    proposal_hash: str
    user_id: str
    approved_at: datetime


def canonical_json(user_id: str, actions: Sequence[Action]) -> bytes:
    """Sorted keys, no spaces, UTF-8: the same proposal always gives the same bytes."""
    document = {"user_id": user_id, "actions": [action.as_json() for action in actions]}
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def proposal_hash(user_id: str, actions: Sequence[Action]) -> str:
    return hashlib.sha256(canonical_json(user_id, actions)).hexdigest()


def approval_matches(approval: Approval | None, proposal: Proposal, user_id: str) -> bool:
    """The approval is for this proposal, its exact contents, and this user."""
    return (
        approval is not None
        and approval.proposal_id == proposal.id
        and approval.proposal_hash == proposal.hash == proposal_hash(user_id, proposal.actions)
        and approval.user_id == proposal.user_id == user_id
    )


def proposal_view(proposal: Proposal) -> dict[str, object]:
    """A proposal as the API shows it: the exact changes, so a person can approve them."""
    return {
        "id": proposal.id,
        "conversation_id": proposal.conversation_id,
        "status": proposal.status,
        "proposal_hash": proposal.hash,
        "actions": [
            {**action.as_json(), "operation": OPERATIONS.get(action.kind)}
            for action in proposal.actions
        ],
        "supersedes": proposal.supersedes,
        "created_at": proposal.created_at.isoformat(),
    }


def actions_from_json(value: object) -> tuple[Action, ...]:
    """Actions as stored. Raises ValueError for anything else."""
    if not isinstance(value, list):
        raise ValueError("actions must be a list")
    actions = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            raise ValueError("an action needs a kind")
        arguments = item.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError("an action needs arguments")
        actions.append(Action(item["kind"], arguments))
    return tuple(actions)
