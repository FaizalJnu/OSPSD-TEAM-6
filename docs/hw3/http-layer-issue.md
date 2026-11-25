# Issue for Vikram: HTTP layer for POST /v1/review-meetings

Open in FaizalJnu/OSPSD-TEAM-6 with the "Feature request" template, label `enhancement`,
assignee Vikram739. Copy the title, then everything below the line as the body.

**Title:** [Feature]: HTTP layer for POST /v1/review-meetings: routes, API key, error mapping, request log

---

## Problem / Motivation

The orchestrator (#112) runs the review-meeting workflow, but nothing serves it over HTTP.
Prateek's interface (#110), the post-deploy smoke check and the first deploy all call
`POST /v1/review-meetings`, so this blocks all three. Nobody owned this part yet: #110 and
#112 both list it as "owner TBD".

**Is this related to an existing problem?**
Yes. Until it exists, the fixed workflow can't run outside tests, and the interface can only
run against its fake API.

## Proposed Solution

A new package, `product/src/meeting_prep/api/`. The import rules already reserve
`meeting_prep.api` as one of the two places allowed to import FastAPI.

**`routes.py`**
- `POST /v1/review-meetings`
  - Checks the API key first, before reading the body.
  - Passes the JSON body to `Orchestrator.run`. Step 0 in the orchestrator stays the only place
    that validates the body; the route adds no rules of its own.
  - Success: `RunResult.body()`, with **201** when the run completes in this request (new or
    resumed) and **200** when `replayed` is true.
  - Failure: `ReviewMeetingError.body()` with the status from the table below. For
    `run_in_progress`, it also sends a `Retry-After` header set to `retry_after`.
  - The orchestrator is synchronous, so declare the route with `def`, not `async def`. FastAPI
    then runs it in its thread pool.
- `GET /health`: 200 `{"status": "ok", "commit": "<sha>"}`, with no provider call. The commit
  comes from an environment variable the deploy sets. Name it in `.env.example` and tell
  Debasmith.

**Authentication:** `Authorization: Bearer <key>`, compared with `PRODUCT_API_KEY` using
`hmac.compare_digest`. A missing, malformed or wrong key gives 401 `unauthorized`, and the
orchestrator is never called. Add `PRODUCT_API_KEY` to `config.py` as a required setting and to
`.env.example` without a value.

**Status for each error code:**

| Code | Status |
|---|---|
| `invalid_request` | 400 |
| `unauthorized` | 401 |
| `permission_denied` | 403 |
| `run_in_progress` | 409, with `Retry-After` |
| `outcome_unknown` | 409 |
| `run_record_invalid` | 409 |
| `provider_error` | 502 |
| `provider_unavailable` | 503 |
| `internal_error` | 500 |

Everything else uses the same `{"error": {"code", "message"}}` body:
- A body that isn't JSON, or isn't a JSON object: 400 `invalid_request`. FastAPI's own 422
  shape must never reach a client.
- Unknown route: 404 `route_not_found`. Wrong method: 405 `method_not_allowed`.
- Any unexpected exception: 500 `internal_error`, with no exception text in the response.

**Request log:** one JSON line per request on stdout, with:
- `commit`, `run_id` (when known), `outcome` (`ok` or the error code), `duration_ms` and the
  step states;
- for a failed request, also `step`, `retryable`, `may_have_applied` and `provider_code` (the
  partner's original code, kept here for diagnosis only).

It never contains the title, an agenda item, the API key, a credential or provider text.

**`main.py`**
- `create_app(orchestrator, settings)` builds the app around an `Orchestrator` it is given, so
  tests pass one built on the fake adapters from #112.
- The module-level app for uvicorn does the startup wiring:
  `load_settings` → `build_implementations` → adapters → `Orchestrator`, built once.
  Any configuration error stops startup and names the variable, never its value.

## Acceptance Criteria

- [ ] HTTP tests on the fake adapters from #112 cover:
  - 201 for a new run, with the full body;
  - 200 for a replay, with `replayed: true` and no provider write;
  - 201 for a run resumed after a failure;
  - every code in the table, with its status and the full error body (`error.code`,
    `message`, `step`, `retryable`, `may_have_applied`, and `run`);
  - `Retry-After` on `run_in_progress`.
- [ ] A missing, malformed or wrong key gives 401, and the fakes record no call.
- [ ] A non-JSON body, a body that isn't an object, and a body with unknown fields each give
      400 `invalid_request` in our body.
- [ ] Unknown routes and methods give 404 and 405 in our body. An unexpected exception gives
      500 `internal_error`, and the response contains no exception text.
- [ ] Request log test: a failed request writes exactly one JSON line with the fields above.
      Plant recognizable strings in the title, the agenda, the key and the provider error, and
      check that none of them appears in the line.
- [ ] A missing `PRODUCT_API_KEY` stops startup and names the variable.
- [ ] `GET /health` returns the configured commit and calls no provider.
- [ ] `.env.example` and `product/README.md` updated.
- [ ] From `product/`: ruff check, ruff format --check, mypy and pytest pass; Product CI is green.

## Alternatives Considered

- **A pydantic model for the request body.** FastAPI would then validate the body with its own
  rules and answer 422. That duplicates step 0, and the two copies could drift apart (whole
  seconds, at most 8 hours, within 365 days). Step 0 stays the only place the rules live.
- **A route on the storage service.** The storage service stays one vertical, and `product/` is
  its own uv project on Python 3.14.

## Example Usage

```bash
curl -sS -X POST "$BASE_URL/v1/review-meetings" \
  -H "Authorization: Bearer $PRODUCT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"Sprint 4 review","start":"2026-12-01T15:00:00-05:00","end":"2026-12-01T15:30:00-05:00","agenda":["Open bugs"]}'
# 201 {"status": "completed", "run_id": "...", "replayed": false, "steps": [...], ...}
# The same request again: 200 with "replayed": true
```

## Additional Context

- **Owner:** Vikram. **Due:** Tue Nov 24 EOD.
- **Depends on #112.** Branch from `dev` after #112 merges.
- **Real providers need Darsh's adapters.** Whichever of this PR and Darsh's adapters PR merges
  second wires the real adapters into `main.py`. Until then, tests and local runs use the fake
  adapters through `create_app`. Once both are in, check Prateek's interface (#110) end to end
  with `FAKE_API` off and the fake providers configured.
- **The request log** was listed with Darsh's adapters. It belongs here, because only the HTTP
  layer sees the final error. Darsh's adapters supply `provider_code`.
- **Dependencies:** `fastapi` arrives with #116. If this PR merges first, add `fastapi` and
  `uvicorn` with `uv add` and commit `uv.lock`.
- **Out of scope:**
  - `GET /health/providers`, which needs a light check on each adapter; it's a follow-up after
    the adapters.
  - Per-user sign-in (Darsh).
  - The Dockerfile and the start command (Debasmith).
  - Traces and metrics (dashboard row).
  - The execute endpoint the agent service calls (Darsh).
