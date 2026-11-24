"""The agent loop: ask the model, run the tools it calls, stop on an answer or a limit.

Each turn the loop checks, in order, the cancel token, the wall-time limit and the
token budget, then calls the model with the remaining budget as ``max_tokens`` and a
timeout of the remaining time. Text is the final answer. Tool calls run in the order
the model returned them; each is one step, checked against the cancel token and
``max_steps`` first.

An unknown tool, invalid arguments, or a handler's error is not a stop: the model gets
a structured error as the tool's result, and the step counts. The loop stops with one
of the ``StopReason`` values and returns everything it did as an ``AgentResult``.
Nothing here logs the prompt.
"""

import asyncio
import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from meeting_prep.agent.model import (
    Message,
    ModelClient,
    ModelError,
    ModelRateLimited,
    ToolCall,
)
from meeting_prep.agent.tools import InvalidArguments, ToolError, ToolRegistry, result_json

StopReason = Literal[
    "completed",
    "max_steps",
    "timeout",
    "token_limit",
    "cancelled",
    "rate_limited",
    "model_error",
]

Clock = Callable[[], float]


@dataclass(frozen=True)
class Limits:
    """``max_seconds`` is wall time for the whole run, model and tool calls included."""

    max_steps: int = 8
    max_seconds: float = 60.0
    max_total_tokens: int = 20_000

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_seconds <= 0 or self.max_total_tokens < 1:
            raise ValueError("every limit must be positive")


class CancelToken:
    """Set from any thread or task; the loop checks it before every model and tool call."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class StepRecord:
    """One tool call: validated arguments (None if invalid), and a result or an error.

    Arguments come from the tool's argument model, so secret fields stay masked, and
    invalid arguments are never stored.
    """

    tool: str
    call_id: str
    arguments: dict[str, object] | None
    result: dict[str, object] | None
    error: dict[str, object] | None
    duration_seconds: float


@dataclass(frozen=True)
class AgentResult:
    stop_reason: StopReason
    final_text: str | None
    steps: tuple[StepRecord, ...]
    prompt_tokens: int
    completion_tokens: int
    model: str | None
    model_calls: int
    duration_seconds: float
    retry_after: float | None = None
    # Why a model_error or rate_limited run stopped. It names the failure's type only.
    error: str | None = None
    # The conversation as the loop left it, to continue or save. Kept out of repr.
    messages: tuple[Message, ...] = field(default=(), repr=False)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


async def run(
    messages: Sequence[Message],
    model: ModelClient,
    registry: ToolRegistry,
    limits: Limits,
    cancel: CancelToken | None = None,
    clock: Clock = time.monotonic,
) -> AgentResult:
    """Run the loop until the model answers or something stops it."""
    state = _Run(messages, model, registry, limits, cancel or CancelToken(), clock)
    try:
        return await state.loop()
    except asyncio.CancelledError:
        # The task running the loop was cancelled: report it like the cancel token. The
        # cancellation is consumed, so the caller receives this result.
        task = asyncio.current_task()
        if task is not None:
            task.uncancel()
        return state.result("cancelled")


class _Run:
    def __init__(
        self,
        messages: Sequence[Message],
        model: ModelClient,
        registry: ToolRegistry,
        limits: Limits,
        cancel: CancelToken,
        clock: Clock,
    ) -> None:
        self.messages = list(messages)
        self.model = model
        self.registry = registry
        self.limits = limits
        self.cancel = cancel
        self.clock = clock
        self.started = clock()
        self.steps: list[StepRecord] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.model_id: str | None = None
        self.model_calls = 0
        self.retry_after: float | None = None
        self.error: str | None = None

    async def loop(self) -> AgentResult:
        tools = self.registry.specs()
        while True:
            if self.cancel.cancelled:
                return self.result("cancelled")
            time_left = self._time_left()
            if time_left <= 0:
                return self.result("timeout")
            budget = self.limits.max_total_tokens - self.prompt_tokens - self.completion_tokens
            if budget <= 0:
                return self.result("token_limit")
            try:
                async with asyncio.timeout(time_left):
                    response = await self.model.complete(self.messages, tools, budget)
            except TimeoutError:
                return self.result("timeout")
            except ModelRateLimited as error:
                self.retry_after, self.error = error.retry_after, str(error)
                return self.result("rate_limited")
            except ModelError as error:
                self.error = str(error)
                return self.result("model_error")

            self.model_calls += 1
            self.model_id = response.model
            self.prompt_tokens += response.usage.prompt_tokens
            self.completion_tokens += response.usage.completion_tokens
            if response.finish_reason == "length":
                return self.result("token_limit")  # the reply was cut off at the budget
            self.messages.append(Message("assistant", response.text, response.tool_calls))
            if not response.tool_calls:
                return self.result("completed", final_text=response.text or "")

            for call in response.tool_calls:
                if self.cancel.cancelled:
                    return self.result("cancelled")
                if len(self.steps) >= self.limits.max_steps:
                    return self.result("max_steps")
                if not await self._run_tool(call):
                    return self.result("timeout")

    async def _run_tool(self, call: ToolCall) -> bool:
        """Run one tool call and append its result. False if the time limit ran out."""
        started = self.clock()
        arguments: BaseModel | None = None
        result: dict[str, object] | None = None
        error: dict[str, object] | None = None
        deadline: asyncio.Timeout | None = None
        try:
            tool, arguments = self.registry.validate(call.name, call.arguments)
            time_left = self._time_left()
            if time_left <= 0:
                return False
            deadline = asyncio.timeout(time_left)
            async with deadline:
                result = result_json(await tool.handler(arguments))
        except TimeoutError:
            if deadline is None or not deadline.expired():
                error = _error("tool_failed", "the tool failed (TimeoutError)")  # its own timeout
            else:
                ran_out = _error("timeout", "the tool ran out of time")
                self._record(call, arguments, None, ran_out, started)
                return False
        except InvalidArguments as problem:
            error = _error(problem.code, problem.message)
            if problem.problems:
                error["problems"] = problem.problems
        except ToolError as problem:
            error = _error(problem.code, problem.message)
        except Exception as problem:
            # Only the type: a handler's message could hold anything.
            error = _error("tool_failed", f"the tool failed ({type(problem).__name__})")
        self._record(call, arguments, result, error, started)
        content = {"result": result} if error is None else {"error": error}
        self.messages.append(Message("tool", json.dumps(content), tool_call_id=call.id))
        return True

    def _record(
        self,
        call: ToolCall,
        arguments: BaseModel | None,
        result: dict[str, object] | None,
        error: dict[str, object] | None,
        started: float,
    ) -> None:
        dumped = None if arguments is None else arguments.model_dump(mode="json")
        duration = self.clock() - started
        self.steps.append(StepRecord(call.name, call.id, dumped, result, error, duration))

    def _time_left(self) -> float:
        return self.limits.max_seconds - (self.clock() - self.started)

    def result(self, stop_reason: StopReason, final_text: str | None = None) -> AgentResult:
        return AgentResult(
            stop_reason=stop_reason,
            final_text=final_text,
            steps=tuple(self.steps),
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            model=self.model_id,
            model_calls=self.model_calls,
            duration_seconds=self.clock() - self.started,
            retry_after=self.retry_after,
            error=self.error,
            messages=tuple(self.messages),
        )


def _error(code: str, message: str) -> dict[str, object]:
    return {"code": code, "message": message}
