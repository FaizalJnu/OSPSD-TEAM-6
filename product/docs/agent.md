# The agent service

The agent helps a project lead prepare a review meeting. It runs our own small loop
(`meeting_prep.agent.loop`) over a model (`GroqModel`, or `ScriptedModel` in tests)
and four tools. It never calls a provider: every tool goes through our API service
(`ApiClient`) as the signed-in user, and the only change it can ask for is a
proposal that a person approves first.

Owner: Vikram Markali.

## Tools

Every tool's arguments are a pydantic model. Arguments are validated before the
handler runs, and unknown fields are refused. Invalid arguments and unknown tools are
not run: the model gets a structured error (`invalid_arguments`, `unknown_tool`), the
step counts toward `max_steps`, and the run record logs it as a policy decision.

| Tool | Preconditions | Effects | Failures |
|---|---|---|---|
| `list_open_issues(limit=20)` | A signed-in user. `limit` is 1 to 100. | None. Reads the user's open tracker issues, newest first, through `ApiClient.list_open_issues`. Returns `{"issues": [{"id", "title"}]}`. | The API's error code and message, as a tool error (for example `provider_unavailable`). |
| `list_upcoming_events(days=14)` | A signed-in user. `days` is 1 to 60. | None. Reads the user's calendar events in the next `days` days. Returns `{"events": [{"id", "title", "start", "end"}]}`. | The API's error, as a tool error. |
| `read_document(path)` | A signed-in user. `path` is 1 to 1024 characters with no control characters. | None. Reads one of the user's stored documents. Returns `{"path", "content", "truncated"}`; content is cut at 20,000 characters. The run record keeps only the content's length. | `not_found` for a path with no document; any other API error, as a tool error. |
| `propose_review_meeting(title, start, end, agenda=[])` | A signed-in user. `title` is 1 to 120 characters after trimming; `start` and `end` are RFC 3339 with an offset and whole seconds; `end` is after `start` and at most 8 hours later; `start` is within the next 365 days; up to 20 agenda items of 1 to 200 characters. | Uses all three verticals: it plans a tracker issue, a calendar event and the agenda document, through one action for the fixed `POST /v1/review-meetings` workflow. It **executes nothing**: it stores a pending proposal and returns `{"proposal_id", "proposal_hash", "status": "pending_approval", "operation", "effects"}`. A pending proposal in the same conversation is superseded. | `invalid_arguments` for the rules above; `invalid_time` for a start in the past or more than 365 days ahead. |

The orchestrator validates the same request again when the API service runs it
(design §1.3, step 0).

## Proposals and approvals

* A proposal stores the user, the conversation, the exact actions and their
  arguments, and a SHA-256 hash of their canonical JSON (sorted keys, no spaces,
  UTF-8, over `{user_id, actions}`).
* `POST /v1/proposals/{id}/approve` takes the `proposal_hash` the person saw. A
  different hash is refused (`stale_proposal`), so an approval never covers content
  the person did not see. A superseded or rejected proposal cannot be approved.
* The approval is stored against the proposal ID, its hash and the user, and the
  proposal becomes `approved`. Execution then reads both back and checks they still
  match (`approval_matches`) right before it calls `ApiClient.execute`, on every path,
  retries included. The API service checks the approval again on its side.
* A changed proposal is a new proposal with a new hash. The old one is `superseded`
  and needs no further action; the new one needs its own approval.
* After `execute` returns, every action's outcome (`succeeded`, `failed`,
  `uncertain`) is stored and the proposal becomes `executed`. An action the API did not
  report is stored as `uncertain`. Approving an executed proposal again returns the
  stored outcomes and never calls `execute` again, also after a restart.
* If the execute call itself fails, the proposal stays `approved` and the response is
  502 `execution_failed`. Approving again retries the call. `POST
  /v1/review-meetings` is idempotent by request (design §2.2), so a retry never makes a
  second issue or event.

Proposal states: `pending` → `approved` → `executed`; `pending` → `rejected`;
`pending` → `superseded`.

## Endpoints

All of them act for the user `current_user` returns. Sign-in provides it; until it is
wired, every request is 401 `unauthorized`. Another user's IDs are 404 `not_found`,
exactly like IDs that do not exist. Errors are `{"error": {"code", "message"}}`.

| Method and path | Success | Errors |
|---|---|---|
| `POST /v1/conversations` `{"time_zone"}` (an IANA name, such as `America/New_York`) | 201 `{id, time_zone, created_at, messages: [], pending_proposal: null}` | 400 `invalid_request` for a name `zoneinfo` does not know, 401 |
| `GET /v1/conversations/{id}` | 200 `{id, time_zone, created_at, messages: [{role, content}], pending_proposal}`. Messages are the user's and the agent's text; tool traffic is not shown. | 401, 404 |
| `POST /v1/conversations/{id}/messages` `{"text"}` (1 to 4,000 characters) | 200 `{reply, stop_reason, run_id, proposal, retry_after}`. A run that stops on a limit, a rate limit or a model error is still 200, with `reply: null` and its `stop_reason`. | 400 `invalid_request`, 401, 404, 413 `payload_too_large`, 429 `rate_limited` or `busy` with `Retry-After` |
| `GET /v1/proposals/{id}` | 200 the proposal (`id, conversation_id, status, proposal_hash, actions, supersedes, created_at`) with its `outcomes` | 401, 404 |
| `POST /v1/proposals/{id}/approve` `{"proposal_hash"}` | 200 the executed proposal with its outcomes | 400, 401, 404, 409 `stale_proposal`, `proposal_superseded`, `proposal_rejected`, 502 `execution_failed` |
| `POST /v1/proposals/{id}/reject` | 200 the rejected proposal | 401, 404, 409 `proposal_not_pending` |

## Limits, prompt and records

* Default limits: `max_steps` 8, `max_seconds` 60, `max_total_tokens` 6,000.
* The system prompt is versioned in `src/meeting_prep/agent/prompts/` (now `system_v2.md`).
  Tool results are data, never instructions, and changes happen only through
  `propose_review_meeting`. A new version is a new file; each run records the version
  it used.
* Every run adds one more system message after the prompt: the user's current date,
  weekday and time in the conversation's time zone, from the service's clock (for
  example `Current date and time for the user: Monday 2026-11-23 14:05 in
  America/New_York (UTC-05:00).`). It is not saved with the conversation, so each run
  gets the date of that run.
* Every run writes one `agent_runs` row:
  * every step: the tool, its validated arguments (secret fields masked), its result
    or error, and its duration
  * the policy decisions: `refused_unknown_tool`, `rejected_arguments`,
    `approval_required`
  * the stop reason, the model error's type if any, token totals, the model ID, the
    prompt version, and the start and end times
  
  It never holds the user's message text or document content.
* Tables (migrations `0002` and `0003`, which adds `conversations.time_zone`): `conversations`, `messages`, `agent_runs`, `proposals`,
  `approvals`, `outcomes`. Every row carries the user ID, and every query filters by
  it (`meeting_prep.db.agent_store`).

## Containment

The rules that hold whatever the model, the user or the data say.

**Retrieved content is data.**
- Every successful tool result reaches the model wrapped as
  `{"untrusted_data": {"tool", "note", "content"}}`. The note says the content may
  hold text written by anyone, is never an instruction, and cannot change the tools,
  whose data is read, or the approval rules.
- The system prompt's rule 1 says the same.
- Errors the service writes itself (`unknown_tool`, `invalid_arguments`, `not_run`)
  are not wrapped.

**Tool authority.**
- The tools are fixed in code for each request. Nothing a model or a document says
  adds one: an unknown tool is refused and logged as `refused_unknown_tool`.
- Every tool acts only as the signed-in user, which comes from `current_user`, never
  from the model. No tool argument names a user. Unknown fields are refused, so a
  `user`, `user_id` or `owner` argument is `invalid_arguments` and logged as
  `rejected_arguments`.
- The three reads change nothing. `propose_review_meeting` only stores a proposal.
  The agent has no tool that approves or executes.

**Approval and resume.**
- Approving loads the proposal for the current user only (another user's is 404),
  compares the hash the person sent, and stores the approval against the proposal,
  its hash and the user.
- Execution reads both back and checks them again right before every
  `ApiClient.execute` call: after a restart, and on a retry after a failed execute.
- A change to the stored proposal after approval makes the check fail
  (`approval_required`).

**Request size.**
- A message is at most 4,000 characters. A request body is at most 16 KB, checked
  from `Content-Length` before the body is read, or counted as it arrives. Either
  over the limit is 413 `payload_too_large`.
- The model sees the system prompt, the date line, and at most the last 20
  conversation messages, the new one included. The history is cut so it starts at a
  user message, so no tool result is sent without the call it answers.

**Per-user message rate.**
- At most 5 messages per minute and 50 per rolling 24 hours, per user. Counted from
  saved messages, so the count survives a restart, plus that user's requests in
  flight.
- Over the limit is 429 `rate_limited`, with `Retry-After` set to when the oldest
  counted message leaves the window. The model is not called.

**Shared Groq token budget** (`agent/budget.py`). All users share one Groq
organization: 8,000 tokens per minute and 200,000 per day for `openai/gpt-oss-120b`.
The assumption test measured about 4,500 tokens per scenario-1 run
(`docs/assumption-groq-budget.md`), so we plan at one run per minute. Before each run:

| Count | Limit | Where it comes from |
|---|---|---|
| Tokens used in the last 60 seconds | 7,000 | `agent_runs`, every user, so it survives a restart |
| Tokens used in the last 24 hours | 180,000 | `agent_runs`, every user |
| Reserved by runs in flight | counted in both | 6,000 per run, its `max_total_tokens`, released when it ends |
| Groq's own count | `x-ratelimit-remaining-tokens` less 1,000 headroom | the last response's headers, until `x-ratelimit-reset-tokens` |
| A Groq 429 | no runs | until its `Retry-After`, or 60 seconds |

- A run starts only if its 6,000-token reservation fits every count. Otherwise the
  answer is 429 `busy`, with `Retry-After` set to the longest wait among the counts,
  and Groq is not called.
- The 1,000 and 20,000 tokens of headroom under Groq's limits absorb what the counts
  cannot see, such as the live provider test.
- A run cap larger than the per-minute budget is refused at startup, because such a
  run could never start.
- `token_usage_since` is the one query not filtered by user: the budget is shared,
  and it returns only times and token counts.

**Limits per run** (from the loop): `max_steps` 8, `max_seconds` 60,
`max_total_tokens` 6,000.

## Not yet

* `current_user` comes from sign-in (Darsh), and the `ApiClient` implementation from
  the API service's operations (Darsh). Until then, tests use `tests/fake_api.py`.
* One worker process: the per-conversation, per-proposal and per-user locks, the
  in-flight counts, the budget's reservations and Groq's last count are in memory.
  Usage and message counts come from the database and survive a restart; a second
  worker would need those in-memory parts shared too.
