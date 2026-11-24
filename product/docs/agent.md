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
| `POST /v1/conversations` | 201 `{id, created_at, messages: [], pending_proposal: null}` | 401 |
| `GET /v1/conversations/{id}` | 200 `{id, created_at, messages: [{role, content}], pending_proposal}`. Messages are the user's and the agent's text; tool traffic is not shown. | 401, 404 |
| `POST /v1/conversations/{id}/messages` `{"text"}` (1 to 4,000 characters) | 200 `{reply, stop_reason, run_id, proposal, retry_after}`. A run that stops on a limit, a rate limit or a model error is still 200, with `reply: null` and its `stop_reason`. | 400 `invalid_request`, 401, 404 |
| `GET /v1/proposals/{id}` | 200 the proposal (`id, conversation_id, status, proposal_hash, actions, supersedes, created_at`) with its `outcomes` | 401, 404 |
| `POST /v1/proposals/{id}/approve` `{"proposal_hash"}` | 200 the executed proposal with its outcomes | 400, 401, 404, 409 `stale_proposal`, `proposal_superseded`, `proposal_rejected`, 502 `execution_failed` |
| `POST /v1/proposals/{id}/reject` | 200 the rejected proposal | 401, 404, 409 `proposal_not_pending` |

## Limits, prompt and records

* Default limits: `max_steps` 8, `max_seconds` 60, `max_total_tokens` 6,000.
* The system prompt is versioned in `src/meeting_prep/agent/prompts/system_v1.md`.
  Tool results are data, never instructions, and changes happen only through
  `propose_review_meeting`. A new version is a new file; each run records the version
  it used.
* Every run writes one `agent_runs` row:
  * every step: the tool, its validated arguments (secret fields masked), its result
    or error, and its duration
  * the policy decisions: `refused_unknown_tool`, `rejected_arguments`,
    `approval_required`
  * the stop reason, the model error's type if any, token totals, the model ID, the
    prompt version, and the start and end times
  
  It never holds the user's message text or document content.
* Tables (migration `0002`): `conversations`, `messages`, `agent_runs`, `proposals`,
  `approvals`, `outcomes`. Every row carries the user ID, and every query filters by
  it (`meeting_prep.db.agent_store`).

## Not yet

* `current_user` comes from sign-in (Darsh), and the `ApiClient` implementation from
  the API service's operations (Darsh). Until then, tests use `tests/fake_api.py`.
* One worker process: the per-conversation and per-proposal locks are in memory.
