# Assumption test: a scenario-1 run fits Groq's free-tier token limit

Owner: Vikram Markali. Run on 2026-11-23 against the live Groq API, on branch
`115-agent-service`.

## Assumption

One scenario-1 run ("prepare a review meeting") fits inside Groq's free-tier limit of
**8,000 tokens per minute** for `openai/gpt-oss-120b`, with room for **more than one
user per minute**.

The limit applies per Groq organization. Every user of our deployment, the
evaluations and the load test share it.

## How it was tested

`scripts/assumption_groq_budget.py` runs the real agent service flow:
- `AgentService` with the `system_v1` prompt, the four meeting tools and the default
  limits (`max_steps` 8, `max_seconds` 60, `max_total_tokens` 6,000)
- the live `GroqModel` (`openai/gpt-oss-120b`)
- the test `FakeApiClient`, seeded with 10 open issues, 2 upcoming events and 1 sprint
  notes document

It sends "Prepare our sprint review for next Tuesday 3 to 3:30 pm Eastern from the
open issues" 5 times, each in a new conversation, 60 seconds apart. Tokens are the
`agent_runs` record's totals: the sum over every model call in the run, prompt and
completion.

A run counts as a success when it created a proposal, which the tool stores only after
its arguments pass validation. The script prints metrics only, never the key, the
prompts or the replies.

Command, from `product/`: `uv run --env-file .env python scripts/assumption_groq_budget.py`

## Results

| Run | Success | Stop reason | Steps (tools called) | Model calls | Prompt tokens | Completion tokens | Total tokens | Wall time | 429 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | No | completed | 1 (`list_open_issues`) | 2 | 1,998 | 813 | 2,811 | 2.8 s | No |
| 2 | No | completed | 1 (`list_open_issues`) | 2 | 1,998 | 706 | 2,704 | 2.6 s | No |
| 3 | Yes | completed | 2 (`list_open_issues`, `propose_review_meeting`) | 3 | 3,434 | 1,052 | 4,486 | 3.2 s | No |
| 4 | Yes | completed | 2 (`list_open_issues`, `propose_review_meeting`) | 3 | 3,432 | 909 | 4,341 | 2.9 s | No |
| 5 | Yes | completed | 2 (`list_open_issues`, `propose_review_meeting`) | 3 | 3,436 | 776 | 4,212 | 2.7 s | No |

- No run hit a limit or a 429. No tool returned an error.
- Runs 1 and 2 read the issues and answered with text instead of proposing.
- Runs 3 to 5 proposed a 30-minute meeting with 10 agenda items, all of them at
  `2026-11-28T15:00:00-05:00` to `15:30:00-05:00`.

| Measure | Tokens | Runs that fit in 8,000 per minute |
|---|---|---|
| Average, all 5 runs | 3,711 | 2 (8,000 / 3,711 = 2.16) |
| Average, the 3 successful runs | 4,346 | 1 (8,000 / 4,346 = 1.84) |
| Maximum | 4,486 | 1 (8,000 / 4,486 = 1.78) |

## Does it hold?

**Partly.**
- One scenario-1 run fits inside 8,000 tokens per minute, with about 3,500 to spare,
  and finishes in about 3 seconds.
- **More than one user per minute does not fit** for a run that reaches a proposal:
  two successful runs need about 8,700 to 9,000 tokens. The second user in the same
  minute would get a 429 (`rate_limited`) part way through.
- Only runs that stop without proposing (about 2,700 tokens) fit twice.

Every further message in a conversation also resends the whole history, so a
follow-up turn costs more than a first one.

## What this changes

- **Plan for one scenario-1 run per minute** on the free tier. The load test and the
  launch-week capacity estimate should use about 4,500 tokens per run, and the
  interface must show `rate_limited` with its retry time.
- To fit two users per minute, cut the prompt: a successful run sends about 3,400
  prompt tokens over three model calls, mostly the system prompt, the tool schemas
  and the issue list repeated on each call. Options:
  - fewer issues per read (a lower default `limit`)
  - shorter tool descriptions
  - a smaller model for the read steps
- The per-run token cap of 6,000 is above the largest run seen (4,486). It stays.

## Found along the way

- **The agent does not know today's date.** Asked for "next Tuesday", all three
  proposals chose Saturday 2026-11-28 (the run was on Monday 2026-11-23, so next
  Tuesday is 2026-11-24 or 2026-12-01). The arguments were valid, so validation could
  not catch it; the approval step would show the wrong date to the user. Fix: give the
  model the current date and the user's time zone in the conversation.
- **Two of five runs did not propose.** Those runs read the issues, then answered in
  text. The replies were not recorded, so the reason is unknown, but asking for
  confirmation is likely. This is consistent with the prompt's rule to ask when
  something is unclear. The evaluations should count it as a clarification, not a
  failure.
