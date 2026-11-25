# **Review Meeting Service: Integration Design**

**Team 6, Document Storage vertical**

**Faizal Rahman, Debasmith Mandal, Vikram Markali, Darsh Shani, Prateek Saxena**

**Reviewers: Debasmith Mandal (Team 6, whole design): reviewed. Team 5 (Calendar implementation owner): reviewed, comments answered in 6.2. Team 4 (Issue Tracker implementation owner): requested. Dayana (Team 1, integration and contract-facing parts): requested.**

**Status: Proposed (HW3 Milestone 1). The design is written and in review. The operation is not yet implemented or deployed, so every trace and number below is marked Planned, Assumed or Estimate until a live run replaces it.**

**Last updated: 2026-11-18**

Evidence labels follow the HW2 design: **Observed** (seen by us), **Reported** (told to us by a teammate or another team), **Planned**, **Assumed**, **Estimate**.

**Relevant links**

* Operation code: product/ in this repository (Planned; not yet in the repository)

* HW2 design, including the storage service's deployment, pipeline and telemetry (Section 10): DESIGN\_hw2\_final.md

* Deployed storage service: [https\://ds.packapunch.xyz](https://ds.packapunch.xyz)

* Our HW2 service and its HTTP contract: [README.md](https://github.com/FaizalJnu/OSPSD-TEAM-6/blob/dev/README.md), [docs/API.md at 07f3168](https://github.com/FaizalJnu/OSPSD-TEAM-6/blob/07f3168/docs/API.md)

* Contracts consumed:

  * [cloud-storage-api 0.3.1](https://github.com/Dayana20/ospsd26-cloud-storage/tree/0.3.1/src/cloud_storage_api) (our vertical)

  * [issue-tracker-contract-v1.1.0](https://github.com/Tyler-Arciniaga/OSPSD-Team-4/tree/issue-tracker-contract-v1.1.0/contract) (Team 4\)

  * [calendar-contract v0.1.0](https://github.com/Airbus-A330/OSPSD-Calendar/tree/v0.1.0) (Teams 2, 5 and 7\)

* Implementations consumed:

  * Storage: our own S3-compatible implementation, storage\_service.shared\_storage.SharedDocumentStorage, against OCI Object Storage

  * Issue Tracker: Team 4's Trello package, tag team-4-issue-tracker-trello-v1.0.0

  * Calendar: Team 5's Google Calendar package, tag team5-calendar-v0.1.0

## **Milestone 1 status**

| Requirement (handout §3) | Where this design covers it | Implementation status |
| :---- | :---- | :---- |
| Python service on tagged shared-contract packages | 1.1, 1.5, 2.1 | Not started |
| Own implementation for storage, other teams' for tracker and calendar | 1.5, 2.1 | Not started |
| Implementation chosen by configuration, no code change to switch | 2.1, 2.4 | Not started |
| One operation, fixed steps, all three verticals, no model | Overview, 1.3 | Not started |
| Failures translated into the HW1 error model, naming the failed step | 1.4, 2.4, 3.1 | Not started |
| Deployed through the HW2 pipeline | 4 | Not started. The storage service's own pipeline is Reported, not Observed (open question 3\) |
| One test account per provider, credentials outside the repository | 2.4, 4.4 | Not started |
| Design reviewed by another team, comments answered | 6 | Reviewed by Debasmith (Team 6\) and Team 5 (Calendar); Team 5's comments answered in 6.2. Team 4 (Issue Tracker) and Dayana (Team 1\) reviews requested |

# **Overview**

HW2 gave us a consumer workflow that ran the same storage steps against any conforming storage service: create, metadata, download and compare, list, move, delete. Milestone 1 extends that consumer into a **deployed API operation that uses all three verticals**, with fixed steps and one test account per provider.

The operation is POST /v1/review-meetings. Given a meeting title, a start and end time, and a list of agenda items, it:

1. **claims the run** by creating a run record in document storage. The record's path comes from the request, so the same request always maps to the same run;

2. **opens a tracker issue** for the review (Team 4's Trello implementation);

3. **books the calendar event** (Team 5's Google Calendar implementation);

4. **writes the agenda document** to storage, linking the issue and the event;

5. **finishes the run** by marking the record complete, and returns the status of every step.

The steps are fixed. There is no language model, product brief or user interface. Milestone 2 picks the product, and this workflow may change then.

**What this adds to the HW2 consumer.** The HW2 workflow touched one vertical and cleaned up after itself. This operation leaves real state in three providers that share no transaction. Most of this design is about what happens when a later step fails after an earlier one succeeded, and how a caller can retry without creating a second issue or event.

**Why a storage team builds it this way.** Storage is the only one of the three contracts with a create that refuses to overwrite (DocumentStorage.create raises ConflictError). The calendar contract says "creation is not idempotent", and the issue tracker's Python interface, create\_issue(title), takes no idempotency key. Keeping the run record in storage gives the operation an idempotent first step, so retries are safe. It needs no database, and the record sits in a vertical we own and can inspect through our own HTTP API.

# **1\. How the system fits together**

## **1.1 Components**

| Component | Responsibility |
| :---- | :---- |
| HTTP layer (main.py, routes.py) | Request schema, one operation route plus health routes, API key check, error body, one log line per failed request. The only code that imports FastAPI |
| Orchestrator (orchestrator.py) | Validates input, derives the run ID and paths, reads or claims the run record, runs the remaining steps in order, builds the response from the record |
| Run record (run\_record.py) | Pure: the record's JSON shape, the step state machine, and the rules for resuming a run |
| Agenda document (agenda.py) | Pure: renders the Markdown from the validated request and the recorded IDs. The same inputs always give the same bytes |
| Adapters (adapters/storage.py, tracker.py, calendar.py) | The only code that sees a contract's exceptions. Each turns contract results and errors into our StepError (step, code, retryable, may\_have\_applied) |
| Implementation registry (factories.py) | One named builder per supported implementation (for example team6-s3, team4-trello, team5-google, fake, fake-failing). Each builder reads its own settings and calls that implementation's constructor. The only code that names an implementation package |
| Configuration (config.py) | Reads the environment once at startup. STORAGE\_PROVIDER, TRACKER\_PROVIDER and CALENDAR\_PROVIDER each name a registry entry. A missing, unknown or malformed value stops startup and names the variable, never its value |
| Fakes (fakes.py) | In-memory storage, tracker and calendar, plus a failing variant per vertical. Chosen through the same three variables as the real implementations |

**Why a separate service, not a new route on the storage service.** AGENTS.md keeps the storage service to one vertical: routes, then service, then StorageClient. Calendar and tracker clients do not belong in it. Team 5's package also requires Python 3.14 (Reported), while the storage service is on 3.13. The operation is its own uv project in product/, with its own lockfile, image and process. It depends on the storage service's package by path, so one commit builds both.

## **1.2 Diagram**

| Caller (curl, smoke check)   │  POST /v1/review-meetings  {title, start, end, agenda\[\]}   │  Authorization: Bearer \<PRODUCT\_API\_KEY\>   ▼ Traefik, TLS — meetings.packapunch.xyz (Proposed)            OCI Ampere VM, Amsterdam   │   ▼ team6-review-meetings container ──────────────────────────────────────────────────────   main.py / routes.py    schema, API key check, error body, failure log line   orchestrator.run       0 validate (no I/O) → 1 claim\_run → 2 create\_issue                          → 3 create\_event → 4 write\_agenda → 5 finish\_run   adapters               StorageAdapter        TrackerAdapter          CalendarAdapter   shared contract (tag)  DocumentStorage       IssueProvider           CalendarService                          cloud-storage-api     issue-tracker-contract  calendar-contract                          0.3.1                 v1.1.0                  v0.1.0   implementation         Team 6                Team 4 Trello           Team 5 Google Calendar   (registry entry        SharedDocumentStorage team-4-issue-tracker-   team5-calendar-v0.1.0    named by env)         → S3Storage           trello-v1.0.0   test-account           S3\_\* env vars         TRELLO\_\* env vars       CALENDAR\_TOKEN\_FILE   credentials                                                          (read-only mount) ─────────────┬────────────────────┬───────────────────────┬───────────────────────────              ▼                    ▼                       ▼    OCI Object Storage       Trello REST API          Google Calendar API    run-record bucket:       one test board,          one test account,    /review-runs/\*.json      one list                 primary calendar    /reviews/\*.md   Credential path: CI environment secrets (staging and demo kept apart)   → container environment and the mounted token file at deploy time.   Never in the repository, the image, a response or a log line.   Startup: config.py reads the environment → factories.py builds the three implementations once → any failure exits before serving, naming the variable. |
| :---- |

The run record is rewritten between steps (2.2). After a failure at any point, the record says which steps finished, which one was in flight, and which never started.

## **1.3 One request traced (Planned)**

This is the trace the design expects. A real run on the deployed service, with its commit, will replace it before the milestone is marked Implemented.

**Request**

| POST /v1/review-meetings Authorization: Bearer \<api key\> Content-Type: application/json   {   "title": "Storage v0.2.0 release review",   "start": "2026-11-20T15:00:00-05:00",   "end": "2026-11-20T15:30:00-05:00",   "agenda": \["Folder delete results on OCI", "Open bugs", "Release go or no-go"\] } |
| :---- |

**0\. validate.** No provider call. The schema rejects unknown fields. The title is trimmed and must be 1 to 120 characters. start and end must be RFC 3339 with an explicit offset and whole seconds, with end after start and at most 8 hours later. start must fall within the next 365 days. agenda holds 0 to 20 items of 1 to 200 characters each. The orchestrator normalizes start and end to UTC and computes:

* run\_id \= first 12 hex characters of SHA-256 over the canonical JSON of {title, start\_utc, end\_utc, agenda}, for example 3f9a1c0d7b2e.

* record path /review-runs/3f9a1c0d7b2e.json.

* agenda path /reviews/2026-11-20-storage-v0-2-0-release-review-3f9a1c0d7b2e.md (UTC date, then a lowercase ASCII slug of the title cut to 40 characters, then the run ID).

**1\. claim\_run.** DocumentStorage.create("/review-runs/3f9a1c0d7b2e.json", record), with every step pending and create\_issue marked attempting. On S3 this is HeadObject (404), HeadBucket (our check that a 404 means a missing key, not a missing bucket), PutObject, then a HeadObject readback. It succeeds and returns the shared FileInfo (path, size, etag, modified\_at; id is null on S3). This request now owns a new run.

**2\. create\_issue.** IssueProvider.create\_issue("Review: Storage v0.2.0 release review \[3f9a1c0d7b2e\]"). The run ID in brackets is a marker that the recovery in 2.3 searches for. Trello returns a card, for example id 6b01c2.... The record is replaced with create\_issue: done, id 6b01c2... and create\_event: attempting.

**3\. create\_event.** CalendarService.create(CreateEvent(title="Review: Storage v0.2.0 release review \[3f9a1c0d7b2e\]", start=..., end=...)). Google returns an event ID. The record is replaced with create\_event: done, id ... and write\_agenda: attempting.

**4\. write\_agenda.** DocumentStorage.create(agenda\_path, markdown):

| \# Review: Storage v0.2.0 release review   \- When: 2026-11-20T20:00:00Z to 2026-11-20T20:30:00Z \- Calendar event: \<event id\> \- Tracker issue: \<issue id\> \- Run: 3f9a1c0d7b2e   \#\# Agenda   1\. Folder delete results on OCI 2\. Open bugs 3\. Release go or no-go |
| :---- |

**5\. finish\_run.** The record is replaced with state: completed.

**Response, 201 Created**

| {   "status": "completed",   "run\_id": "3f9a1c0d7b2e",   "replayed": false,   "steps": \[     {"name": "claim\_run", "status": "ok"},     {"name": "create\_issue", "status": "ok"},     {"name": "create\_event", "status": "ok"},     {"name": "write\_agenda", "status": "ok"},     {"name": "finish\_run", "status": "ok"}   \],   "issue": {"id": "6b01c2..."},   "event": {"id": "...", "start": "2026-11-20T20:00:00Z", "end": "2026-11-20T20:30:00Z"},   "agenda": {"path": "/reviews/2026-11-20-storage-v0-2-0-release-review-3f9a1c0d7b2e.md"},   "record": {"path": "/review-runs/3f9a1c0d7b2e.json"} } |
| :---- |

Sending the same request again returns 200 with the same body and "replayed": true. It makes no provider write: one refused claim (one HeadObject) and one download of the record.

## **1.4 The operation's contract**

| Item | Value |
| :---- | :---- |
| Operation | POST /v1/review-meetings |
| Auth | Authorization: Bearer \<key\>, compared in constant time with PRODUCT\_API\_KEY. Missing or wrong: 401 unauthorized, no provider call |
| New run completed | 201 Created |
| Same request, run already completed | 200 OK, "replayed": true, nothing written |
| Same request, earlier run stopped part way | Resumes from the first unfinished step. 201 if it completes now |
| Liveness | GET /health: 200 {"status": "ok", "commit": "\<sha\>"}, no provider call |
| Readiness | GET /health/providers: one light call to storage (HeadBucket) and tracker (list\_issues(limit=1)). Calendar is reported unchecked (2.4) |

**Request body.** title, start, end and agenda as validated in step 0\. Unknown fields are rejected. The body is the run's identity: two requests that differ only in the UTC offset of start are the same run, while a different title or agenda is a different run.

**Success body.** As in the trace. Clients ignore fields they do not recognize, the same rule our storage contract uses.

**Error body.** It is the HW1 error envelope ({"error": {"code", "message"}}, [API.md, Errors](https://github.com/FaizalJnu/OSPSD-TEAM-6/blob/07f3168/docs/API.md)) with added fields, so a client that only reads error.code still works:

| {   "error": {     "code": "provider\_error",     "message": "The calendar did not confirm the event. It may have been created.",     "step": "create\_event",     "retryable": false,     "may\_have\_applied": true   },   "run": {     "run\_id": "3f9a1c0d7b2e",     "status": "partial",     "steps": \[       {"name": "claim\_run", "status": "ok"},       {"name": "create\_issue", "status": "ok"},       {"name": "create\_event", "status": "unknown"},       {"name": "write\_agenda", "status": "pending"},       {"name": "finish\_run", "status": "pending"}     \],     "issue": {"id": "6b01c2..."},     "event": null,     "agenda": null,     "record": {"path": "/review-runs/3f9a1c0d7b2e.json"}   } } |
| :---- |

* error.step names the step that failed. run is null when the request was rejected before step 1\.

* run.status is failed if nothing exists in any provider apart from the run record, partial if an issue or event exists or may exist, and completed only on success.

* retryable: true means sending the **same request** again is safe and resumes the run. false means a person has to act first; the message says what.

* may\_have\_applied: true means the failed step's write may have happened.

* Messages never contain provider text, credentials, URLs or request content (the HW1 rule in [API.md, What stays internal](https://github.com/FaizalJnu/OSPSD-TEAM-6/blob/07f3168/docs/API.md#what-stays-internal)).

**Codes.** The HW1 codes are reused unchanged. Four codes are new to this operation, and every vertical is translated into this one set (2.4):

| Status | Code | Meaning | In HW1 |
| :---- | :---- | :---- | :---- |
| 400 | invalid\_request | The body breaks a rule in step 0\. Nothing was called | Yes |
| 401 | unauthorized | Missing or wrong API key. Nothing was called | New |
| 403 | permission\_denied | A provider refused the test account's credentials or permissions | Yes |
| 409 | run\_in\_progress | Another request is working on this run (2.2). Retry-After is set | New |
| 409 | outcome\_unknown | An earlier attempt left an event whose existence is unknown. The run will not continue until an operator resolves it (2.3) | New |
| 409 | run\_record\_invalid | The record at the run's path cannot be read as a record, names a different request, or disappeared mid-run | New |
| 502 | provider\_error | A provider failed or gave an unusable answer | Yes |
| 503 | provider\_unavailable | A provider could not be reached, or the calendar authorization has expired | Yes |
| 500 | internal\_error | A bug in this service | Yes |

Unknown routes and methods keep the HW1 route\_not\_found and method\_not\_allowed handlers.

**Usage (Planned endpoint).**

| curl \-sS \-X POST https\://meetings.packapunch.xyz/v1/review-meetings \\   \-H "Authorization: Bearer \$PRODUCT\_API\_KEY" \\   \-H "Content-Type: application/json" \\   \-d '{"title":"Storage v0.2.0 release review","start":"2026-11-20T15:00:00-05:00","end":"2026-11-20T15:30:00-05:00","agenda":\["Open bugs"\]}' |
| :---- |

Staging uses meetings-staging.packapunch.xyz. Course staff receive the API key privately, not in the repository or the submission text.

## **1.5 Contracts we consume, and what we rely on**

| Vertical | Operations used | What we rely on |
| :---- | :---- | :---- |
| Storage (cloud-storage-api 0.3.1) | create, replace, download, check\_health | create raises ConflictError if the path exists; replace raises NotFoundError and never creates; download returns exact bytes. We use the bytes download, which our adapter caps at 150 MiB; a run record or agenda is a few kilobytes |
| Issue Tracker (issue-tracker-contract v1.1.0) | create\_issue, get\_issue(fresh=True), list\_issues | list\_issues is newest first, never cached, at most 100\. ServiceError.may\_have\_applied distinguishes a lost response from a refused write. Titles 1 to 256 characters |
| Calendar (calendar-contract v0.1.0) | create, get | An uncertain create raises PROVIDER\_ERROR with retryable=False. get of a missing ID raises NOT\_FOUND. Clients compare instants, not strings. Team 5's package sets no title limit (it only trims spaces) and never retries a create that may have gone through (Team 5 review, 6.2) |

**Operations we need that the contracts do not provide.** Each gap shapes a decision below. Gaps in another team's contract or implementation are filed in the owner's repository with a reproduction, not worked around silently.

| Gap | Owner | Effect on this design | Workaround in Milestone 1 | Reported |
| :---- | :---- | :---- | :---- | :---- |
| Calendar has no list or search, no client-chosen ID and no idempotency key | Calendar contract (Teams 2, 5, 7\) | A lost create response cannot be found again | Calendar is the last risky write; an unknown outcome stops for an operator (2.3) | To file, owner Faizal |
| Calendar has no health operation | Calendar contract | Readiness cannot check the calendar | Reported as unchecked; the smoke check makes a real create (2.4, 4.3) | To file, owner Faizal |
| Tracker package's create\_issue takes no idempotency key (Team 4's HTTP service has one) | Team 4 | A retried create could duplicate the issue | Marker in the title, found again with list\_issues (2.3) | To file, owner Faizal |
| Team 5's Calendar call has no timeout: it uses the Google client's default HTTP settings (only token refresh times out, after 10 s) | Team 5 | A hung create could outlive the 120-second lease (2.2) | socket.setdefaulttimeout(30) at startup; a calendar timeout is an unknown outcome (2.2) | Raised by Team 5 in review (6.2, T5-2) |
| Our S3 create is check-then-put, not atomic | Team 6 (our implementation; HW2 open question 15\) | Two identical requests within one round trip could both claim a run | One worker process with a per-run lock (2.2) | Tracked in the HW2 design |

**Error translation.** Each adapter owns one table:

| From | To |
| :---- | :---- |
| Storage ConflictError at claim\_run | Not an error: the run exists, so the orchestrator downloads the record and resumes |
| Storage ConflictError at write\_agenda | Not an error: replace with the same bytes |
| Storage NotFoundError on a record replace | run\_record\_invalid (the record was removed mid-run) |
| Storage InvalidRequestError | internal\_error (our own paths always pass the rules, so this is a bug) |
| Storage PermissionDeniedError | permission\_denied, not applied |
| Storage ProviderError / ProviderUnavailableError | provider\_error / provider\_unavailable. A failed create or replace may have applied |
| Tracker ACCESS\_DENIED | permission\_denied |
| Tracker SERVICE\_NOT\_CONFIGURED | provider\_unavailable, not retryable (operator action) |
| Tracker PROVIDER\_ERROR | provider\_error, may\_have\_applied as the error says |
| Calendar ACCESS\_DENIED | permission\_denied |
| Calendar PROVIDER\_UNAVAILABLE, retryable=False | provider\_unavailable, not retryable. Team 5 raises this when the Google authorization is missing or expired (Reported) |
| Calendar PROVIDER\_UNAVAILABLE, retryable=True | provider\_unavailable, retryable |
| Calendar PROVIDER\_ERROR on create | provider\_error, may\_have\_applied: true, not retryable |
| Calendar INVALID\_INPUT | internal\_error (step 0 is stricter than the contract and Team 5 sets no title limit, so this is a bug, or a limit of an alternate implementation) |
| A timeout (TimeoutError, including socket.timeout) raised from calendar create | provider\_error, may\_have\_applied: true, not retryable: the step becomes unknown (2.2) |
| Any other exception from an implementation | internal\_error. The adapter logs the exception type only |

## **1.6 Run record**

| {   "version": 1,   "run\_id": "3f9a1c0d7b2e",   "request": {"title": "...", "start": "2026-11-20T20:00:00Z", "end": "2026-11-20T20:30:00Z", "agenda": \["..."\]},   "state": "in\_progress",   "updated\_at": "2026-11-18T21:04:11Z",   "steps": {     "create\_issue": {"state": "done", "id": "6b01c2..."},     "create\_event": {"state": "attempting"},     "write\_agenda": {"state": "pending"}   } } |
| :---- |

Step states are pending, attempting, done, unknown (a write that may have applied) and not\_applied (a write that was refused or never sent). updated\_at comes from the service's clock, not the provider's modified\_at: OCI reports whole seconds (HW2 provider runs), and this field is only used for the lease in 2.2.

## **1.7 Fixed steps now, judgment later**

Milestone 1 has no model. Building the path in plain code shows which parts never needed judgment.

| Stays fixed in code (also in Milestone 2\) | Needs judgment later (a person now, possibly the agent in Milestone 2\) |
| :---- | :---- |
| Input validation and the strictest-rule limits (2.4) | What the meeting is about: title and agenda items, drawn from open issues or notes |
| Run identity, the run record, step order, the lease and resume rules (2.2, 2.3) | When to meet: the caller supplies the time. Choosing a free slot needs free/busy data the calendar contract does not offer |
| Error translation and which step failed | Whether to reuse an existing issue or event instead of creating a new one |
| Agenda layout and the links between issue, event and document | What the agenda says beyond the listed items |
| Never retrying an uncertain write; stopping on an unknown calendar outcome | How to resolve an outcome\_unknown run: today an operator checks the calendar |

Anything that creates, changes or deletes provider data stays behind this fixed path, so a later agent can propose a run but cannot skip its checks.

# **2\. Decisions**

The three decisions with the greatest effect on the integration are where the implementations run (2.1), where run state lives (2.2) and the order of the writes (2.3). Section 2.4 states the boundaries and the rules that hold whatever fails.

## **2.1 Call the implementations in-process, chosen by name from configuration**

* **Constraint:** the milestone needs one deployed operation, one test account per provider, and a swap between teams' implementations with no code change. Teams publish their implementations as Python packages behind the shared interfaces.

* **Approach:** install the three contracts and every implementation we may select, pinned to immutable tags in product/uv.lock. factories.py holds one builder per installed implementation. STORAGE\_PROVIDER, TRACKER\_PROVIDER and CALENDAR\_PROVIDER name the builder to use, and each builder reads only its own settings. Swapping between installed implementations is then a change to one variable and that implementation's credentials. Adding an implementation that was never installed is a reviewed code change (a dependency and a builder), made before the swap is needed. For the swap in 3.3, a second calendar implementation is installed and registered ahead of time (open question 11).

* **Alternative:** call each team's deployed HTTP service (our dev deployment, Team 4 on Render, a Calendar team's service), as the HW2 consumer did.

* **Tradeoff:** in-process, we hold the test account's credentials and do not depend on three other deployments staying up. The cost is the partners' Python constraints (Team 5 needs 3.14) and their dependencies in our image. Over HTTP, Team 4's server-side Idempotency-Key would make step 2 safe to retry, which the package does not offer.

* **If a partner's implementation is unavailable:** a provider outage returns 503 and the caller resends the same request later (3.1). A broken release of a partner package is reported to its owner with a reproduction. We keep our pin on the last tag that works, or switch to the alternate implementation through configuration.

* **Evidence:** Team 4's HW3 product installs the same three kinds of packages from tags and swaps storage implementations by configuration (their docs/evidence/storage-swap.md, Reported). Our own install is Planned.

* **Revisit when:** a partner's package lags its deployed service, or Milestone 2 needs a feature only one team's HTTP service has.

## **2.2 Keep the run record in our storage, keyed by the request**

* **Constraint:** neither the calendar create nor the tracker package create is idempotent. A caller that loses a response, or retries after a timeout, must not get a second issue or event.

* **Approach:** the run ID is a hash of the normalized request. Step 1 creates the record with DocumentStorage.create, whose ConflictError tells this request that the run exists. The orchestrator then downloads the record and resumes. Before each partner write, the record says attempting; after it, the record holds the ID. A record whose create\_issue or create\_event step is attempting and whose updated\_at is less than 120 seconds old belongs to a live request. A second request then gets 409 run\_in\_progress, with Retry-After set to the rest of that lease. An attempting agenda or finish step takes no lease, because repeating it is harmless.

* **Why the lease holds:** our S3 client uses a 5-second connect timeout, a 60-second read timeout and standard retry mode with max\_attempts=3, so one call can make up to four attempts ([storage/s3.py:78-80](https://github.com/FaizalJnu/OSPSD-TEAM-6/blob/07f3168/src/storage_service/storage/s3.py#L78-L80); HW2 design Section 5). The record write that sets attempting can therefore itself take minutes. The orchestrator starts a tracker or calendar write only if fewer than 20 seconds have passed since the updated\_at it wrote. Otherwise it records the step as not\_applied and stops with 503 provider\_unavailable, retryable: true, before calling the partner. The partner calls are then bounded:

  * Team 4's Trello calls time out after 10 seconds per network operation (their API documentation, Reported).

  * Team 5's token refresh times out after 10 seconds, but the Calendar call itself uses the Google client's default HTTP settings, which have **no timeout** (Team 5 review, 6.2 T5-2). The service therefore sets socket.setdefaulttimeout(30) once at startup, which the Google client picks up (Reported by Team 5). The setting is process-wide but applies only to sockets opened without their own timeout; botocore and Team 4's package set their own.

  * Calendar worst case: 20 s guard \+ 10 s token refresh \+ 30 s connect \+ 30 s waiting for the response \= 90 s, under the 120-second lease. A socket timeout bounds each blocking operation, not the whole call, so a server that trickles its response could stretch it. We accept that for a small JSON response.

A request that finds the lease expired can therefore assume the first request's partner call has finished. A calendar timeout is an unknown outcome, not a refusal: the step becomes unknown and the run stops at outcome\_unknown (2.3).

* **What an expired lease never does:** a step still attempting after its lease belongs to a request that stopped (a crash, a redeploy, or a failed record write). Recovery searches for the tracker issue by its marker. The calendar step becomes unknown and is **never created again automatically**. An expired lease alone cannot make a second event. The timeout bound matters because an operator resolving an outcome\_unknown run must not check the calendar while the first create may still be running.

* **Alternative 1, caller-held state:** return the IDs and have the caller send them back to resume. Team 4 chose this. A caller that loses the response has to check the calendar by hand, and Team 3's review of Team 4 suggested a storage record instead (Reported).

* **Alternative 2, a database on the VM** (SQLite, as Team 4's HW2 service uses for idempotency keys): it adds a stateful volume to back up and migrate. The storage record can be read and repaired through our own HTTP API.

* **Alternative 3, a caller-supplied Idempotency-Key:** it would let a caller ask for two identical meetings on purpose. The cost is key retention rules, and a caller that forgets the key loses all protection. With our design, a caller who wants two meetings changes the title.

* **Tradeoff:** a new run costs about 17 small S3 requests instead of 3 (4.6), and a storage outage stops the operation before anything else is called. Our create checks, then puts, so two identical requests arriving within one round trip could both claim the run. We accept that for Milestone 1 by running one worker process with a per-run lock.

* **Evidence:** our create's 409 on an existing key is covered by tests/test\_upload.py and recorded OCI runs in TESTING.md. The check-then-put pattern and the unverified conditional write are recorded in the HW2 design (Section 5, Provider-call costs; open question 15).

* **Revisit when:** OCI is shown to honour a conditional PutObject (If-None-Match: \*). Then create closes the race and more than one worker is safe.

## **2.3 Order: storage, then tracker, then calendar, then storage; resume forward**

* **Constraint:** the three providers share no transaction, so any step can fail after an earlier one succeeded.

* **Approach:** order the writes by how well we can recover each one's lost outcome:

  1. **Storage claim** first. It is idempotent and leaves nothing in a provider a person looks at.

  2. **Tracker** second. A lost create\_issue response can be recovered: list\_issues(limit=100) is fresh and newest first, and our title carries the marker \[\<run\_id\>\]. On resume, an attempting or unknown issue step searches for the marker. If found, the ID is adopted. If not, the issue is created. The 120-second lease means the earlier request's call has finished by then.

  3. **Calendar** last among the partner writes. A lost create cannot be found, because the contract has no list, so it is the last risky call. A timeout, a lost response, or an attempting step found after its lease all count as unknown. If it ends unknown, the run stops with 409 outcome\_unknown until an operator checks the test calendar and records the answer (scripts/resolve\_run.py \<run\_id\> \--event-id \<id\> or \--no-event, Planned).

  4. **Agenda and finish** last. Both are safe to repeat: the agenda bytes depend only on the record, so a resume uses create and, on ConflictError, replaces with the same bytes.

* **Alternative:** calendar before tracker. An unrecoverable unknown outcome would then come first, and every later step would wait on an operator.

* **Alternative, compensation:** on failure, delete what earlier steps created. A compensating delete can fail too, and an event of unknown ID cannot be deleted. We resume forward instead, and say exactly what exists.

* **Tradeoff:** while a run is stuck at the calendar step, the tracker can hold an issue for a meeting that was never booked. The response and the record both name it.

* **Revisit when:** the calendar contract gains a list or a client-chosen ID, which would make step 3 recoverable like step 2\.

## **2.4 Boundaries and the rules that must hold**

| Boundary | Rule |
| :---- | :---- |
| Caller → our API | The API key is checked before anything else. Step 0 validates the whole body before the first provider call. It applies the strictest rule from each contract plus our own: whole seconds (a calendar server may drop sub-seconds), at most 8 hours, within 365 days. It also builds every path and title. A contract rejecting our input later is reported as internal\_error, since it means step 0 is wrong. Our limits are tighter than any single provider's; that is intended for a fixed-step operation |
| Orchestrator → contracts | The orchestrator calls only the adapters. Only adapters import contract interfaces and exceptions; only factories.py names implementation packages; only main.py and routes.py import FastAPI. test\_import\_boundary.py enforces this |
| Contracts → implementations | Chosen at startup by registry name (2.1). No request can change the implementation, and nothing falls back silently to another implementation or a fake |
| Credentials | Values live in CI environment secrets and reach the container at deploy time (4.4). The repository, the image, responses and logs never hold them. .env.example lists the names without values. A startup error names the missing variable, never its value |
| Errors | Every vertical's errors are translated into the one code set in 1.4, with the step named. A client then needs one table to read one operation. Detail from the other verticals is reduced to our codes; the failure log keeps the original code for diagnosis. The alternative, passing each vertical's code through, would make a client handle three code tables |
| Calendar readiness | The calendar contract has no health operation, and Team 5's Google token can expire after 7 days while its OAuth app is in Testing mode (Team 5's package README, Reported). GET /health/providers reports the calendar as unchecked, and the post-deploy smoke check (4.3) makes a real create and delete. Probing with get on a made-up ID was rejected: it depends on how Team 5 handles IDs it cannot parse, which the contract does not define. Revisit when the contract adds a health check or our OAuth app leaves Testing mode |

**Invariants that hold whatever fails**

1. Invalid input and failed authentication never reach a provider.

2. No uncertain write is retried automatically inside a request.

3. The response's issue and event list only IDs known to exist.

4. The agenda is written only after both the issue and the event exist, so it never links to something missing.

5. Nothing after a failed step runs in that request.

6. run.status is completed only after the finish\_run write succeeds. The response is built from the record, never from what the request intended.

7. No provider text, credential, title or agenda item appears in a response message or a log line.

# **3\. What could go wrong**

## **3.1 Failures**

"Same request" means the identical body sent again; it resumes the run from the record. In the Test column, **C** is a controlled test with fakes (fast suite, no network) and **L** is a run against the real providers. Test names are Planned, in product/tests/test\_failures.py unless stated otherwise.

| Trigger | What the caller sees | State left behind | Recovery | Test |
| :---- | :---- | :---- | :---- | :---- |
| Invalid body: wrong offset, sub-seconds, too long | 400 invalid\_request, run: null | Nothing | Fix the field named in the message | C: test\_invalid\_body\_calls\_nothing |
| Missing or wrong API key | 401 unauthorized | Nothing | Use the right key | C: test\_bad\_key\_calls\_nothing |
| Storage unreachable or refused at claim\_run | 503 provider\_unavailable or 502 provider\_error, failed | Nothing, or possibly a record with nothing attempted | Same request later. A leftover record is resumed | C: test\_claim\_fails |
| Same request while another holds the lease | 409 run\_in\_progress, Retry-After \= rest of the 120-second lease | Unchanged | Same request after the delay | C: test\_live\_lease\_returns\_409 |
| Record write before a partner call took more than 20 seconds | 503 provider\_unavailable, retryable: true, partial or failed | Step not\_applied (or still attempting if that write also failed); partner not called | Same request. Tracker: search finds nothing, so create. Calendar still attempting: the unknown row below | C: test\_slow\_record\_write\_skips\_partner |
| Same request after completion | 200, replayed: true | Unchanged | Nothing | C \+ L: test\_replay\_writes\_nothing |
| Tracker refuses (ACCESS\_DENIED, not configured) | 403 or 503, not retryable, failed | Record only; issue step not\_applied | Operator fixes the Trello credentials or list, then same request | C: test\_tracker\_refuses |
| Tracker response lost (PROVIDER\_ERROR, may have applied) | 502 provider\_error, retryable: true, partial | Record says unknown; the card may exist | Same request: recovery searches the newest 100 cards for \[\<run\_id\>\] and adopts or creates | C: test\_tracker\_lost\_response\_adopts\_card |
| Calendar refuses (ACCESS\_DENIED) | 403, not retryable, partial | Issue exists. No event | Operator fixes the calendar permission, then same request. Only the event and later steps run | C: test\_calendar\_refuses |
| Calendar authorization expired | 503 provider\_unavailable, not retryable, partial | Issue exists. No event | Operator re-authorizes and replaces the token secret (4.4), then same request | C: test\_calendar\_auth\_expired; L: manual, before each grading window |
| Calendar temporarily unavailable (retryable) | 503, retryable: true, partial | Issue exists. No event | Same request later | C: test\_calendar\_unavailable\_then\_resume; L: deployed fake-failing calendar (3.3) |
| Calendar outcome unknown (socket timeout after 30 s, lost response) | 502 provider\_error, may\_have\_applied: true, not retryable, partial | Issue exists. The event may exist with no known ID | Operator checks the test calendar for the marker title and runs resolve\_run.py. Until then, same request returns 409 outcome\_unknown | C: test\_calendar\_unknown\_blocks\_until\_resolved, test\_calendar\_timeout\_is\_unknown; test\_config.py checks the socket timeout is set and the 90 s bound stays under the lease |
| The process stops during a partner call (crash, redeploy) | The first caller gets no response or a connection error | Record says attempting for that step | Same request after the lease: tracker recovery searches for the marker; calendar becomes outcome\_unknown, never a second create | C: test\_expired\_attempting\_calendar\_is\_unknown |
| Record write fails between steps | The storage code, partial, step named | The previous step's write exists, but the record may still say attempting | Same request: tracker recovery adopts the card. For the calendar, the unknown row above | C: test\_record\_write\_fails\_after\_issue, ...\_after\_event |
| Agenda write fails | Storage code, retryable: true, partial | Issue and event exist. No agenda, or possibly the agenda | Same request: only the agenda and finish run (walkthrough A in 3.2) | C: test\_agenda\_fails\_then\_resume; L: test\_live.py |
| Finish fails after the agenda exists | Storage code, retryable: true, partial | Everything except the completed mark | Same request: finishes | C: test\_finish\_fails\_then\_resume |
| Record unreadable, for a different request, or removed mid-run | 409 run\_record\_invalid | Unchanged | Operator inspects /review-runs/\<run\_id\>.json through our storage API | C: test\_record\_invalid |
| Two identical requests within one round trip (create race) | Both may claim the run | Possibly two issues and two events | Prevented by one worker and a per-run lock. Accepted limit (2.2) | C: test\_per\_run\_lock\_serializes |
| Someone deletes the event or card after completion | 200 replayed (the record is trusted) | The deleted item stays deleted | Not detected in Milestone 1\. Replay does not re-check providers (open question 5\) | None (accepted) |
| Bad configuration, unknown registry name, or an implementation that cannot be built | Service does not start | No service. One log line names the variable | Fix the variable. The deploy's smoke check fails first | C: test\_config.py |
| A bug | 500 internal\_error | Whatever ran before it, as the record says | Report it. The log has the traceback | C: test\_unexpected\_exception |

**Logs.** Each failed request writes one JSON line: event: review\_meeting\_failed, run\_id, step, our code, the provider's original code, may\_have\_applied, and the steps' states. These are the same fields as our HW1 failure logs ([API.md, Failure logs](https://github.com/FaizalJnu/OSPSD-TEAM-6/blob/07f3168/docs/API.md#failure-logs)).

**Rollback limits.** Redeploying an earlier release does not remove issues, events or documents a faulty release created. Cleanup uses the record to find them (4.3).

## **3.2 Partial failures, worked through**

**A. The event is created, but saving the agenda fails. The caller retries.**

1. First request: steps 1 to 3 succeed. The record holds the issue ID and the event ID, with write\_agenda: attempting.

2. The agenda create fails with ProviderUnavailableError. The orchestrator tries once to record write\_agenda: unknown. The caller receives 503 provider\_unavailable, step: write\_agenda, retryable: true, may\_have\_applied: true, run.status: partial, with the issue and event IDs and agenda: null.

3. The caller sends the same body. The run ID is the same, so the claim gets ConflictError, and the orchestrator downloads the record. write\_agenda takes no lease, so there is no 409\.

4. create\_issue and create\_event are done, so they are skipped. Trello and Google receive no call, and **no second issue or event is created**.

5. The agenda is rendered again from the record, with the same bytes. If the first attempt's write had landed, create raises ConflictError and the orchestrator replaces it with identical bytes. Either way, one agenda exists.

6. finish\_run marks the record completed, and the response is 201 with the same issue and event IDs.

The first response never claimed the agenda existed. completed appears only after step 6 succeeds (invariant 6).

**B. The issue is created, but the calendar step fails.** The handout's "second step succeeds, third fails" case.

* A **refusal or retryable outage** leaves the issue and no event. The caller sees 403 or 503 with step: create\_event and the issue ID. The same request later skips the tracker and creates only the event, then the agenda.

* A **lost response** leaves an event that may exist with no known ID. The caller sees 502 with may\_have\_applied: true. We do not retry it, because a second create could book the meeting twice, and the contract cannot search for the first. The run returns 409 outcome\_unknown until an operator resolves it, then continues with the agenda. This is the one case where Milestone 1 needs a person (2.3).

## **3.3 Verification**

Success is defined by provider records and documented API results, not by a 2xx alone.

| What | Controlled checks (fakes, fast suite, CI) | Real providers (deployed staging, test accounts) | Observable success |
| :---- | :---- | :---- | :---- |
| The composed workflow | Full run on the three fakes; each fake records the calls it received and the run's record is checked step by step | POST to staging, then confirm in each provider. A Trello card with the marker title is on the test list; the test calendar has an event at the same instants; the agenda object in the OCI bucket downloads with the expected bytes. Then resend for the replay | 201 whose IDs match the provider records; replay returns 200 replayed: true and the Trello list and calendar are unchanged |
| Swapping an implementation through configuration | test\_config.py: each registry name builds its implementation; switching CALENDAR\_PROVIDER changes the calendar used and nothing else | Redeploy staging with the **same image digest**, changing only CALENDAR\_PROVIDER from team5-google to the alternate calendar implementation (open question 11\) and that implementation's credentials. Rerun the workflow | Two successful runs with one digest and two configurations; the second event appears in the alternate implementation's calendar; the commit has no code change between runs |
| Failure reporting | Every row of 3.1, injected at each step through the fakes, then the same request sent again | Deploy staging with CALENDAR\_PROVIDER=fake-failing (raises retryable PROVIDER\_UNAVAILABLE), send a request, then switch back to team5-google and resend it | First response is 503 provider\_unavailable, step: create\_event, run.status: partial, with the issue ID, and the Trello card exists. The resend completes with the **same** issue ID and no second card |
| Contract adherence of the fakes | The fakes pass the contracts' own conformance helpers where they exist (calendar\_contract.conformance) | n/a | Fakes behave like the contract, so controlled results transfer |

Other layers in the fast suite: pure units (run ID normalization across offsets, slug and paths, agenda bytes, record state machine), adapter translation (every row of 1.5's table) and the import boundary (2.4). Real-provider tests are marked @pytest.mark.provider (product/tests/test\_live.py: one full run and one resume after an injected calendar failure) and recorded in TESTING.md. The fast suite stays free of network access and credentials, as AGENTS.md requires.

# **4\. Deployment and operations**

Owner: Debasmith Mandal, who owns the storage service's infrastructure (HW2 design, Section 10). The operation reuses that host, pipeline and telemetry instead of adding new ones.

**Status.** The storage service's dev branch is deployed on the Oracle Cloud VM below through a CI/CD pipeline (Reported by the team, November 18). The last Observed state in the HW2 design (November 11\) was a manual deploy. At commit 07f3168 the repository holds only .github/workflows/ci.yml (lint, format, type check and fast tests). There is no Dockerfile, infra/ folder or deploy workflow yet (Observed), so the storage column below follows the HW2 design's Section 10\. Debasmith confirms each row against what is running (open question 3).

## **4.1 Where it runs**

| Item | Storage service (HW2 Section 10\) | Review meeting service (this design) |
| :---- | :---- | :---- |
| Host | Oracle Cloud Always Free Ampere (ARM64) VM in Amsterdam, shared with other personal services (Observed) | Same VM, with its own container memory limit |
| Runtime | Docker container published by Traefik with TLS | A second container, team6-review-meetings, on the same Docker network, routed by Traefik labels |
| Endpoint | [https\://ds.packapunch.xyz](https://ds.packapunch.xyz) (demo); ds-staging.packapunch.xyz (staging) | Proposed: meetings.packapunch.xyz (demo) and meetings-staging.packapunch.xyz (staging). Both fall under the existing wildcard DNS record and certificate, so no new DNS or certificate work |
| Artifact | Multi-stage Dockerfile; uv sync \--locked; non-root; linux/arm64; pushed to GitHub Container Registry, tagged with the commit SHA and pinned by digest (Planned) | product/Dockerfile with the same rules, on a Python 3.14 base image (Team 5's requirement). It installs the storage\_service package from the same commit |
| Infrastructure as code | OpenTofu in infra/: Docker provider (container, network, Traefik labels) and OCI provider (bucket); state in a versioned private OCI bucket; staging and demo workspaces (Planned) | The same infra/: one more container and one more OCI bucket per workspace |
| Release identity | Commit SHA as an image label and a RELEASE variable | The same. GET /health returns the commit |
| Health | GET /health and GET /health/provider are proposed in PR \#98 (open); dev does not serve them yet | GET /health for the Docker health check and Traefik; GET /health/providers for the smoke check and dashboard only, so a partner outage shows as not ready instead of a restart loop |

The storage step does **not** call ds.packapunch.xyz. It runs the storage\_service package in-process against its own bucket (2.1). Redeploying or losing the storage container does not affect this operation. A bug in storage\_service ships in both.

## **4.2 Pipeline**

The same triggers as the storage service (HW2 Section 10.4):

| Trigger | Checks and actions for product/ |
| :---- | :---- |
| Every pull request that touches product/ | Ruff, format check, strict mypy and the fast tests on Python 3.14, including the import-boundary test. tofu fmt, validate and plan when infra/ changes. No deployment credentials |
| Merge to dev | Build the image once, natively for ARM on the self-hosted runner, and tag it with the commit SHA. Deploy to staging and run the smoke check (4.3) |
| Release tag on main | Deploy the digest already built for that commit to demo and run the smoke check. Mark the release successful only if it passes |

* Both services' deploys share one concurrency group and queue rather than cancel, so the shared host never runs two deploys at once.

* **Runner:** the self-hosted runner on the Amsterdam VM from HW2 Section 10.4, under its own user, with no inbound SSH.

* **Configuration-only redeploy:** a manually started run can apply an existing digest with changed configuration. The swap and controlled-failure checks in 3.3 use this, so they never rebuild the image.

* **Rollback:** a manually started run applies the previous known-good digest and repeats the smoke check. It restores code and configuration, not issues, events or documents (3.1, Rollback limits).

## **4.3 Post-deploy smoke check**

After each deploy, against the staging or demo URL, the pipeline:

1. checks that GET /health reports the expected commit;

2. sends one fixed request with a unique title (smoke \<commit\> \<timestamp\>) and a start 300 days ahead;

3. verifies the effects, not just the status: downloads the agenda and compares the bytes, get\_issue(fresh=True) returns the marked title, and calendar get returns the same instants;

4. sends the same request again and expects 200 replayed with the same IDs;

5. cleans up through the packages directly (deletes the event, the issue, the agenda and the record) and lists anything it could not delete.

The deploy counts as successful only when steps 1 to 4 pass. This follows the storage service's planned smoke check (HW2 Section 10.4), which also verifies effects and removes its own data.

## **4.4 Test accounts and credentials**

| Provider | One test account | Settings (values never in the repository) |
| :---- | :---- | :---- |
| OCI Object Storage | One bucket per workspace, used only by this operation, created by OpenTofu's OCI provider. It is separate from the storage service's data bucket and its provider-test bucket | S3\_ENDPOINT, S3\_REGION, S3\_BUCKET, S3\_ACCESS\_KEY, S3\_SECRET\_KEY (existing names, see .env.example) |
| Trello | One board with one list, under a team test user that has access to nothing else | TRELLO\_API\_KEY, TRELLO\_TOKEN, TRELLO\_LIST\_ID (names per Team 4's package, to be confirmed) |
| Google Calendar | A dedicated Google test account. Team 5's package uses **our own** Google Cloud project and Desktop OAuth client, so we add the account as a test user and authorize it once with python \-m team5\_calendar.authorize | CALENDAR\_TOKEN\_FILE: path to the token file inside the container |
| Alternate calendar (swap check) | Its own test account, per that implementation's setup | Per that package (open question 11\) |
| This service |  | PRODUCT\_API\_KEY, STORAGE\_PROVIDER, TRACKER\_PROVIDER, CALENDAR\_PROVIDER |

**How the values reach the container.** This follows HW2 Section 10.3:

* Values are CI environment secrets, separate for staging and demo, passed to the container at apply time.

* OpenTofu's Docker provider records container environment in its state, so the state stays in the private state bucket, never in the repository or CI artifacts.

* The Google token is a file. The deploy writes it into a host directory owned by the container's user, mode 0600, and mounts that directory into the container **read-only**. Team 5's create\_calendar\_service(token\_file=...) refreshes the access token in memory and never writes the file, so the file needs to hold only a valid refresh token (Team 5 review, 6.2 T5-3).

* .env.example gains the new names without values.

* Startup errors name a missing variable, never its value, as the storage service's ConfigError does.

**Rotation.** Update the CI secret and run a configuration-only redeploy (4.2). No source change.

**Google token renewal.** While our OAuth app is in Testing mode, its refresh tokens last 7 days. Renew within the 7 days before every demo and grading window (Team 5 review, 6.2 T5-5):

1. On a workstation, delete the old token file. python \-m team5\_calendar.authorize refuses to overwrite an existing token.

2. Run python \-m team5\_calendar.authorize and sign in as the Google test account.

3. Replace the token CI secret with the new file's contents, run a configuration-only redeploy, and confirm that the smoke check's calendar create passes.

## **4.5 Observability (Planned, reusing HW2 Section 10.5)**

* **Traces:** OpenTelemetry's FastAPI instrumentation for the server span, one child span per step (review\_meeting.claim\_run, .create\_issue, .create\_event, .write\_agenda, .finish\_run), and botocore instrumentation for the S3 calls. run\_id is a span attribute, so one run can be followed across a resume.

* **Metrics:** request count, outcome by error code, the failed step, and a latency histogram per step. Labels are limited to operation (review\_meeting), step, outcome, status class, release and the configured implementation per vertical. Never run\_id, titles, agenda text or paths.

* **Logs:** one JSON line per request in the storage service's format: release, trace\_id, run\_id, outcome, duration\_ms and the step states. A failure adds the fields in 3.1.

* **Dashboard and alert:** the storage service's Grafana stack on the Mumbai OCI VM, reached over the existing WireGuard tunnel. One panel counts runs stuck at outcome\_unknown. The alert fires on any provider\_unavailable at create\_event, the expected sign of an expired Google token. It goes to the team Slack channel or email, with a link to the renewal steps.

* **Telemetry failure:** exports are asynchronous with bounded queues and drop data when full. A telemetry outage never fails or slows a run.

## **4.6 Provider calls per run (Estimate)**

From our S3 code: a create on a new path is HeadObject (404), HeadBucket (because a HEAD 404 could mean a missing bucket, [storage/s3.py:104-121](https://github.com/FaizalJnu/OSPSD-TEAM-6/blob/07f3168/src/storage_service/storage/s3.py#L104-L121)), PutObject and a HeadObject readback, so 4 S3 requests. A replace of an existing path is HeadObject, PutObject and HeadObject, so 3\.

| Path | S3 requests | Trello | Google Calendar |
| :---- | :---- | :---- | :---- |
| New run | About 17: claim (4), three record replaces (9), agenda (4) | 1 create | 1 create |
| Same request after completion | 2: the refused claim's HeadObject, then one GetObject for the record | 0 | 0 |
| Resume after a lost tracker response | The new-run figures for the remaining steps, plus 1 download | 1 list, then 0 or 1 create | 1 create |
| Smoke check | One new run, one replay, plus verification and cleanup | 1 get, 1 delete | 1 get, 1 delete |

The S3 client's standard retry mode can turn any one request into up to four attempts. Latency is unmeasured. The first live run records it per step, and a latency objective waits until there is a week of data, as for Download in HW2 Section 10.6.

## **4.7 Risks and limits**

* **Shared host:** other services run on the same VM. Each container has a memory limit.

* **Partner credentials on our host:** the Trello token can act as the test user everywhere that user can reach. That user has only the test board.

* **Runner risk:** HW2 accepted the self-hosted runner's risk that anyone who can merge to dev can run code on the host. This service widens it to the Trello and Google tokens. The repository is private and limited to the five team members.

* **API key:** PRODUCT\_API\_KEY is one shared secret. It protects the test accounts from anyone who finds the URL (the storage service has no caller authentication, HW2 Section 10.7). Rotate it by updating the CI secret.

* **Fakes in a deployed build:** fake and fake-failing are registered in every image so that 3.3 needs no rebuild. Only staging's configuration ever names them; the smoke check on demo would fail on a fake because it verifies records in the real providers.

* **Teardown:** at the end of the course, with the storage service. tofu destroy removes the container, its routing and its buckets. By hand: delete the Trello board, revoke the Trello token and the Google OAuth grant, and delete the Google Cloud project.

# **5\. Work plan**

Owners are proposed from each person's HW2 area (HW2 design, Owned work) and stay provisional until the team confirms them. None of the implementation rows has started.

| Work | Owner | Why this owner | Done when |
| :---- | :---- | :---- | :---- |
| This design, its review, and the comment record | Faizal | Wrote the HW2 consolidated design; cross-team contact | Section 6 filled in, substantive comments answered |
| Partner coordination and test accounts: Trello test user and list, Google Cloud project, test account and token; contract gaps filed with reproductions (1.5) | Faizal | Cross-team communication | Each provider's live test passes once; each gap has an issue link |
| product/ project, config, implementation registry, fakes | Faizal | Path mapping and service wiring in HW2 | uv sync \--locked on 3.14; boundary and config tests pass |
| Alternate calendar implementation installed and registered (open question 11\) | Faizal | Cross-team contact | test\_config.py builds it; one live run against it |
| Orchestrator, run record, agenda, resolve\_run.py | Vikram | Built Move, HW2's other partial, non-atomic write | Section 3.1 tests pass on fakes |
| Adapters and error tables (1.5), failure log line | Darsh | Owns the error model and the shared streaming adoption | Translation tests pass |
| Fast tests for 3.1, live provider test, smoke check script | Prateek | Owns the conformance suite and List tests | Section 3.3 controlled checks pass; live run recorded in TESTING.md |
| Dockerfile, infra/ additions, pipeline job, test buckets, telemetry | Debasmith | Owns Team 6's infrastructure (HW2 Section 10\) | A deploy passes 4.3 with a recorded commit and digest |
| Live trace replacing 1.3; swap and controlled-failure evidence (3.3) | Prateek with Debasmith |  | Real IDs, commit and digest in 1.3; both 3.3 runs recorded |

# **6\. Review**

As in the HW2 design, whole-design review and contract-facing review are recorded separately:

| Scope | Reviewer | Where | Status |
| :---- | :---- | :---- | :---- |
| Whole design | Debasmith Mandal (Team 6\) | Pull request that adds this file | Reviewed |
| Integration design and contract-facing parts (sections 1 to 3\) | Dayana (Team 1, Document Storage coordinator) | Same pull request, or a linked comment thread | Requested |
| Integration design, calendar-facing parts | Team 5 (owner of the Calendar implementation we use) | Review comments, recorded in 6.2 | Reviewed; comments answered |
| Integration design, tracker-facing parts | Team 4 (owner of the Issue Tracker implementation we use) | Review comments, recorded in 6.2 | Requested |

## **6.1 Questions for the reviewers**

For Dayana (Team 1):

1. The run record relies on DocumentStorage.create raising ConflictError for an existing path. Is that a guarantee the vertical will keep, and would Team 1's Dropbox implementation work as STORAGE\_PROVIDER without changing the orchestrator?

2. Is the run ID being the request hash the right identity, or would you, as a caller, rather send an explicit key?

3. Does reporting every vertical in the storage vertical's codes (2.4) lose anything you would need as a caller?

4. Is anything in section 3.1 missing a case you would hit?

For Debasmith (Team 6):

1. Do 4.1 and 4.2 match what is running, and can the second container share the storage service's concurrency group and runner?

2. Is a stuck outcome\_unknown run, waiting on an operator, acceptable for Milestone 1, or should the calendar step recover differently?

For Team 4 (Issue Tracker):

1. Recovery after a lost create\_issue response (2.3) searches list\_issues(limit=100) for the \[\<run\_id\>\] marker in the title. Does your Trello implementation return issues newest first and uncached, and keep the title exactly as sent? Any trimming or rewriting would break the marker match.

2. Open question 2: what are the exact setting names for the Trello key, token and list? Does create\_issue raise with may\_have\_applied=False when Trello refuses the request, and True only when the response may have been lost?

3. The lease in 2.2 assumes each Trello network operation times out after 10 seconds and that create\_issue never retries internally. Is that right?

## **6.2 Comment record**

Each substantive comment gets a response here: changed (with the section), accepted as is (with the reason), or deferred (with an owner and a date). Team 5 reviewed the first draft, so the section numbers in their comments (3.6, 8.2) refer to it. Responses give the current sections.

| \# | Reviewer | Comment | Response | Status |
| :---- | :---- | :---- | :---- | :---- |
| T5-1 | Team 5 | Title length (open question 1): the package sets no limit; it only trims spaces. 120 characters plus the marker are fine on Team 5's side. | Accepted. Removed the title-length gap from 1.5 and closed open question 1\. Step 0 already trims the title, so the event's title is the one we send. | Closed |
| T5-2 | Team 5 | Google timeout (open question 6): token refresh times out after 10 s, but the Calendar call uses the Google client's default HTTP settings, which have no timeout. "Under 100 s" is not guaranteed, so a second request could find the lease expired while the first create is still running, then make a second event. Set socket.setdefaulttimeout(...) at startup below the lease, and treat a timeout as outcome\_unknown. The package never retries a create that may have gone through. | Changed (1.5, 2.2, 2.3, 3.1). The service sets socket.setdefaulttimeout(30) at startup. A calendar timeout becomes provider\_error with may\_have\_applied: true, and the run stops at outcome\_unknown. Worst case: 20 s guard \+ 10 s refresh \+ 30 s connect \+ 30 s response \= 90 s, under the 120-second lease. We also state explicitly that a calendar step found attempting after its lease becomes unknown and is never created again automatically. The bound stops an operator from resolving a run while its first create may still be running. | Closed |
| T5-3 | Team 5 | Token saving (open question 7): no. create\_calendar\_service(token\_file=...) refreshes the access token in memory and never writes the file, so it can be mounted read-only. It needs to hold a valid refresh token only. | Changed (1.2, 4.4): the token directory is mounted read-only, and the writable-mount assumption is removed. Closed open question 7\. | Closed |
| T5-4 | Team 5 | arm64 and Python 3.14 (open question 8): the package and its dependencies are pure Python and need 3.14+, so they should install on arm64. Not yet run on arm64; keep it in the smoke test. | Accepted. The smoke check (4.3) makes a real calendar create and get from the arm64 image after every deploy, which is that test. Open question 8 stays open until the first image build passes it. | Open until first deploy (Debasmith) |
| T5-5 | Team 5 | 7-day token (first draft 3.6, now 2.4): correct. Re-run python \-m team5\_calendar.authorize within 7 days before the demo. It refuses to overwrite an existing token, so delete the old file first. | Changed (4.4): renewal procedure written out, including deleting the old file first. | Closed |
| T5-6 | Team 5 | Comment record (first draft 8.2, now 6.2) is empty; the submission needs review comments and responses. | Changed: comments and responses recorded in this table. | Closed |

# **7\. Open questions**

| \# | Question | Owner | Resolve by |
| :---- | :---- | :---- | :---- |
| 1 | Closed (6.2 T5-1): Team 5's package sets no title limit | Faizal, with Team 5 | Done |
| 2 | Team 4's Trello package: exact setting names, and whether create\_issue sets may\_have\_applied=False on refusals | Faizal, with Team 4 | Before implementation |
| 3 | Do 4.1 and 4.2 match the running deployment? Dockerfile, infra/ and the deploy workflow are not in this repository, and the HW2 design last observed a manual deploy (November 11\) | Debasmith | Before review |
| 4 | Does OCI honour a conditional PutObject? It would close the create race (2.2) | Debasmith (HW2 open question 15\) | Milestone 2 |
| 5 | Should replay re-check that the issue and event still exist? | Team | Milestone 2 |
| 6 | Closed (6.2 T5-2): the Calendar call had no timeout; we set socket.setdefaulttimeout(30) at startup (2.2) | Darsh, with Team 5 | Done |
| 7 | Closed (6.2 T5-3): the package never writes the token file, so the mount is read-only (4.4) | Faizal, with Team 5 | Done |
| 8 | Do Team 5's Google client libraries install and run on linux/arm64 with Python 3.14? Team 5 reports pure-Python dependencies but has not run them on arm64 (6.2 T5-4); the first smoke check confirms it | Debasmith | First image build |
| 9 | How graders open the Grafana dashboard without the admin login | Debasmith (HW2 open question I2) | Before Milestone 2 |
| 10 | HW2 open question I1 is answered for this service: dev deploys to staging, release tags deploy to demo (4.2). Confirm the same holds for the storage service | Debasmith and Faizal | Before review |
| 11 | Which second calendar-contract v0.1.0 implementation (Team 2 or Team 7\) we install for the swap check, its tag, its Python requirement and its test-account setup | Faizal, with that team | Before deploy |

# **Revision notes, 2026-11-18**

After Team 5's review (6.2):

* Bounded the Calendar call with socket.setdefaulttimeout(30) and treat a calendar timeout as an unknown outcome (2.2). Stated that an expired lease never creates a second event (2.2, 2.3, 3.1).

* Token file mounted read-only; Google token renewal procedure added (4.4).

* Closed open questions 1, 6 and 7; open question 8 waits for the first image build.

* Reviewers: Team 5 (Calendar) reviewed; Team 4 (Issue Tracker) review requested, with questions in 6.1.

Changes from the first draft, for reviewers who read it:

* Reorganized around the handout's three questions (sections 1 to 3). Reduced the decisions to three (2.1 to 2.3). Validation, error translation and calendar readiness moved to 2.4, Boundaries.

* Added: Milestone 1 status table, usage example (1.4), contract gaps with owners (1.5), fixed steps versus later judgment (1.7), a test for each failure (3.1), worked partial failures (3.2), and verification of the workflow, the swap and failure reporting (3.3).

* Implementation selection is now by registry name. The earlier module:attr setting could not pass implementation-specific constructor arguments without code changes.

* Corrected: S3 retries allow up to four attempts, not three. A create on a new path costs 4 S3 requests, not 3, so a new run costs about 17\. The storage service's health routes are in open PR \#98, not deployed. Fixed the HW2 design link. Pinned the API.md links to a commit.

* The lease now covers only the partner writes (create\_issue, create\_event). A step skipped by the 20-second guard is recorded as not\_applied.

* Section 6 (the Team 1 review questions) is unchanged apart from updated section numbers.

