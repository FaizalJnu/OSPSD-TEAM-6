"""Queries for the agent service's tables. Every one takes the user ID and filters by it.

A row that belongs to another user is treated exactly like a row that does not exist,
so the caller cannot tell the two apart. The one exception is ``token_usage_since``:
Groq's token limit is shared by every user, so it sums tokens across users. It
returns only times and token counts, never a row. Functions return the agent's own types, never
SQLAlchemy objects.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from meeting_prep.agent.api_client import ActionOutcome, OutcomeStatus
from meeting_prep.agent.model import Message, Role, ToolCall
from meeting_prep.agent.proposals import (
    Action,
    Approval,
    Proposal,
    ProposalStatus,
    actions_from_json,
    proposal_hash,
)
from meeting_prep.db.tables.agent import (
    AgentRun,
    ApprovalRow,
    Conversation,
    ConversationMessage,
    OutcomeRow,
    ProposalRow,
)


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    time_zone: str
    created_at: datetime


def new_id() -> str:
    return uuid.uuid4().hex


class AgentStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _session(self) -> Session:
        # Rows are read after their transaction commits, so do not expire them.
        return Session(self.engine, expire_on_commit=False)

    # --- Conversations and messages ---

    def create_conversation(self, user: str, time_zone: str, now: datetime) -> ConversationRecord:
        row = Conversation(
            id=new_id(), user_id=user, time_zone=time_zone, created_at=now, updated_at=now
        )
        with self._session() as session, session.begin():
            session.add(row)
        return ConversationRecord(row.id, time_zone, now)

    def get_conversation(self, user: str, conversation_id: str) -> ConversationRecord | None:
        with self._session() as session:
            row = session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id, Conversation.user_id == user
                )
            )
            if row is None:
                return None
            return ConversationRecord(row.id, row.time_zone, _utc(row.created_at))

    def messages(self, user: str, conversation_id: str) -> list[Message]:
        with self._session() as session:
            rows = session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.user_id == user,
                )
                .order_by(ConversationMessage.position)
            )
            return [_message(row) for row in rows]

    def append_messages(
        self, user: str, conversation_id: str, messages: Sequence[Message], now: datetime
    ) -> None:
        with self._session() as session, session.begin():
            last = session.scalar(
                select(func.max(ConversationMessage.position)).where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.user_id == user,
                )
            )
            start = -1 if last is None else last
            for offset, message in enumerate(messages, start=1):
                session.add(
                    ConversationMessage(
                        conversation_id=conversation_id,
                        user_id=user,
                        position=start + offset,
                        role=message.role,
                        content=message.content,
                        tool_calls=[
                            {"id": c.id, "name": c.name, "arguments": c.arguments}
                            for c in message.tool_calls
                        ]
                        or None,
                        tool_call_id=message.tool_call_id,
                        created_at=now,
                    )
                )
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id, Conversation.user_id == user)
                .values(updated_at=now)
            )

    def user_message_times(self, user: str, since: datetime) -> list[datetime]:
        """When this user's messages since ``since`` were saved, for the rate limit."""
        with self._session() as session:
            times = session.scalars(
                select(ConversationMessage.created_at).where(
                    ConversationMessage.user_id == user,
                    ConversationMessage.role == "user",
                    ConversationMessage.created_at >= since,
                )
            )
            return [_utc(moment) for moment in times]

    # --- Runs ---

    def token_usage_since(self, since: datetime) -> list[tuple[datetime, int]]:
        """(end time, tokens) of every user's runs since ``since``: the shared budget."""
        with self._session() as session:
            rows = session.execute(
                select(
                    AgentRun.ended_at, AgentRun.prompt_tokens + AgentRun.completion_tokens
                ).where(AgentRun.ended_at >= since)
            )
            return [(_utc(ended), int(tokens)) for ended, tokens in rows]

    def save_run(self, user: str, run: Mapping[str, Any]) -> None:
        with self._session() as session, session.begin():
            session.add(AgentRun(user_id=user, **run))

    def get_run(self, user: str, run_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            row = session.scalar(
                select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user)
            )
            if row is None:
                return None
            columns = AgentRun.__table__.columns.keys()
            return {name: getattr(row, name) for name in columns}

    # --- Proposals, approvals and outcomes ---

    def create_proposal(
        self,
        user: str,
        conversation_id: str,
        run_id: str | None,
        actions: Sequence[Action],
        now: datetime,
    ) -> Proposal:
        """A new pending proposal. A pending one in the same conversation is superseded."""
        with self._session() as session, session.begin():
            pending = session.scalars(
                select(ProposalRow).where(
                    ProposalRow.conversation_id == conversation_id,
                    ProposalRow.user_id == user,
                    ProposalRow.status == "pending",
                )
            ).all()
            for row in pending:
                row.status, row.updated_at = "superseded", now
            row = ProposalRow(
                id=new_id(),
                user_id=user,
                conversation_id=conversation_id,
                run_id=run_id,
                actions=[action.as_json() for action in actions],
                proposal_hash=proposal_hash(user, actions),
                status="pending",
                supersedes=max(pending, key=lambda p: _utc(p.created_at)).id if pending else None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            return _proposal(row)

    def get_proposal(self, user: str, proposal_id: str) -> Proposal | None:
        with self._session() as session:
            row = session.scalar(
                select(ProposalRow).where(
                    ProposalRow.id == proposal_id, ProposalRow.user_id == user
                )
            )
            return None if row is None else _proposal(row)

    def pending_proposal(self, user: str, conversation_id: str) -> Proposal | None:
        with self._session() as session:
            row = session.scalar(
                select(ProposalRow).where(
                    ProposalRow.conversation_id == conversation_id,
                    ProposalRow.user_id == user,
                    ProposalRow.status == "pending",
                )
            )
            return None if row is None else _proposal(row)

    def change_status(
        self,
        user: str,
        proposal_id: str,
        allowed: Sequence[ProposalStatus],
        to: ProposalStatus,
        now: datetime,
    ) -> bool:
        """Move a proposal to ``to`` only from one of ``allowed``. False if it was not."""
        with self._session() as session, session.begin():
            result = session.execute(
                update(ProposalRow)
                .where(
                    ProposalRow.id == proposal_id,
                    ProposalRow.user_id == user,
                    ProposalRow.status.in_(allowed),
                )
                .values(status=to, updated_at=now)
            )
            return cast(int, getattr(result, "rowcount", 0)) == 1

    def approve(self, user: str, proposal: Proposal, now: datetime) -> Approval:
        """Store the approval for this proposal's hash and mark it approved, in one step.

        Returns the stored approval if there is one already.
        """
        with self._session() as session, session.begin():
            existing = session.scalar(
                select(ApprovalRow).where(
                    ApprovalRow.proposal_id == proposal.id, ApprovalRow.user_id == user
                )
            )
            if existing is not None:
                return _approval(existing)
            row = ApprovalRow(
                id=new_id(),
                proposal_id=proposal.id,
                user_id=user,
                proposal_hash=proposal.hash,
                approved_at=now,
            )
            session.add(row)
            session.execute(
                update(ProposalRow)
                .where(
                    ProposalRow.id == proposal.id,
                    ProposalRow.user_id == user,
                    ProposalRow.status == "pending",
                )
                .values(status="approved", updated_at=now)
            )
            return _approval(row)

    def approval_for(self, user: str, proposal_id: str) -> Approval | None:
        with self._session() as session:
            row = session.scalar(
                select(ApprovalRow).where(
                    ApprovalRow.proposal_id == proposal_id, ApprovalRow.user_id == user
                )
            )
            return None if row is None else _approval(row)

    def record_outcomes(
        self, user: str, proposal_id: str, outcomes: Sequence[ActionOutcome], now: datetime
    ) -> None:
        """Store every action's outcome and mark the proposal executed, in one transaction."""
        with self._session() as session, session.begin():
            for outcome in outcomes:
                session.add(
                    OutcomeRow(
                        proposal_id=proposal_id,
                        user_id=user,
                        action_index=outcome.index,
                        kind=outcome.kind,
                        status=outcome.status,
                        detail=dict(outcome.detail),
                        recorded_at=now,
                    )
                )
            session.execute(
                update(ProposalRow)
                .where(ProposalRow.id == proposal_id, ProposalRow.user_id == user)
                .values(status="executed", updated_at=now)
            )

    def outcomes(self, user: str, proposal_id: str) -> list[ActionOutcome]:
        with self._session() as session:
            rows = session.scalars(
                select(OutcomeRow)
                .where(OutcomeRow.proposal_id == proposal_id, OutcomeRow.user_id == user)
                .order_by(OutcomeRow.action_index)
            )
            return [
                ActionOutcome(
                    row.action_index, row.kind, cast(OutcomeStatus, row.status), row.detail
                )
                for row in rows
            ]


def _utc(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; every time we store is UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _message(row: ConversationMessage) -> Message:
    calls = tuple(ToolCall(c["id"], c["name"], c["arguments"]) for c in row.tool_calls or [])
    return Message(cast(Role, row.role), row.content, calls, row.tool_call_id)


def _proposal(row: ProposalRow) -> Proposal:
    return Proposal(
        id=row.id,
        user_id=row.user_id,
        conversation_id=row.conversation_id,
        actions=actions_from_json(row.actions),
        hash=row.proposal_hash,
        status=cast(ProposalStatus, row.status),
        created_at=_utc(row.created_at),
        supersedes=row.supersedes,
        run_id=row.run_id,
    )


def _approval(row: ApprovalRow) -> Approval:
    return Approval(row.id, row.proposal_id, row.proposal_hash, row.user_id, _utc(row.approved_at))
