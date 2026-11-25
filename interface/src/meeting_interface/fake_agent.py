"""A stand-in for the agent service, for tests and for trying the chat locally.

With nothing scripted, a word in the message picks the outcome, so a person can see
each case by hand: "prep" proposes a review meeting, "fail" proposes one whose
execution fails, "busy" is rate limited, and "stop" ends the run on a limit.
"""

from meeting_interface.agent_client import AgentError
from meeting_interface.agent_models import (
    Action,
    Conversation,
    MessageReply,
    Outcome,
    OutcomeStatus,
    Proposal,
)

REVIEW = Action(
    kind="create_review_meeting",
    operation="POST /v1/review-meetings",
    arguments={
        "title": "Sprint review",
        "start": "2026-11-27T15:00:00-05:00",
        "end": "2026-11-27T15:30:00-05:00",
        "agenda": ["Open bugs", "Release go or no-go"],
    },
)


def proposal(proposal_id: str = "p-1", status: str = "pending", **changes: object) -> Proposal:
    fields: dict[str, object] = {
        "id": proposal_id,
        "status": status,
        "proposal_hash": f"hash-{proposal_id}",
        "actions": [REVIEW],
    }
    return Proposal(**{**fields, **changes})  # type: ignore[arg-type]


class FakeAgentClient:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.approvals: list[tuple[str, str]] = []
        self.rejections: list[str] = []
        self.next_reply: MessageReply | None = None
        self.next_error: AgentError | None = None
        self.next_proposal: Proposal | None = None
        self._proposals: dict[str, Proposal] = {}
        self.tokens: list[str] = []

    def as_user(self, token: str) -> "FakeAgentClient":
        self.tokens.append(token)
        return self

    def start_conversation(self, time_zone: str) -> Conversation:
        self.started.append(time_zone)
        return Conversation(f"c-{len(self.started)}", time_zone, [], None)

    def send_message(self, conversation_id: str, text: str) -> MessageReply:
        self.sent.append((conversation_id, text))
        self._raise_if_scripted()
        if self.next_reply is not None:
            return self.next_reply
        return self._demo(text.lower())

    def get_proposal(self, proposal_id: str) -> Proposal:
        self._raise_if_scripted()
        return self._proposals.get(proposal_id) or proposal(proposal_id)

    def approve(self, proposal_id: str, proposal_hash: str) -> Proposal:
        self.approvals.append((proposal_id, proposal_hash))
        self._raise_if_scripted()
        if self.next_proposal is not None:
            return self.next_proposal
        current = self._proposals.get(proposal_id) or proposal(proposal_id)
        if proposal_hash != current.proposal_hash:
            raise AgentError("stale_proposal", "The proposal changed since you saw it.")
        if proposal_id.startswith("fail"):
            raise AgentError(
                "execution_failed",
                "The meeting could not be prepared. It may have been partly applied.",
                may_have_applied=True,
            )
        done = Outcome(0, REVIEW.kind, OutcomeStatus.SUCCEEDED, {"run_id": "3f9a1c0d7b2e"})
        return proposal(proposal_id, "executed", outcomes=[done])

    def reject(self, proposal_id: str) -> Proposal:
        self.rejections.append(proposal_id)
        self._raise_if_scripted()
        if self.next_proposal is not None:
            return self.next_proposal
        return proposal(proposal_id, "rejected")

    def _raise_if_scripted(self) -> None:
        if self.next_error is not None:
            raise self.next_error

    def _demo(self, text: str) -> MessageReply:
        if "busy" in text:
            raise AgentError("busy", "The agent is busy.", retry_after=30)
        if "stop" in text:
            return MessageReply(None, "token_limit", "r-demo", None, None)
        if "prep" in text or "fail" in text:
            made = proposal("fail-1" if "fail" in text else "p-1")
            self._proposals[made.id] = made
            return MessageReply(
                "Here is what I would create. Approve it to go ahead.",
                "completed",
                "r-demo",
                made,
                None,
            )
        return MessageReply(
            "I can prepare a review meeting. Tell me which one.", "completed", "r-demo", None, None
        )
