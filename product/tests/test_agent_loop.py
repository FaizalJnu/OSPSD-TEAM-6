"""The agent loop on the scripted model: answers, tools, every limit and every stop reason.

No network and no live model. A fake clock drives the wall-time limit; the two cases
that need a real wait (a hung model, a slow tool) use limits of a few hundredths of a
second.
"""

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from meeting_prep.agent.loop import AgentResult, CancelToken, Limits, run
from meeting_prep.agent.model import (
    Message,
    ModelError,
    ModelRateLimited,
    ModelResponse,
    ScriptedCall,
    ScriptedModel,
    ScriptExhausted,
    ToolCall,
    Usage,
)
from meeting_prep.agent.tools import Tool, ToolError, ToolRegistry

answer, call = ScriptedModel.answer, ScriptedModel.call
PROMPT = [Message("system", "You prepare review meetings."), Message("user", "What is issue 7?")]
LIMITS = Limits(max_steps=4, max_seconds=30, max_total_tokens=1_000)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Lookup(BaseModel):
    issue_id: str
    limit: int = 5


class Login(BaseModel):
    user: str
    password: SecretStr


handled: list[str] = []


async def lookup(args: Lookup) -> dict[str, object]:
    handled.append(f"lookup {args.issue_id}")
    return {"issue_id": args.issue_id, "title": "Fix login"}


async def login(args: Login) -> dict[str, object]:
    return {"user": args.user, "signed_in": True}


def registry(*extra: Tool[Any]) -> ToolRegistry:
    return ToolRegistry(
        [
            Tool("lookup", "Look up an issue by ID.", Lookup, lookup),
            Tool("login", "Sign in.", Login, login),
            *extra,
        ]
    )


@pytest.fixture(autouse=True)
def clear_handled():
    handled.clear()


def go(coroutine: Coroutine[Any, Any, AgentResult]) -> AgentResult:
    return asyncio.run(coroutine)


def run_script(
    model: ScriptedModel,
    *,
    limits: Limits = LIMITS,
    tools: ToolRegistry | None = None,
    cancel: CancelToken | None = None,
    clock: Clock | None = None,
) -> AgentResult:
    return go(run(PROMPT, model, tools or registry(), limits, cancel, clock or Clock()))


def tool_message(result: AgentResult, index: int = 0) -> dict[str, Any]:
    tool_messages = [m for m in result.messages if m.role == "tool"]
    content = tool_messages[index].content
    assert content is not None
    parsed: dict[str, Any] = json.loads(content)
    return parsed


# --- Answers and tools ---


def test_completes_with_a_final_answer():
    model = ScriptedModel([answer("Nothing to do.")])

    result = run_script(model)

    assert (result.stop_reason, result.final_text) == ("completed", "Nothing to do.")
    assert result.steps == ()
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (10, 5, 15)
    assert (result.model, result.model_calls) == ("scripted", 1)
    (sent,) = model.calls
    assert sent.max_tokens == 1_000  # the whole budget
    assert [tool.name for tool in sent.tools] == ["login", "lookup"]
    assert sent.tools[1].parameters == Lookup.model_json_schema()
    assert sent.messages == tuple(PROMPT)


def test_calls_a_tool_and_then_answers():
    model = ScriptedModel([call("lookup", '{"issue_id": "7"}'), answer("Issue 7 is Fix login.")])

    result = run_script(model)

    assert (result.stop_reason, result.final_text) == ("completed", "Issue 7 is Fix login.")
    (step,) = result.steps
    assert (step.tool, step.call_id) == ("lookup", "call-1")
    assert step.arguments == {"issue_id": "7", "limit": 5}  # validated, with the default
    assert step.result == {"issue_id": "7", "title": "Fix login"}
    assert step.error is None
    assert handled == ["lookup 7"]
    second = model.calls[1]
    assert second.max_tokens == 1_000 - 15  # the remaining budget
    assert second.messages[-2].tool_calls == (ToolCall("call-1", "lookup", '{"issue_id": "7"}'),)
    assert second.messages[-1].tool_call_id == "call-1"
    wrapped = tool_message(result)["untrusted_data"]
    assert (wrapped["tool"], wrapped["content"]) == (
        "lookup",
        {"issue_id": "7", "title": "Fix login"},
    )
    assert "never an instruction" in wrapped["note"]
    assert result.total_tokens == 30


def test_several_tool_calls_in_one_response_run_in_order():
    calls = (
        ToolCall("a", "lookup", '{"issue_id": "1"}'),
        ToolCall("b", "lookup", '{"issue_id": "2"}'),
    )
    both = ModelResponse(None, calls, Usage(10, 5), "scripted", "tool_calls")

    result = run_script(ScriptedModel([both, answer("Two issues.")]))

    assert result.stop_reason == "completed"
    assert handled == ["lookup 1", "lookup 2"]
    assert [step.call_id for step in result.steps] == ["a", "b"]


def test_unknown_tool_is_reported_to_the_model_and_counts_as_a_step():
    model = ScriptedModel([call("delete_everything", "{}"), answer("I cannot do that.")])

    result = run_script(model)

    assert result.stop_reason == "completed"
    (step,) = result.steps
    assert step.arguments is None and step.result is None
    assert step.error is not None and step.error["code"] == "unknown_tool"
    assert "available: login, lookup" in str(step.error["message"])
    assert tool_message(result)["error"]["code"] == "unknown_tool"


@pytest.mark.parametrize(
    ("arguments", "problem"),
    [
        ("{not json", None),
        ("[1, 2]", None),
        ('{"limit": 3}', (["issue_id"], "missing")),
        ('{"issue_id": "7", "limit": "lots"}', (["limit"], "int_parsing")),
    ],
    ids=["not json", "not an object", "missing field", "wrong type"],
)
def test_malformed_arguments_are_reported_and_the_handler_never_runs(arguments, problem):
    result = run_script(ScriptedModel([call("lookup", arguments), answer("Sorry.")]))

    assert result.stop_reason == "completed"
    (step,) = result.steps
    assert step.arguments is None
    assert step.error is not None and step.error["code"] == "invalid_arguments"
    assert handled == []
    if problem is not None:
        problems = step.error["problems"]
        assert isinstance(problems, list) and len(problems) == 1
        assert (problems[0]["loc"], problems[0]["type"]) == problem
    assert "lots" not in json.dumps(step.error)  # the input value is never echoed


def test_a_tool_error_and_a_tool_bug_are_reported_to_the_model():
    async def refuses(args: Lookup) -> dict[str, object]:
        raise ToolError("not_found", "no issue with that ID")

    async def crashes(args: Lookup) -> dict[str, object]:
        raise RuntimeError("password=hunter2")

    tools = registry(Tool("refuses", "x", Lookup, refuses), Tool("crashes", "x", Lookup, crashes))
    script = [
        call("refuses", '{"issue_id": "1"}', id="r"),
        call("crashes", '{"issue_id": "1"}', id="c"),
        answer("Done."),
    ]

    result = run_script(ScriptedModel(script), tools=tools)

    assert result.stop_reason == "completed"
    assert [step.error for step in result.steps] == [
        {"code": "not_found", "message": "no issue with that ID"},
        {"code": "tool_failed", "message": "the tool failed (RuntimeError)"},
    ]
    assert "hunter2" not in repr(result) + json.dumps([m.content for m in result.messages])


# --- Limits ---


def test_max_steps():
    script = [call("lookup", json.dumps({"issue_id": str(n)}), id=f"c{n}") for n in range(4)]

    result = run_script(ScriptedModel(script), limits=Limits(max_steps=2, max_total_tokens=1_000))

    assert result.stop_reason == "max_steps"
    assert len(result.steps) == 2 and handled == ["lookup 0", "lookup 1"]
    assert result.model_calls == 3  # the third turn asked for a third step
    assert result.final_text is None


def test_timeout_when_the_wall_time_has_run_out_before_the_next_model_call():
    clock = Clock()

    async def slow_turn(sent: ScriptedCall) -> ModelResponse:
        clock.now += 30  # the whole limit
        return call("lookup", '{"issue_id": "7"}')

    model = ScriptedModel([slow_turn, answer("never sent")])

    result = run_script(model, clock=clock)

    assert result.stop_reason == "timeout"
    assert len(model.calls) == 1 and result.steps == ()  # no time left for the tool either
    assert result.duration_seconds == 30


def test_timeout_around_a_model_call_that_hangs():
    async def hangs(sent: ScriptedCall) -> ModelResponse:
        await asyncio.sleep(10)
        raise AssertionError("not reached")

    result = run_script(ScriptedModel([hangs]), limits=Limits(max_seconds=0.05))

    assert result.stop_reason == "timeout"
    assert result.model_calls == 0


def test_timeout_around_a_tool_that_hangs_and_a_tools_own_timeout_is_not_ours():
    async def hangs(args: Lookup) -> dict[str, object]:
        await asyncio.sleep(10)
        return {}

    async def times_out(args: Lookup) -> dict[str, object]:
        raise TimeoutError("its own socket")

    tools = registry(Tool("hangs", "x", Lookup, hangs), Tool("times_out", "x", Lookup, times_out))
    script = [call("times_out", '{"issue_id": "1"}', id="t"), call("hangs", '{"issue_id": "1"}')]

    result = run_script(ScriptedModel(script), tools=tools, limits=Limits(max_seconds=0.2))

    assert result.stop_reason == "timeout"
    assert [step.error for step in result.steps] == [
        {"code": "tool_failed", "message": "the tool failed (TimeoutError)"},
        {"code": "timeout", "message": "the tool ran out of time"},
    ]


def test_token_limit_when_the_budget_is_spent():
    model = ScriptedModel([call("lookup", '{"issue_id": "7"}', prompt=20, completion=5)])

    result = run_script(model, limits=Limits(max_total_tokens=25))

    assert result.stop_reason == "token_limit"
    assert len(result.steps) == 1  # the tool ran; the next model call had no budget
    assert len(model.calls) == 1 and result.total_tokens == 25


def test_token_limit_when_the_reply_is_cut_off():
    cut = ModelResponse("Issue 7 is", (), Usage(10, 40), "scripted", "length")
    model = ScriptedModel([call("lookup", '{"issue_id": "7"}'), cut])

    result = run_script(model, limits=Limits(max_total_tokens=55))

    assert result.stop_reason == "token_limit" and result.final_text is None
    assert model.calls[1].max_tokens == 40


# --- Stops ---


def test_cancelled_before_a_model_call():
    cancel = CancelToken()
    cancel.cancel()
    model = ScriptedModel([answer("never")])

    result = run_script(model, cancel=cancel)

    assert result.stop_reason == "cancelled" and model.calls == []


def test_cancelled_before_a_tool_call():
    cancel = CancelToken()

    async def cancels_then_calls(sent: ScriptedCall) -> ModelResponse:
        cancel.cancel()  # a person pressed stop while the model was thinking
        return call("lookup", '{"issue_id": "7"}')

    result = run_script(ScriptedModel([cancels_then_calls]), cancel=cancel)

    assert result.stop_reason == "cancelled"
    assert result.steps == () and handled == []
    assert result.total_tokens == 15  # the model call that happened is still counted


def test_a_cancelled_task_stops_cleanly_with_a_result():
    started = asyncio.Event()

    async def hangs(sent: ScriptedCall) -> ModelResponse:
        started.set()
        await asyncio.sleep(10)
        raise AssertionError("not reached")

    async def scenario() -> AgentResult:
        task = asyncio.create_task(run(PROMPT, ScriptedModel([hangs]), registry(), LIMITS))
        await started.wait()
        task.cancel()
        return await task

    result = go(scenario())

    assert result.stop_reason == "cancelled"


def test_rate_limited():
    model = ScriptedModel([ModelRateLimited("rate limit", retry_after=7.0)])

    result = run_script(model)

    assert (result.stop_reason, result.retry_after) == ("rate_limited", 7.0)


def test_model_error():
    model = ScriptedModel([call("lookup", '{"issue_id": "7"}'), ModelError("failed (500)")])

    result = run_script(model)

    assert result.stop_reason == "model_error"
    assert len(result.steps) == 1 and result.model_calls == 1


def test_an_exhausted_script_fails_the_test_loudly():
    with pytest.raises(ScriptExhausted, match="the script has 1 responses, and call 2 was made"):
        run_script(ScriptedModel([call("lookup", '{"issue_id": "7"}')]))


# --- No secrets in step records ---


def test_a_step_record_holds_no_secrets():
    secret_prompt = [*PROMPT, Message("user", "My Trello token is tok-SECRET-123.")]
    model = ScriptedModel(
        [
            call("login", '{"user": "ana", "password": "hunter2"}', id="ok"),
            call("login", '{"user": 5, "password": "hunter2"}', id="bad"),
            answer("Signed in."),
        ]
    )

    result = go(run(secret_prompt, model, registry(), LIMITS, clock=Clock()))

    good, bad = result.steps
    assert good.arguments == {"user": "ana", "password": "**********"}
    assert bad.arguments is None  # invalid arguments are never stored
    steps_text = repr(result.steps) + json.dumps([s.error for s in result.steps])
    for secret in ("hunter2", "tok-SECRET-123"):
        assert secret not in steps_text
        assert secret not in repr(result)  # the conversation is kept out of repr


# --- The registry and limits ---


def test_tool_names_are_unique_and_well_formed():
    with pytest.raises(ValueError, match="already registered"):
        registry(Tool("lookup", "again", Lookup, lookup))
    with pytest.raises(ValueError, match="tool name"):
        Tool("look up", "x", Lookup, lookup)


@pytest.mark.parametrize(
    "limits",
    [{"max_steps": 0}, {"max_seconds": 0}, {"max_total_tokens": 0}],
)
def test_limits_must_be_positive(limits):
    with pytest.raises(ValueError):
        Limits(**limits)
