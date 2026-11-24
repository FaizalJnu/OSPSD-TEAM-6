"""The agent service's tables: conversations, messages, proposals, approvals, outcomes, runs.

Owner: Vikram. Every row carries the user ID it belongs to, and every query in
``meeting_prep.db.agent_store`` filters by it, so one user's IDs never reach another
user's rows.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from meeting_prep.db.base import Base

ID = String(32)  # uuid4().hex
USER_ID = String(64)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(USER_ID, index=True)
    # The user's IANA time zone, for the current date the model is told on each run.
    time_zone: Mapped[str] = mapped_column(String(64), server_default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationMessage(Base):
    """One message, in order. ``tool_calls`` holds an assistant message's tool calls."""

    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[str] = mapped_column(USER_ID, index=True)
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    tool_call_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    """The execution record of one loop run (remaining-work.md, D: execution records)."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(USER_ID, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stop_reason: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(String(256))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    model_calls: Mapped[int] = mapped_column(Integer)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    policy_decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class ProposalRow(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(USER_ID, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ID)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    supersedes: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    """At most one approval per proposal, for that proposal's hash and user."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    user_id: Mapped[str] = mapped_column(USER_ID, index=True)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutcomeRow(Base):
    """What happened to one action of an executed proposal."""

    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("proposal_id", "action_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    user_id: Mapped[str] = mapped_column(USER_ID, index=True)
    action_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
