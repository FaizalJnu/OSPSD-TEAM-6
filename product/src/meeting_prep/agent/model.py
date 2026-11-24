"""The model interface the loop calls, a real Groq client, and a scripted one for tests.

``ModelClient.complete`` takes the conversation, the tools' specs and a token cap, and
returns text or tool calls with the tokens used, the model ID and the finish reason.
A failure is ``ModelError``; a rate limit is ``ModelRateLimited``, with the seconds the
provider asks us to wait when it says.

``GroqModel`` is the only code that imports the Groq SDK. It never logs the API key or
the prompt, and its errors name only the failure's type and status.
"""

import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import groq

from meeting_prep.config import ConfigError

DEFAULT_MODEL = "openai/gpt-oss-120b"

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model asked for. ``arguments`` is the model's raw JSON text."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Message:
    """One message of the conversation, in the chat-completions shape.

    An assistant message may carry tool calls; a tool message answers one of them by
    ``tool_call_id``.
    """

    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    """What the model is told about a tool: its name, description and argument schema."""

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class RateLimit:
    """The provider's own count after a call: tokens left this minute, and when it resets."""

    remaining_tokens: int
    reset_seconds: float


@dataclass(frozen=True)
class ModelResponse:
    """Text, or tool calls (a response with tool calls is not an answer yet)."""

    text: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    model: str
    finish_reason: str
    rate_limit: RateLimit | None = None


class ModelError(Exception):
    """The model call failed. The message names the failure's type, never its content."""


class ModelRateLimited(ModelError):
    """The provider refused the call for its rate limit. Retry after ``retry_after`` seconds."""

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ModelClient(Protocol):
    async def complete(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec], max_tokens: int
    ) -> ModelResponse:
        """One model turn. ``max_tokens`` caps the completion."""
        ...


# --- Scripted ---


@dataclass(frozen=True)
class ScriptedCall:
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]
    max_tokens: int


ScriptStep = ModelResponse | Exception | Callable[[ScriptedCall], Awaitable[ModelResponse]]


class ScriptExhausted(AssertionError):
    """The loop asked the scripted model for more turns than the script holds.

    It is not a ModelError on purpose: the loop does not catch it, so the test fails.
    """


class ScriptedModel:
    """Answers with a fixed script, in order, and records every call.

    A script step is a response, an exception to raise (``ModelError``,
    ``ModelRateLimited``...), or an async function of the call, for a step that must
    wait or move a fake clock.
    """

    def __init__(self, script: Sequence[ScriptStep], model: str = "scripted") -> None:
        self.script = list(script)
        self.model = model
        self.calls: list[ScriptedCall] = []

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec], max_tokens: int
    ) -> ModelResponse:
        call = ScriptedCall(tuple(messages), tuple(tools), max_tokens)
        self.calls.append(call)
        if len(self.calls) > len(self.script):
            raise ScriptExhausted(
                f"the script has {len(self.script)} responses, and call {len(self.calls)} was made"
            )
        step = self.script[len(self.calls) - 1]
        if isinstance(step, Exception):
            raise step
        if isinstance(step, ModelResponse):
            return step
        return await step(call)

    @staticmethod
    def answer(text: str, *, prompt: int = 10, completion: int = 5) -> ModelResponse:
        return ModelResponse(text, (), Usage(prompt, completion), "scripted", "stop")

    @staticmethod
    def call(
        name: str, arguments: str, *, id: str = "call-1", prompt: int = 10, completion: int = 5
    ) -> ModelResponse:
        return ModelResponse(
            None,
            (ToolCall(id, name, arguments),),
            Usage(prompt, completion),
            "scripted",
            "tool_calls",
        )


# --- Groq ---


@dataclass
class GroqModel:
    """The real model through the Groq SDK. Settings: GROQ_API_KEY, AGENT_MODEL.

    The SDK's own retries are off (``max_retries=0``): a 429 goes straight back to the
    loop as ``ModelRateLimited``, and the loop's limits bound every call.
    """

    model: str
    client: groq.AsyncGroq = field(repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> GroqModel:
        """Raises ConfigError naming GROQ_API_KEY, never its value, when it is not set."""
        key = env.get("GROQ_API_KEY", "").strip()
        if not key:
            raise ConfigError("GROQ_API_KEY is not set")
        model = env.get("AGENT_MODEL", "").strip() or DEFAULT_MODEL
        return cls(model=model, client=groq.AsyncGroq(api_key=key, max_retries=0))

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec], max_tokens: int
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [_groq_message(message) for message in messages],
            "max_completion_tokens": max_tokens,
        }
        if tools:
            request["tools"] = [_groq_tool(tool) for tool in tools]
        try:
            raw = await self.client.chat.completions.with_raw_response.create(**request)
            return _response(await raw.parse(), _rate_limit(raw.headers))
        except groq.RateLimitError as error:
            raise ModelRateLimited(
                "the model provider's rate limit was reached", _retry_after(error)
            ) from None
        except groq.APIStatusError as error:
            raise ModelError(
                f"the model request failed ({type(error).__name__}, {error.status_code})"
            ) from None
        except Exception as error:
            raise ModelError(f"the model request failed ({type(error).__name__})") from None


def _groq_message(message: Message) -> dict[str, object]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    converted: dict[str, object] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        converted["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    return converted


def _groq_tool(tool: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _rate_limit(headers: Mapping[str, str]) -> RateLimit | None:
    """Groq's x-ratelimit-remaining-tokens and x-ratelimit-reset-tokens, when both parse."""
    remaining = headers.get("x-ratelimit-remaining-tokens")
    reset = _duration_seconds(headers.get("x-ratelimit-reset-tokens"))
    if remaining is None or reset is None or not remaining.isdigit():
        return None
    return RateLimit(int(remaining), reset)


_DURATION = re.compile(
    r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?"
)


def _duration_seconds(text: str | None) -> float | None:
    """Seconds from a Groq duration such as "7.66s", "2m59.56s", "1h2m" or "120ms"."""
    if not text:
        return None
    match = _DURATION.fullmatch(text.strip())
    if match is None or not any(match.groups()):
        return None
    hours, minutes, seconds, millis = (float(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _response(completion: Any, rate_limit: RateLimit | None = None) -> ModelResponse:
    choice = completion.choices[0]
    calls = tuple(
        ToolCall(call.id, call.function.name, call.function.arguments)
        for call in choice.message.tool_calls or ()
    )
    usage = completion.usage
    return ModelResponse(
        text=choice.message.content,
        tool_calls=calls,
        usage=Usage(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        ),
        model=completion.model,
        finish_reason=choice.finish_reason or "",
        rate_limit=rate_limit,
    )


def _retry_after(error: groq.RateLimitError) -> float | None:
    """Seconds from the Retry-After header, when it is a number."""
    value = error.response.headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None
