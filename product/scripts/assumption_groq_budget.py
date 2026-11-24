"""Assumption test: one scenario-1 run fits in Groq's 8,000 tokens per minute.

Runs the real agent service flow (the system_v1 prompt, the four meeting tools, the
default limits) with the live GroqModel and the test fake ApiClient, seeded with 10
open issues, 2 upcoming events and 1 document. It sends the scenario-1 message five
times in new conversations, 60 seconds apart, and prints one line of metrics per run
and a summary as JSON. It never prints the key, the prompts or the replies.

    uv run --env-file .env python scripts/assumption_groq_budget.py
"""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for tests.fake_api

from tests.fake_api import FakeApi  # noqa: E402

from meeting_prep.agent.api_client import OpenIssue, UpcomingEvent  # noqa: E402
from meeting_prep.agent.model import GroqModel  # noqa: E402
from meeting_prep.agent.proposals import REVIEW_MEETING  # noqa: E402
from meeting_prep.agent.service import DEFAULT_LIMITS, AgentService  # noqa: E402
from meeting_prep.db import create_engine_for, upgrade  # noqa: E402
from meeting_prep.db.agent_store import AgentStore  # noqa: E402

USER = "assumption-user"
MESSAGE = "Prepare our sprint review for next Tuesday 3 to 3:30 pm Eastern from the open issues"
RUNS = 5
PAUSE_SECONDS = 60
TOKENS_PER_MINUTE = 8_000

ISSUES = [
    ("Fix login redirect loop on Safari", "6b01c2a1"),
    ("Folder delete leaves empty prefixes on OCI", "6b01c2a2"),
    ("Agenda document links to the wrong event", "6b01c2a3"),
    ("Retry-After not shown in the interface", "6b01c2a4"),
    ("Add pagination to the issues view", "6b01c2a5"),
    ("Calendar token expires after 7 days", "6b01c2a6"),
    ("Rate limit errors during the load test", "6b01c2a7"),
    ("Write the getting-started page", "6b01c2a8"),
    ("Dashboard panel for stuck runs", "6b01c2a9"),
    ("Release checklist for v0.3.0", "6b01c2b0"),
]
NOTES = """# Sprint 12 notes

- Storage v0.2.0 is released; v0.3.0 needs the folder delete fix.
- The Safari login loop blocks two testers.
- Open question: do we keep the 7-day Google token for the demo?
- Action: Prateek to finish the getting-started page before Wednesday.
"""


def seeded_api() -> FakeApi:
    api = FakeApi()
    api.issues = {USER: [OpenIssue(f"card-{i}", title) for title, i in ISSUES]}
    api.events = {
        USER: [
            UpcomingEvent("evt-1", "Team standup", "2026-11-24T14:00:00Z", "2026-11-24T14:15:00Z"),
            UpcomingEvent(
                "evt-2", "Advisor check-in", "2026-11-26T19:00:00Z", "2026-11-26T19:30:00Z"
            ),
        ]
    }
    api.documents = {(USER, "/reviews/sprint-12-notes.md"): NOTES}
    return api


async def one_run(service: AgentService, api: FakeApi) -> dict[str, Any]:
    conversation = service.create_conversation(USER)
    api.calls.clear()
    started = time.monotonic()
    reply = await service.send_message(USER, conversation.id, MESSAGE)
    seconds = time.monotonic() - started
    record = service.store.get_run(USER, reply.run_id) or {}
    proposal = reply.proposal
    arguments: dict[str, Any] = {}
    if proposal is not None and proposal.actions and proposal.actions[0].kind == REVIEW_MEETING:
        arguments = dict(proposal.actions[0].arguments)
    steps = record.get("steps", [])
    prompt, completion = record.get("prompt_tokens", 0), record.get("completion_tokens", 0)
    return {
        "success": bool(arguments),  # the tool only stores a proposal whose arguments validated
        "stop_reason": reply.stop_reason,
        "steps": len(steps),
        "tool_calls": [step["tool"] for step in steps],
        "tool_errors": [step["error"]["code"] for step in steps if step["error"]],
        "model_calls": record.get("model_calls", 0),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "seconds": round(seconds, 1),
        "rate_limited": reply.stop_reason == "rate_limited",
        "retry_after": reply.retry_after,
        "error": record.get("error"),
        "proposed_start": arguments.get("start"),
        "proposed_end": arguments.get("end"),
        "agenda_items": len(arguments.get("agenda", [])) if arguments else 0,
    }


async def main() -> int:
    model = GroqModel.from_env()
    api = seeded_api()
    with tempfile.TemporaryDirectory() as folder:
        url = f"sqlite:///{Path(folder) / 'assumption.sqlite3'}"
        upgrade(url)
        engine = create_engine_for(url)
        service = AgentService(AgentStore(engine), model, api, limits=DEFAULT_LIMITS)
        runs = []
        for number in range(1, RUNS + 1):
            if number > 1:
                await asyncio.sleep(PAUSE_SECONDS)
            result = {"run": number, **await one_run(service, api)}
            runs.append(result)
            print(json.dumps(result), flush=True)
        engine.dispose()

    totals = [run["total_tokens"] for run in runs]
    average = sum(totals) / len(totals)
    summary = {
        "model": model.model,
        "limits": {
            "max_steps": DEFAULT_LIMITS.max_steps,
            "max_seconds": DEFAULT_LIMITS.max_seconds,
            "max_total_tokens": DEFAULT_LIMITS.max_total_tokens,
        },
        "successes": sum(run["success"] for run in runs),
        "average_tokens": round(average),
        "max_tokens": max(totals),
        "runs_per_minute_at_average": TOKENS_PER_MINUTE // round(average) if average else None,
        "runs_per_minute_at_max": TOKENS_PER_MINUTE // max(totals) if max(totals) else None,
        "rate_limited_runs": sum(run["rate_limited"] for run in runs),
    }
    print(json.dumps({"summary": summary}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
