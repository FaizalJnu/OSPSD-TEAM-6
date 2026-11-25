# Meeting Prep: launch readiness record

Team 6. Owner of this record: Faizal. Last updated 2026-11-25, 22:00 UTC.

This record links the evidence for launch and states the decision. Evidence labels:
**Observed** (we measured or saw it), **Reported** (a teammate, another team or a
provider's documentation told us), **Planned**, **Assumed**, **Estimate**.

## Launch decision

**Not ready** (2026-11-25). The fixed workflow, the agent service, sign-in and the
interface are built and tested on fakes, but:

1. The product is not deployed: the meeting services have no host or HTTPS address yet
   (Debasmith).
2. Users cannot connect their own Trello or Google Calendar yet, so the core scenario
   cannot run for anyone but the test account (Faizal).
3. There is no release candidate, so none of the measurements below has been taken
   against one.

**Next decision: Tue Dec 1, 18:00 ET.** We launch **ready with restrictions** if all of
these hold on the release candidate:

* the core scenario completes on staging for two signed-in users with their own
  providers, and neither can see the other's data;
* the security tests and the deterministic agent tests pass in CI;
* the evaluations meet the correctness target below, and no guardrail is broken;
* the kill switch, the alert and a rollback have each been exercised once.

The restriction we already expect: **one agent run per minute across all users**,
because of the model's free-tier limit (see Capacity).

## Release candidate

**Pending.** Tag, commit and deployed URL go here when Debasmith deploys the first
candidate.

## Launch audience and workload

| | Value | Label |
|---|---|---|
| Audience | Our team (5), the two teams assigned to us for launch week (about 10), course staff (about 3): about 18 accounts | Estimate |
| Simultaneous users | Up to 6 in the first hour after the launch post, then 1 or 2 | Estimate |
| Traffic mix per user over the week | 2 reviews prepared (about 2 agent messages each), 2 "next review" questions (1 message each), first-time sign-in and connections | Assumed |
| Agent runs | About 108 over the week: about 22 a day on average, up to about 44 on launch day | Estimate |
| Test duration | Load test: 15 minutes at the launch-day rate, plus a burst of 6 users at once | Planned |

The interface waits on each request; it does not poll. Retries come from users
pressing **Approve again** or resending a message, and are counted in the same totals.

## Service levels

Targets proposed for launch week (Dec 2 to 6); Debasmith confirms them. Each operation
is measured separately, so fast reads cannot hide slow agent runs.

| Operation | Indicator | Target | Measured |
|---|---|---|---|
| Ordinary API requests with no provider call (session, sign-in redirect, pages) | Latency | p95 ≤ 300 ms, p99 ≤ 1 s | Pending |
| Provider reads through the API (open issues, upcoming events, a document) | Latency | p95 ≤ 2 s, p99 ≤ 5 s | Pending |
| Agent message to reply or proposal (approval wait excluded) | Latency; runs stop at 60 s | p95 ≤ 45 s; timeouts reported alongside | Pending |
| Time to the first useful progress update | Latency | Same as the reply: the interface shows "Working" at once but receives no progress from the server. Recorded as a limitation | Pending |
| Execute an approved proposal (card, event, agenda) | Latency | p95 ≤ 15 s | Pending |
| All operations | Unexpected errors and timeouts / eligible requests | < 1%; deliberate 429s reported separately, with their effect on task completion | Pending |
| Core scenario | Correct results / attempted supported tasks | ≥ 4 of 5 evaluation runs per scenario; correct means the card, event and agenda exist with the requested title, time and items | Pending |
| Availability | Successful `/health` checks, once a minute | 99% over Dec 2 to 6 | Pending |

Saturation measured during the load test: CPU and memory of each container, database
connections in use, in-flight agent runs, tokens per run and per minute.

## Capacity

Traced for one "prepare a review" task: interface → agent service (model calls, tool
reads through the API) → API service (reads; then, after approval, the fixed workflow)
→ Trello, Google Calendar, our storage, the database.

### Per task

| Stage | Work per task | Label |
|---|---|---|
| Model (Groq, `openai/gpt-oss-120b`) | 3 calls and about 4,350 tokens for a run that reaches a proposal; 2 calls and about 2,750 tokens for a run that answers with text | Observed (5 live runs) |
| API reads | 1 Trello read, 1 Google Calendar read, 0 or 1 storage read | Observed (tool design) |
| Execute (after approval) | About 17 storage requests, 1 or 2 Trello requests, 1 Google Calendar request | Estimate |
| Database | About 20 queries per agent run | Estimate |

### Demand against limits

Planning figure: 3,700 tokens per agent run, the observed average over all five runs.

| Resource | Limit | Launch-day demand | Headroom |
|---|---|---|---|
| Groq tokens per minute | 8,000 (Reported); our own budget stops at 7,000 | One proposal run per minute fits; two do not | **Binding.** Beyond one run a minute, the agent answers "busy, try again in N seconds" |
| Groq tokens per day | 200,000 (Reported); our budget stops at 180,000 | 44 runs × 3,700 = about 163,000 | Fits, with little room. Average days use about 81,000 |
| Groq requests | 30 a minute, 1,000 a day (Reported) | About 110 a day | Fits |
| Per user | 5 messages a minute, 50 a day | At most a few a day | Fits |
| Trello | 100 requests per 10 s per token, 300 per 10 s per app key (Reported, Trello documentation) | Under 50 a day | Fits |
| Google Calendar | Per-project daily quota (check the Cloud console quota page) | Under 50 a day | Fits (Assumed) |
| Database connections | One worker per service, SQLAlchemy's default pool of 5 plus 10 overflow: at most 30 | Under 5 in use | Check against the hosted database plan's limit |
| Storage growth | About 4 KB per executed run (agenda and run record) | Under 1 MB for the week | Fits (Estimate) |
| Cost | Groq free tier, existing OCI VM, free database plan | $0 | (Assumed) |

**Concurrency (Little's law):** at the launch-day peak of about 2 runs a minute
(0.033 a second) and about 5 seconds per run, about 0.2 runs are in progress at a time.
Concurrency is not the limit; the model's token budget is.

**Burst:** if 6 users send their first message in the same minute, one or two runs
start and the rest are told to wait up to a minute. All six are served within about 4
minutes, as long as each user resends after the wait.

**What scales without help:** API and agent requests, the database, storage. **What
needs coordination:** the model quota. **What we limit at admission:** agent runs,
through the shared token budget and the per-user message limits.

## Failure map

What the user sees when each dependency fails, and how it recovers.

| Failure | What the user sees | Recovery | Tested |
|---|---|---|---|
| Model rate limit (Groq 429) or our budget is used up | "The agent is busy": wait the time shown, then send again | Automatic after the wait | Observed (scripted model) |
| Model error or timeout | "The agent stopped without an answer" | Resend, or ask for less at once | Observed (scripted model) |
| Trello or Google fails before the write | The change shows **Failed**; **Approve again** | Approving again finishes what is missing; nothing is created twice | Observed (fakes) |
| Trello or Google times out during the write | The change shows **Not sure** | The user checks the provider; an operator records the answer for a stopped run | Observed (fakes) |
| Storage unavailable | At the start: nothing is created. At the end: the card and event exist, but the change shows **Failed** | **Approve again** saves what is missing, without a second card or event | Observed (fakes) |
| Session expired or signed out | "Your session has ended" | Sign in again; the conversation is kept | Observed (tests) |
| Provider connection expired or revoked | **Pending:** "Reconnect Google Calendar / Trello" | Reconnect from the connections page | Pending (provider connections) |
| Database unavailable | **Pending** | **Pending** | Pending (game day) |

## Operations

| Item | Owner | Status |
|---|---|---|
| Deploy pipeline for both new services, with HTTPS and a post-deploy smoke check | Debasmith | Pending. The smoke-check script exists (`scripts/smoke_check.py`); the storage service already deploys this way |
| Kill switch: stop new agent runs or all writes while reads keep working | Debasmith | Pending |
| Rollout: our team → one launch-week team → the class. Advance when the stage has no broken guardrail and at least 80% of core-scenario attempts succeed; stop and use the kill switch on any broken guardrail | Debasmith | Planned |
| Dashboard: task success, errors, latency, model usage | Debasmith | Pending |
| Alert that reaches its owner, clears after recovery, links a runbook | Debasmith | Pending |
| Game day: an injected failure recovered by a teammate who did not write the runbook (Vikram), a release rollback, a backup restored into a disposable database | Debasmith | Pending |
| On call during launch week | Debasmith primary, Vikram backup; Faizal triages feedback daily | Planned |

## Evidence

| Evidence | Status | Where |
|---|---|---|
| Fast tests: fixed workflow, adapters, agent, sign-in, isolation, approvals | Observed: 436 product tests and 89 interface tests pass on `dev` (2026-11-25) | CI on every pull request |
| Deterministic agent tests and security tests | In review | Pull request #132 |
| Real-provider tests | Storage run on the real bucket passed; the three-provider run waits on configured test accounts | `tests/test_live.py` |
| Technical assumption test (model token budget) | Observed | [assumption-groq-budget.md](assumption-groq-budget.md) |
| Measured improvement (dates in the model's context) | Observed: correct dates 1 of 4 → 5 of 5 | [assumption-groq-budget.md](assumption-groq-budget.md) |
| Evaluations: 5 real-model runs per scenario, planted-instruction cases with a control | Pending | Prateek |
| Load test | Pending | Prateek |
| Usability check and outside sign-up check | Pending | Darsh, Faizal |

## Remaining risks

| Risk | Effect | Owner | Mitigation |
|---|---|---|---|
| Model free-tier limits | Users wait, or the agent refuses work, at busy moments | Vikram | Shared budget with clear "busy" answers; shorter prompts if the load test shows long waits |
| Google testing mode | Each user must be on the test-user list, and connections expire after 7 days | Faizal | Add staff and launch-week users before Dec 2; reconnect steps in the getting-started page |
| Team 5 has not released the credentials change | We run their package from our pull request's commit | Faizal | Pinned to an exact commit; switch to their tag when released |
| Trello tokens expire after 30 days | The test account's tracker stops working | Faizal | Renew before Dec 2 and before Demo Day |
| One worker process per service | A crash stops that service until it restarts; locks and budget counters live in memory | Debasmith | Container restart policy; the counters rebuild from the database |
| Product not yet deployed | No launch | Debasmith | Next decision Dec 1 |
