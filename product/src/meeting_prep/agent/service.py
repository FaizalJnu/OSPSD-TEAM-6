"""The agent service's rules: conversations, runs, proposals, approvals and execution.

No web framework here; ``app.py`` maps each ``AgentError`` code to a status. Every
call takes the acting user, which comes only from the signed-in session.

Execution goes only through ``ApiClient.execute``, and only with a stored approval
that matches the proposal's ID, hash and user (``approval_matches``), checked again
right before every execute call, retries included. An executed proposal is never
executed again: approving it again returns the stored outcomes.
"""

import asyncio
import json
import time
import weakref
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from meeting_prep.agent.api_client import ActionOutcome, ApiClient, ApiError
from meeting_prep.agent.budget import (
    DAY,
    BudgetLimits,
    MessageLimits,
    TokenBudget,
    message_retry_after,
)
from meeting_prep.agent.loop import AgentResult, Limits, StepRecord, run
from meeting_prep.agent.model import Message, ModelClient
from meeting_prep.agent.proposals import Action, Proposal, approval_matches
from meeting_prep.agent.tools_meeting import meeting_tools
from meeting_prep.db.agent_store import AgentStore, ConversationRecord, new_id

DEFAULT_LIMITS = Limits(max_steps=8, max_seconds=60, max_total_tokens=6_000)
PROMPT_VERSION = "system_v2"
MESSAGE_CHARACTERS = 4_000
# The model sees at most this many conversation messages, the new one included.
HISTORY_MESSAGES = 20


def system_prompt(version: str = PROMPT_VERSION) -> str:
    return files("meeting_prep.agent").joinpath(f"prompts/{version}.md").read_text("utf-8")


def valid_time_zone(name: str) -> str:
    """An IANA time zone name, or AgentError invalid_request."""
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        raise AgentError("invalid_request", "time_zone: not an IANA time zone name") from None
    return name


def current_date_line(now: datetime, time_zone: str) -> str:
    """The date, weekday and time the model is told at the start of every run."""
    local = now.astimezone(ZoneInfo(time_zone))
    offset = local.strftime("%z")
    return (
        f"Current date and time for the user: {local:%A} {local:%Y-%m-%d} {local:%H:%M} "
        f"in {time_zone} (UTC{offset[:3]}:{offset[3:]})."
    )


class AgentError(Exception):
    """A refused or failed request. ``code`` is stable; ``message`` is safe to show."""

    def __init__(self, code: str, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class Reply:
    text: str | None
    stop_reason: str
    run_id: str
    proposal: Proposal | None
    retry_after: float | None


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentService:
    def __init__(
        self,
        store: AgentStore,
        model: ModelClient,
        api: ApiClient,
        *,
        limits: Limits = DEFAULT_LIMITS,
        now: Callable[[], datetime] = utc_now,
        clock: Callable[[], float] = time.monotonic,
        message_limits: MessageLimits | None = None,
        budget: TokenBudget | None = None,
    ) -> None:
        self.store = store
        self.model = model
        self.message_limits = message_limits or MessageLimits()
        self.budget = budget or TokenBudget(BudgetLimits(tokens_per_run=limits.max_total_tokens))
        if self.budget.limits.tokens_per_run > self.budget.limits.tokens_per_minute:
            raise ValueError("a run's token cap must fit in the per-minute token budget")
        self._in_flight: dict[str, int] = {}
        self.api = api
        self.limits = limits
        self.now = now
        self.clock = clock
        self.prompt = system_prompt()
        # One request at a time per conversation and per proposal, in this process.
        # A lock disappears once nothing holds or waits for it.
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    # --- Conversations ---

    def create_conversation(self, user: str, time_zone: str) -> ConversationRecord:
        """A new conversation in the user's IANA time zone, such as America/New_York."""
        return self.store.create_conversation(user, valid_time_zone(time_zone), self.now())

    def conversation(
        self, user: str, conversation_id: str
    ) -> tuple[ConversationRecord, list[Message], Proposal | None]:
        record = self._conversation(user, conversation_id)
        messages = self.store.messages(user, conversation_id)
        return record, messages, self.store.pending_proposal(user, conversation_id)

    async def send_message(self, user: str, conversation_id: str, text: str) -> Reply:
        """Run the loop on the conversation plus ``text``, and save both and the run."""
        conversation = self._conversation(user, conversation_id)
        run_id = new_id()
        await self._admit(user, run_id)
        try:
            return await self._send(user, conversation_id, conversation.time_zone, text, run_id)
        finally:
            self.budget.release(run_id)
            self._in_flight[user] -= 1
            if not self._in_flight[user]:
                del self._in_flight[user]

    async def _admit(self, user: str, run_id: str) -> None:
        """The user's message limit, then the shared token budget. Neither calls the model."""
        async with self._lock(f"user:{user}"):
            now = self.now()
            sent = self.store.user_message_times(user, now - DAY)
            wait = message_retry_after(now, sent, self._in_flight.get(user, 0), self.message_limits)
            if wait is not None:
                raise AgentError(
                    "rate_limited", "too many messages; try again later", retry_after=wait
                )
            wait = self.budget.retry_after(now, self.store.token_usage_since(now - DAY))
            if wait is not None:
                raise AgentError(
                    "busy", "the assistant is busy for everyone; try again later", retry_after=wait
                )
            self.budget.reserve(run_id)
            self._in_flight[user] = self._in_flight.get(user, 0) + 1

    async def _send(
        self, user: str, conversation_id: str, time_zone: str, text: str, run_id: str
    ) -> Reply:
        async with self._lock(f"conversation:{conversation_id}"):
            history = _recent(self.store.messages(user, conversation_id), HISTORY_MESSAGES - 1)
            said = Message("user", text)
            started_at = self.now()
            made: list[Proposal] = []

            def propose(actions: tuple[Action, ...]) -> Proposal:
                proposal = self.store.create_proposal(
                    user, conversation_id, run_id, actions, self.now()
                )
                made.append(proposal)
                return proposal

            today = current_date_line(self.now(), time_zone)
            prompt = [Message("system", self.prompt), Message("system", today), *history, said]
            registry = meeting_tools(self.api, user, propose, self.now)
            result = await run(prompt, self.model, registry, self.limits, clock=self.clock)

            self.budget.observe(self.now(), result.rate_limit)
            if result.stop_reason == "rate_limited":
                self.budget.block(self.now(), result.retry_after)
            added = _answer_open_tool_calls(list(result.messages[len(prompt) :]))
            self.store.append_messages(user, conversation_id, [said, *added], self.now())
            self.store.save_run(
                user, _run_row(run_id, conversation_id, started_at, self.now(), result, made)
            )
            return Reply(
                result.final_text,
                result.stop_reason,
                run_id,
                self.store.pending_proposal(user, conversation_id),
                result.retry_after,
            )

    # --- Proposals ---

    def proposal(self, user: str, proposal_id: str) -> tuple[Proposal, list[ActionOutcome]]:
        proposal = self._proposal(user, proposal_id)
        return proposal, self.store.outcomes(user, proposal_id)

    async def approve(
        self, user: str, proposal_id: str, proposal_hash: str
    ) -> tuple[Proposal, list[ActionOutcome]]:
        """Approve the exact proposal the person saw, then execute it.

        A hash that is not the proposal's current hash is refused: the person approved
        something else. Approving an executed proposal returns its stored outcomes.
        """
        async with self._lock(f"proposal:{proposal_id}"):
            proposal = self._proposal(user, proposal_id)
            if proposal_hash != proposal.hash:
                raise AgentError(
                    "stale_proposal", "this is not the proposal's current content; review it again"
                )
            if proposal.status == "superseded":
                raise AgentError(
                    "proposal_superseded", "this proposal was replaced; approve the new one"
                )
            if proposal.status == "rejected":
                raise AgentError("proposal_rejected", "this proposal was rejected")
            if proposal.status == "executed":
                return proposal, self.store.outcomes(user, proposal_id)
            self.store.approve(user, proposal, self.now())
            outcomes = await self._execute(user, proposal_id)
            return self._proposal(user, proposal_id), outcomes

    async def execute(self, user: str, proposal_id: str) -> list[ActionOutcome]:
        """Execute an approved proposal; used for a retry after a failed execute call."""
        async with self._lock(f"proposal:{proposal_id}"):
            proposal = self._proposal(user, proposal_id)
            if proposal.status == "executed":
                return self.store.outcomes(user, proposal_id)
            return await self._execute(user, proposal_id)

    def reject(self, user: str, proposal_id: str) -> Proposal:
        proposal = self._proposal(user, proposal_id)
        if proposal.status != "rejected" and not self.store.change_status(
            user, proposal_id, ["pending"], "rejected", self.now()
        ):
            raise AgentError(
                "proposal_not_pending", f"a proposal that is {proposal.status} cannot be rejected"
            )
        return self._proposal(user, proposal_id)

    async def _execute(self, user: str, proposal_id: str) -> list[ActionOutcome]:
        # Read both again: the check runs against what is stored, on every path.
        proposal = self._proposal(user, proposal_id)
        approval = self.store.approval_for(user, proposal_id)
        if proposal.status != "approved" or approval is None:
            raise AgentError("approval_required", "this proposal has not been approved")
        if not approval_matches(approval, proposal, user):
            raise AgentError("approval_required", "the approval does not match this proposal")
        try:
            outcomes = await self.api.execute(user, proposal, approval)
        except ApiError as error:
            # The proposal stays approved, so approving it again retries the execute call.
            # The review-meeting workflow is idempotent, so a retry never duplicates.
            detail = " It may have been partly applied." if error.may_have_applied else ""
            raise AgentError(
                "execution_failed", f"the API service could not execute the proposal.{detail}"
            ) from None
        outcomes = _one_per_action(proposal, outcomes)
        self.store.record_outcomes(user, proposal_id, outcomes, self.now())
        return outcomes

    def _conversation(self, user: str, conversation_id: str) -> ConversationRecord:
        record = self.store.get_conversation(user, conversation_id)
        if record is None:
            raise AgentError("not_found", "no such conversation")
        return record

    def _proposal(self, user: str, proposal_id: str) -> Proposal:
        proposal = self.store.get_proposal(user, proposal_id)
        if proposal is None:
            raise AgentError("not_found", "no such proposal")
        return proposal

    def lock_count(self) -> int:
        """How many conversations and proposals have a request holding or waiting for a lock."""
        return len(self._locks)

    @asynccontextmanager
    async def _lock(self, key: str) -> AsyncIterator[None]:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        async with lock:
            yield


def _recent(history: list[Message], count: int) -> list[Message]:
    """The last ``count`` messages, starting at a user message.

    Cutting elsewhere could leave a tool result without the call it answers, which the
    model's API refuses.
    """
    recent = history[-count:] if count > 0 else []
    while recent and recent[0].role != "user":
        recent.pop(0)
    return recent


def _answer_open_tool_calls(messages: list[Message]) -> list[Message]:
    """Answer tool calls the loop stopped before running, so the history stays valid."""
    answered = {m.tool_call_id for m in messages if m.role == "tool"}
    for message in list(messages):
        for call in message.tool_calls:
            if call.id not in answered:
                error = {"code": "not_run", "message": "the run stopped before this tool ran"}
                messages.append(Message("tool", json.dumps({"error": error}), tool_call_id=call.id))
    return messages


def _one_per_action(proposal: Proposal, outcomes: Sequence[ActionOutcome]) -> list[ActionOutcome]:
    """Exactly one outcome per action. One the API did not report is uncertain."""
    reported = {outcome.index: outcome for outcome in outcomes}
    return [
        reported.get(index)
        or ActionOutcome(index, action.kind, "uncertain", {"reason": "not reported"})
        for index, action in enumerate(proposal.actions)
    ]


def _run_row(
    run_id: str,
    conversation_id: str,
    started_at: datetime,
    ended_at: datetime,
    result: AgentResult,
    proposals: Sequence[Proposal],
) -> dict[str, Any]:
    """The execution record: every step, every policy decision, the stop and the totals."""
    return {
        "id": run_id,
        "conversation_id": conversation_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "stop_reason": result.stop_reason,
        "error": result.error,
        "model": result.model,
        "prompt_version": PROMPT_VERSION,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "model_calls": result.model_calls,
        "steps": [_recorded_step(step) for step in result.steps],
        "policy_decisions": [*_decisions(result.steps), *_approvals_required(proposals)],
    }


def _recorded_step(step: StepRecord) -> dict[str, object]:
    result = step.result
    if step.tool == "read_document" and result is not None:
        # A document can hold anything; the record keeps its size, not its text.
        content = result.get("content")
        result = {
            **result,
            "content": f"<{len(content) if isinstance(content, str) else 0} characters>",
        }
    return {
        "tool": step.tool,
        "call_id": step.call_id,
        "arguments": step.arguments,
        "result": result,
        "error": step.error,
        "duration_seconds": step.duration_seconds,
    }


def _decisions(steps: Sequence[StepRecord]) -> Iterator[dict[str, object]]:
    for step in steps:
        code = (step.error or {}).get("code")
        if code == "unknown_tool":
            yield {"decision": "refused_unknown_tool", "tool": step.tool, "call_id": step.call_id}
        elif code == "invalid_arguments":
            problems = (step.error or {}).get("problems", [])
            yield {
                "decision": "rejected_arguments",
                "tool": step.tool,
                "call_id": step.call_id,
                "problems": problems,
            }


def _approvals_required(proposals: Sequence[Proposal]) -> Iterator[dict[str, object]]:
    for proposal in proposals:
        yield {
            "decision": "approval_required",
            "proposal_id": proposal.id,
            "proposal_hash": proposal.hash,
            "superseded": proposal.supersedes,
        }
