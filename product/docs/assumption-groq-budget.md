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

## Measured improvement

**Failure.** The agent was not told today's date. Asked for "next Tuesday", all three
proposals in the first test booked Saturday 2026-11-28 (above).

**Change (one).** A conversation now has a required IANA `time_zone` (migration
`0003`; an unknown name is 400). Every run adds one system message after the prompt
with the user's current date, weekday and time in that zone, from the service's clock.
The prompt moved to `system_v2`, which tells the model to work out relative dates
from that line and to state the exact weekday and date when it proposes. Runs record
`prompt_version: system_v2`.

**How the change was isolated.** `scripts/assumption_groq_budget.py --prompt v1` runs
`system_v1` with no date line; `--prompt v2` runs `system_v2` with the date line, as
the service does. The switch exists in the script only.

Both runs used everything else unchanged:
- the same seeded data, model (`openai/gpt-oss-120b`) and default limits
- a conversation in `America/New_York`
- this message, which names the title so the run does not stop to ask for it: "Prepare
  our sprint review titled Sprint 12 review for next Tuesday 3 to 3:30 pm Eastern from
  the open issues"

There were 5 runs per prompt, 60 seconds apart, on Monday 2026-11-23. A proposal is
correct if it is a Tuesday after today, 15:00 to 15:30 America/New_York.

| | v1: `system_v1`, no date line | v2: `system_v2`, date line |
|---|---|---|
| Proposals made | 4 of 5 | 5 of 5 |
| Proposals with a correct date | 1 of 4 | 5 of 5 |
| Dates proposed | Tuesday 2026-12-01 once, Saturday 2026-11-28 three times | Tuesday 2026-11-24 every time |
| Average tokens per run | 4,053 | 4,639 |
| Maximum tokens per run | 4,540 | 4,721 |
| 429s | 0 | 0 |

| Run | v1 result | v1 tokens (prompt / completion) | v2 result | v2 tokens (prompt / completion) |
|---|---|---|---|---|
| 1 | proposal, Tue 2026-12-01, correct | 4,216 (3,447 / 769) | proposal, Tue 2026-11-24, correct | 4,484 (3,779 / 705) |
| 2 | proposal, Sat 2026-11-28 | 4,262 (3,444 / 818) | proposal, Tue 2026-11-24, correct | 4,721 (3,778 / 943) |
| 3 | proposal, Sat 2026-11-28 | 4,297 (3,450 / 847) | proposal, Tue 2026-11-24, correct | 4,699 (3,776 / 923) |
| 4 | no proposal | 2,951 (2,008 / 943) | proposal, Tue 2026-11-24, correct | 4,640 (3,776 / 864) |
| 5 | proposal, Sat 2026-11-28 | 4,540 (3,449 / 1,091) | proposal, Tue 2026-11-24, correct | 4,649 (3,778 / 871) |

Every proposal was 15:00 to 15:30 Eastern with 10 agenda items, and no tool returned
an error. Each run with a proposal made 3 model calls (read the issues, propose,
answer), in 2.7 to 6.1 seconds.

**Why the run without a proposal stopped.** v1 run 4 read the issues, then asked which
Tuesday the user meant, offering "tomorrow (Tuesday 2026-11-24)". With no date given,
it could not tell.

**Result. The change works:**
- **Correct dates:** 1 of 4 before, 5 of 5 after. Every v2 proposal picked the
  nearest Tuesday.
- **Proposals:** 4 of 5 before, 5 of 5 after.
- **Cost:** v2 adds about 330 prompt tokens to each of the three model calls (the date
  line and the longer prompt). That is about 300 more tokens per successful run:
  4,639 on average, against 4,329 for v1's four successful runs.
- **Budget:** one run still fits in 8,000 tokens per minute (8,000 / 4,721 = 1.69),
  and two still do not. The budget conclusion above is unchanged.

### History: first rerun, with a message that gave no title

The first rerun used the original message, which names no title, and ran only v2.
It could not isolate the date change. It is kept here as a record.

On 2026-11-23, with the same script, message, seeded data, model and
limits, the conversation was created in `America/New_York`. There were 5 runs, 60
seconds apart. A proposal counts as correct if it is a Tuesday after today, 15:00 to
15:30 America/New_York. The script now also keeps the reply of a run that ends
without a proposal; replies are about the seeded test data only.

| | First test (`system_v1`, no date) | First rerun (`system_v2`, date line) |
|---|---|---|
| Proposals made | 3 of 5 | 0 of 5 |
| Proposals with a correct date | 0 of 3 (all Saturday 2026-11-28) | none to check |
| Dates stated in a reply | not recorded | 1 run, correct: "Tuesday 2026-11-24, 15:00 to 15:30 Eastern" |
| Average tokens per run | 3,711 | 2,640 |
| Maximum tokens per run | 4,486 | 2,798 |
| 429s | 0 | 0 |

| Run (first rerun) | Tools called | Model calls | Prompt / completion tokens | Total | Time |
|---|---|---|---|---|---|
| 1 | `list_open_issues` | 2 | 2,214 / 390 | 2,604 | 2.5 s |
| 2 | `list_open_issues` | 2 | 2,214 / 584 | 2,798 | 2.5 s |
| 3 | `list_open_issues` | 2 | 2,214 / 459 | 2,673 | 2.5 s |
| 4 | `list_open_issues` | 2 | 2,214 / 431 | 2,645 | 1.9 s |
| 5 | `list_open_issues` | 2 | 2,214 / 265 | 2,479 | 1.2 s |

**Why the runs without a proposal stopped.** All five read the open issues and then
asked for the **meeting title**, which the message does not give. Four of them also
asked whether the agenda should list every open issue. That is the prompt's rule 4
("if the title, times or agenda are missing or unclear, ask the user instead of
guessing"), which is unchanged from `system_v1`. Before, three runs guessed a title
and proposed. The first test did not keep replies, so it cannot show why its other
two runs stopped.

**Result.**
- **Date fixed where stated.** The date line works where the model states a date:
  the one run that restated the slot named the correct Tuesday, 2026-11-24. The
  wrong-weekday failure did not occur.
- **No proposal to verify.** This change could not be confirmed on a proposal,
  because no run made one.
- **Cheaper runs.** Runs that stop at a clarifying question are cheaper: about 2,600
  to 2,800 tokens, so 2 or 3 fit in 8,000 tokens per minute.
- **Not causal.** With 5 runs each, this does not show the date line caused the
  extra questions. The question rule did not change, and the first test already had
  2 of 5 runs without a proposal.

**Next measurement.** Done above, with a message that names the title. The product
question for the brief remains: should the agent pick a default title, such as
"Sprint review", instead of asking?
