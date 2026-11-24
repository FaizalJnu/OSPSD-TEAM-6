"""GroqModel over a stubbed SDK client: requests, responses, 429s and errors. No network.

The one live call is marked ``provider`` and stays out of the fast suite:

    uv run --env-file .env pytest -m provider tests/test_agent_model.py
"""

import asyncio
import os
from typing import Any, cast

import groq
import httpx
import pytest
from groq.types.chat import ChatCompletion

from meeting_prep.agent.model import (
    DEFAULT_MODEL,
    GroqModel,
    Message,
    ModelError,
    ModelRateLimited,
    RateLimit,
    ToolCall,
    ToolSpec,
)
from meeting_prep.config import ConfigError

URL = "https://api.groq.com/openai/v1/chat/completions"
LOOKUP = ToolSpec(
    "lookup",
    "Look up an issue.",
    {"type": "object", "properties": {"issue_id": {"type": "string"}}, "required": ["issue_id"]},
)
PROMPT = [Message("system", "secret system prompt"), Message("user", "What is issue 7?")]


def completion(message: dict[str, Any], finish: str = "stop", usage: bool = True) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1_763_000_000,
            "model": "openai/gpt-oss-120b",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49}
            if usage
            else None,
        }
    )


class StubRaw:
    """What ``with_raw_response.create`` returns: the headers, and an async ``parse()``."""

    def __init__(self, completion: ChatCompletion, headers: dict[str, str]) -> None:
        self.headers = httpx.Headers(headers)
        self.completion = completion

    async def parse(self) -> ChatCompletion:  # async, as in the SDK's AsyncAPIResponse
        return self.completion


class StubCompletions:
    def __init__(self, outcome: ChatCompletion | Exception, headers: dict[str, str]) -> None:
        self.outcome = outcome
        self.headers = headers
        self.requests: list[dict[str, Any]] = []
        self.with_raw_response = self

    async def create(self, **request: Any) -> StubRaw:
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return StubRaw(self.outcome, self.headers)


class StubClient:
    def __init__(self, outcome: ChatCompletion | Exception, headers: dict[str, str]) -> None:
        self.completions = StubCompletions(outcome, headers)
        self.chat = self


def model_over(
    outcome: ChatCompletion | Exception, headers: dict[str, str] | None = None
) -> tuple[GroqModel, StubCompletions]:
    stub = StubClient(outcome, headers or {})
    return GroqModel("openai/gpt-oss-120b", cast(Any, stub)), stub.completions


def complete(model: GroqModel, tools: list[ToolSpec] | None = None) -> Any:
    return asyncio.run(model.complete(PROMPT, tools or [], 500))


def status_error(
    cls: type[groq.APIStatusError], status: int, **headers: str
) -> groq.APIStatusError:
    response = httpx.Response(status, headers=headers, request=httpx.Request("POST", URL))
    return cls("secret system prompt echoed", response=response, body=None)


def test_a_text_answer_is_mapped_with_usage_model_and_finish_reason():
    model, stub = model_over(completion({"role": "assistant", "content": "Issue 7 is Fix login."}))

    response = complete(model)

    assert response.text == "Issue 7 is Fix login."
    assert response.tool_calls == ()
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (42, 7)
    assert (response.model, response.finish_reason) == ("openai/gpt-oss-120b", "stop")
    (request,) = stub.requests
    assert request["model"] == "openai/gpt-oss-120b"
    assert request["max_completion_tokens"] == 500
    assert "tools" not in request  # no tools, no tools field
    assert request["messages"] == [
        {"role": "system", "content": "secret system prompt"},
        {"role": "user", "content": "What is issue 7?"},
    ]


def test_tool_calls_and_the_tools_sent_are_mapped():
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "lookup", "arguments": '{"issue_id": "7"}'},
    }
    reply = completion(
        {"role": "assistant", "content": None, "tool_calls": [tool_call]}, "tool_calls"
    )
    model, stub = model_over(reply)

    response = complete(model, [LOOKUP])

    assert response.text is None
    assert response.tool_calls == (ToolCall("call_1", "lookup", '{"issue_id": "7"}'),)
    assert response.finish_reason == "tool_calls"
    assert stub.requests[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up an issue.",
                "parameters": LOOKUP.parameters,
            },
        }
    ]


def test_an_earlier_tool_call_and_its_result_are_sent_back_in_the_sdk_shape():
    model, stub = model_over(completion({"role": "assistant", "content": "Done."}))
    history = [
        *PROMPT,
        Message("assistant", None, (ToolCall("call_1", "lookup", "{}"),)),
        Message("tool", '{"result": {}}', tool_call_id="call_1"),
    ]

    asyncio.run(model.complete(history, [LOOKUP], 100))

    assert stub.requests[0]["messages"][2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"result": {}}'},
    ]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (
            {"x-ratelimit-remaining-tokens": "3512", "x-ratelimit-reset-tokens": "7.66s"},
            RateLimit(3512, 7.66),
        ),
        (
            {"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "2m59.5s"},
            RateLimit(0, 179.5),
        ),
        (
            {"x-ratelimit-remaining-tokens": "10", "x-ratelimit-reset-tokens": "120ms"},
            RateLimit(10, 0.12),
        ),
        ({"x-ratelimit-remaining-tokens": "10", "x-ratelimit-reset-tokens": "soon"}, None),
        ({"x-ratelimit-remaining-tokens": "-1", "x-ratelimit-reset-tokens": "1s"}, None),
        ({}, None),
    ],
)
def test_groqs_token_count_is_read_from_the_response_headers(headers, expected):
    model, _ = model_over(completion({"role": "assistant", "content": "ok"}), headers)

    rate_limit = complete(model).rate_limit

    if expected is None:
        assert rate_limit is None
    else:
        assert rate_limit.remaining_tokens == expected.remaining_tokens
        assert rate_limit.reset_seconds == pytest.approx(expected.reset_seconds)


def test_missing_usage_counts_as_zero():
    model, _ = model_over(completion({"role": "assistant", "content": "ok"}, usage=False))

    assert complete(model).usage.total_tokens == 0


@pytest.mark.parametrize(
    ("headers", "retry_after"),
    [
        ({"retry-after": "7"}, 7.0),
        ({"retry-after": "2.5"}, 2.5),
        ({}, None),
        ({"retry-after": "soon"}, None),
    ],
)
def test_a_429_is_rate_limited_with_retry_after(headers, retry_after):
    model, _ = model_over(status_error(groq.RateLimitError, 429, **headers))

    with pytest.raises(ModelRateLimited) as caught:
        complete(model)

    assert caught.value.retry_after == retry_after
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (status_error(groq.InternalServerError, 500), "(InternalServerError, 500)"),
        (status_error(groq.AuthenticationError, 401), "(AuthenticationError, 401)"),
        (status_error(groq.BadRequestError, 400), "(BadRequestError, 400)"),
        (groq.APIConnectionError(request=httpx.Request("POST", URL)), "(APIConnectionError)"),
        (groq.APITimeoutError(request=httpx.Request("POST", URL)), "(APITimeoutError)"),
        (ValueError("secret system prompt"), "(ValueError)"),
    ],
)
def test_any_other_failure_is_a_model_error_that_names_only_its_type(error, expected):
    model, _ = model_over(error)

    with pytest.raises(ModelError) as caught:
        complete(model)

    assert not isinstance(caught.value, ModelRateLimited)
    assert str(caught.value) == f"the model request failed {expected}"
    assert caught.value.__cause__ is None


def test_settings_come_from_the_environment():
    model = GroqModel.from_env({"GROQ_API_KEY": "gsk-not-a-real-key", "AGENT_MODEL": "  "})

    assert model.model == DEFAULT_MODEL == "openai/gpt-oss-120b"
    assert model.client.max_retries == 0  # a 429 comes straight back to the loop
    assert "gsk-not-a-real-key" not in repr(model)
    assert GroqModel.from_env({"GROQ_API_KEY": "k", "AGENT_MODEL": "llama-x"}).model == "llama-x"


def test_a_missing_key_names_the_variable():
    with pytest.raises(ConfigError, match="^GROQ_API_KEY is not set$"):
        GroqModel.from_env({"AGENT_MODEL": DEFAULT_MODEL})


@pytest.mark.provider
def test_one_live_call_to_groq():
    if not os.environ.get("GROQ_API_KEY"):
        pytest.fail("set GROQ_API_KEY (uv run --env-file .env ...) to run the provider tests")
    model = GroqModel.from_env()
    prompt = [
        Message("system", "Use the lookup tool when asked about an issue."),
        Message("user", "Look up issue 7."),
    ]

    response = asyncio.run(model.complete(prompt, [LOOKUP], 300))

    assert response.tool_calls or response.text
    assert response.usage.prompt_tokens > 0
    assert response.model == model.model
