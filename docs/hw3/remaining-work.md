# HW3: what is left for Milestones 2 and 3, and who does it

Team 6, as of Sunday 2026-11-22. Everything below comes from the handout (`docs/hw3/HW3.md`),
our Milestone 1 design (`docs/hw3/design.md`), and the repository and GitHub state on that date.
**Every decision is made and every row has one owner.** Nothing in this file waits on a vote or
on Faizal. Copy each row into a GitHub issue with its owner and due date. The working rules below
say who decides anything that comes up later.

**Target: all Milestone 2 work done, released, and submitted by Wednesday Nov 25 at 4:30 pm.** The course
deadline is still Wed Dec 2. Nov 26 to Dec 1 is buffer for anything that slips, not planned work.
Every Milestone 2 row below has a **Due** date. "EOD" means 11 pm that day, **except Wednesday Nov 25, when EOD means 4:30 pm**: the release is cut and the submission is in by then.

## Where we stand

| Item | State |
|---|---|
| Milestone 1 design (`design.md`) | Written. Reviewed by Debasmith and Team 5, and Team 5's comments are answered. Team 4 and Dayana have been asked to review but have not responded. |
| Milestone 1 operation `POST /v1/review-meetings` | **Not built.** There is no `product/` directory, no Dockerfile, no `infra/`, and no deploy workflow in the repository. Milestone 2 builds on it, so it comes first below. |
| Product (Milestone 2 Level 1) | Not chosen. No brief, discovery notes, or assumption tests. |
| Tracker | No GitHub milestones or project board for HW3. |
| Storage service | v0.2.0 is merged to `main`. The version-bump PRs #105 and #106 are open, the tag must be recreated, and there is no GitHub Release yet. |

## Deadlines

| Date | What happens | Can it move? |
|---|---|---|
| **Wed Nov 25, 4:30 pm** | **Our target:** Milestone 2 complete, GitHub Release cut, Brightspace submission in. | Our choice. Slipped rows use the buffer. |
| Nov 26 to Dec 1 | Buffer: finish slipped rows, second visit for the outside user check, more evaluation runs, more Google test users, launch post and recording. | |
| **Wed Dec 2** | Milestone 2 course deadline, before class. Launch week starts, and other teams begin using our product **whether or not it is ready**. | We can take up to 2 slack days, but they come out of our own launch week. Not recommended. |
| Dec 2 to Dec 6 | Launch week: we use two other teams' products and they use ours. | No |
| **Wed Dec 9** | Milestone 3 and Demo Day (3-minute presentation and live demo). | Demo Day cannot move. The final release and retrospective can move to Dec 16 if we ask staff for an extension. |

That leaves **3 working days** (Mon to Wed) to build Milestone 1 and all of Milestone 2, so most rows run in parallel from Monday morning.

## Schedule (checkpoints)

The handout says to get one scenario working end to end before widening scope. Each checkpoint is a
working path, not a set of finished parts. If a checkpoint is missed, say so in the team channel
the same day and use the cut list below rather than pushing every later row back.

| By | Checkpoint |
|---|---|
| **Sun Nov 22 (tonight)** | Team call: share the decisions and owners below; each person starts on their rows. Create the GitHub milestones, board, and issues with due dates. Send the per-user credential questions to Teams 4 and 5. Storage v0.2.0 released. |
| **Mon Nov 23 noon** | `product/` scaffold merged, so everyone builds on it. Database provisioned. |
| **Mon Nov 23 EOD** | Product brief draft, discovery notes, `DESIGN.md` extension (with threat model) reviewed by the team. Fixed workflow passes on fakes. Agent loop runs with the scripted model. Dockerfile and pipeline build an image. Test accounts work. |
| **Tue Nov 24 noon** | The fixed workflow is deployed and runs against the real Trello, Google Calendar, and OCI accounts (Milestone 1), with swap and controlled-failure evidence. |
| **Tue Nov 24 EOD** | Interface runs the fixed scenario through the API, and the usability check is done. Sign-in, provider connections, isolation, API operations, tools, proposals and approvals all work on staging with the scripted model. Deterministic tests in CI. Dashboard up. Brief final, assumption tests recorded. |
| **Wed Nov 25 10 am** | Full key scenario on staging: real model, approval, real providers, two signed-in users kept apart. All interface screens work. |
| **Wed Nov 25 4:30 pm** | Evaluations (5 real-model runs per scenario, adversarial cases, one measured improvement), security tests, load test, kill switch, alert test, game day and backup restore, readiness record and launch decision. **GitHub Release cut and Milestone 2 submitted on Brightspace.** |
| Nov 26 to Dec 1 | Buffer only (see Deadlines). Launch post and recording ready by Tue Dec 1. |
| Wed Dec 2 | Course deadline for Milestone 2. Launch post in Slack; launch week starts. |
| Dec 2 to 6 | Watch telemetry, triage incoming `launch-feedback` issues every day, use the two products assigned to us. |
| Sun Dec 7 to Tue Dec 8 | Fixes, a disposition on every feedback issue, traction report, retrospective, final release, Demo Day rehearsal. |

## Decisions (made Sun Nov 22 by Faizal)

These are final for Milestone 2. Work starts on them Monday morning.

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Product and user | **Meeting prep agent** for student project leads who run a weekly or sprint review | Reuses the Milestone 1 review-meeting workflow (tracker issue, calendar event, agenda document) almost unchanged. |
| 2 | Key scenarios | **(1) Prepare a review meeting**: read open issues, find or book the event, save the agenda document, link it on the event and a tracker issue (all three verticals; the must-have). **(2) Post-meeting follow-ups**: from the saved agenda's notes, propose issues for action items and save a summary. **(3) What's on for my next review**: read-only summary of the next meeting, its agenda, and open issues. | If time runs short, cut 2 first, then 3. Scenario 1 never gets cut. |
| 3 | Brief format | **PRD one-pager** | Its sections match the handout's required brief sections one to one, so it is the fastest format to write. |
| 4 | Interface | **Python web app**: FastAPI with server-rendered pages (Jinja and HTMX) in its own directory | Google sign-in and provider connections run in the browser, other teams can open it from a link, and a Python client needs no OpenAPI code generation. |
| 5 | Sign-in and sessions | **Continue with Google** (OpenID Connect through Authlib), server-side session in a Secure, HttpOnly, SameSite cookie, CSRF tokens on forms | Uses the Google Cloud project we already need for Calendar. |
| 6 | Model | **Groq free tier** behind our own model interface, with a scripted fake model for tests | Fast, with tool calling. Its per-minute token limits are tight: cache responses in development, use the scripted model in CI and for most of the load test. Vikram picks the exact Groq model and records its limits by Mon 23 noon. |
| 7 | Agent loop | **Our own small loop**: model interface (real and scripted), tool registry, argument validation, limits on steps, time, and tokens, stop reasons | Easiest to explain and to test deterministically, which the handout grades. |
| 8 | Database | **Postgres on Neon**, SQLite for local development and tests | Managed and free, with point-in-time restore for the Level 5 backup drill. |
| 9 | Hosting | **The existing OCI VM** behind Traefik with wildcard TLS (design §4), new containers under `meetings.packapunch.xyz` | No new accounts, and Debasmith already runs it. |
| 10 | Storage isolation | **One key prefix per user**: the API service puts every key under `users/<internal user ID>/` and rejects any path outside it | Users do not connect a storage account. Tested with User A against User B. |
| 11 | Trello per user | **Pull request to Team 4.** Their `TrelloIssueProvider` takes no constructor arguments and reads `TRELLO_API_KEY` and `TRELLO_TOKEN` from the environment on every request (tag `team-4-issue-tracker-trello-v1.0.0`), so it cannot act for more than one user. We file the gap as an issue with a reproduction, open a pull request that adds optional key and token arguments (the environment stays the default), and pin their new tag. | Keeps us on Team 4 and fixes the gap where it belongs. Until it is tagged, we install from our pull request's commit. |
| 12 | Calendar per user | **Pull request to Team 5, plus a temporary file in the meantime.** Their package builds a client from `create_calendar_service(token_file=...)`. We open a pull request that adds a credentials argument. Until it is tagged, we decrypt the user's token into a per-request temporary file (mode 0600, on tmpfs) and delete it after the call. | Per-user access without waiting on Team 5. The temporary file is recorded as a known limitation until their tag lands. |
| 13 | Google OAuth app | **Stay in Testing mode**, and add staff and launch-week users as test users (up to 100) | Google's verification takes longer than we have. Refresh tokens expire after 7 days, so the getting-started page explains reconnecting. |

## Working rules (so nobody waits on anyone)

1. **The owner of a row decides everything inside it.** That covers libraries, internal design,
   numbers such as SLO targets, hostnames, and the exact Groq model, within the Decisions table
   and the handout. Write the choice in the PR description and, if it affects other rows, in
   `DESIGN.md`.
2. **The service that serves an endpoint owns its shape.** The API service belongs to Darsh, the
   agent service to Vikram, and sign-in and provider connections to Darsh and Faizal
   respectively. Each owner publishes their request and response shapes (the FastAPI OpenAPI page
   is enough) by **Tue 24 noon**. Callers code against what is published and open an issue on
   the owner's row if something is missing.
3. **Each table belongs to the row that creates it** (see the rows in D and E). Change another
   person's table only through a migration they review.
4. **External contacts are handled by the row owner directly**, with no relay through Faizal:
   * Faizal: Teams 4 and 5 (per-user credential issues and pull requests), the Team 4 and Dayana
     design reviews, the outside sign-up check, course staff for test-user emails.
   * Debasmith: anyone needed for the OCI VM, Neon, or DNS.
   * Everyone: their own discovery conversation; their own launch-feedback issues on other teams'
     products.
5. **Slipping rows trigger the cut list automatically.** The owner posts in the team channel the
   same day, and the next item on the cut list is dropped without a meeting. Faizal updates the
   brief, design, and readiness record to match.
6. **Reviews:** every PR needs one approving review from any teammate. Reviewers check the row's
   "done when". A review is not a place to reopen a decision in the Decisions table.

## Work for Milestone 2 (target Wed Nov 25; course deadline Wed Dec 2)

### A. Finish Milestone 1: the fixed workflow, deployed

| Work | Owner | Due | Done when |
|---|---|---|---|
| `product/` uv project, configuration, implementation registry, fakes (design §1.1); database access layer and migration tool set up so others add tables through migrations | Faizal | **Mon 23 noon** | `uv sync --locked` passes, the config and import-boundary tests pass in CI, and an empty migration runs on SQLite and Postgres |
| Orchestrator, run record, agenda (design §2.2, §2.3) | Vikram | **Mon 23 EOD** | The design §3.1 failure tests pass on fakes |
| Adapters for the three verticals and their error tables; failure log line (design §1.5, §2.4) | Darsh | **Mon 23 EOD** | The translation tests pass |
| Fast tests for design §3.1, live provider test, smoke-check script | Prateek | **Tue 24 noon** | The design §3.3 controlled checks pass, and a live run is recorded |
| Dockerfile, deploy pipeline, hostnames, test buckets (design §4) | Debasmith | **Mon 23 EOD (first deploy Tue 24 noon)** | A deploy passes the smoke check in design §4.3 with a recorded commit |
| Test accounts (Trello board, Google test account, token); answers from Team 4 (open question 2); second calendar implementation for the swap check (open question 11) | Faizal | **Mon 23 EOD** | Each provider's live test passes once |
| Per-user credential gaps: issue with a reproduction and a pull request to Team 4 (key and token as constructor arguments) and to Team 5 (credentials argument); pin their new tags when released | Faizal | **Mon 23 EOD** (pull requests opened) | Both issues and pull requests are linked from `DESIGN.md` §1.5; our code runs against the pull request commits until tags land |
| Live trace in design §1.3; swap and controlled-failure evidence | Prateek with Debasmith | **Tue 24 noon** | Real IDs and the commit are recorded |

### B. Level 1: define the product

| Work | Owner | Due | Done when |
|---|---|---|---|
| Product brief, 2 to 4 pages: problem, user, evidence, key scenarios, must/should/won't, success metrics, assumptions, open questions | Faizal (everyone reviews) | **Draft Mon 23 EOD, final Tue 24 EOD** | Merged and linked from the submission |
| Discovery notes: the team's own discussion, plus conversations with people outside the team, quoted | Each of the five members writes notes from one conversation by Mon 23 EOD; Faizal merges them and records the team discussion | **Mon 23 EOD** | Notes linked from the brief |
| 1 or 2 riskiest-assumption tests, for example "does a retried Trello or Calendar create make a duplicate?" or "do users want proposals rather than automatic actions?" | Vikram (technical), Faizal (product) | **Tue 24 EOD** | Assumption, test, result, and the decision it led to are recorded in the brief |
| GitHub milestones (M2, M3), project board, one issue per outcome with an owner, scenario link, and completion check | Faizal | **Sun 22 EOD** | The board shows who is doing what, what is blocked, and what is ready to start |
| Extend `DESIGN.md`: interface, agent service, stateless API, database, model access, and the identity → approval → execution → verification trace for one scenario; code versus model decisions; threat model (Level 4) | Faizal, with a section from each owner | **Mon 23 EOD (team review the same evening)** | The team has reviewed it before implementation, and the decisions are recorded |
| Send `DESIGN.md` to the Team 4 and Dayana reviewers, and record their comments | Faizal | **Sent Mon 23; comments recorded by Wed 25 EOD** | Design §6.2 has their comments and our responses |

### C. Level 2: interface

| Work | Owner | Due | Done when |
|---|---|---|---|
| Interface in its own directory with its own tests in CI. It calls only our API, shows the progress of each step, and turns every error code into a message that tells the user what to do next. | Prateek | **Tue 24 EOD** | A person runs the fixed scenario through it |
| Interface screens for later levels: chat with the agent, proposal review with approve and reject, sign-in and sign-out, provider connections (connected account, needs attention, connect, disconnect) | Prateek, against endpoints from Vikram (agent) and Darsh, Faizal (sign-in, connections) | **Wed 25 10 am** | Each screen works against the deployed staging services |
| Usability check: a teammate who did not build the interface runs the scenario from the getting-started page with no help, and we record where they get stuck. Also show one failing step. | Darsh runs it, Prateek fixes what it finds | **Tue 24 EOD** | Notes and fixes recorded |
| Getting-started page | Prateek, then Faizal edits | **Wed 25 10 am** | Someone outside the team can follow it |

### D. Level 3: agent service (a separate service)

| Work | Owner | Due | Done when |
|---|---|---|---|
| API service operations that the agent's tools call: per-user reads (open issues, upcoming events, stored documents) and one endpoint that executes an approved change set and returns each action's outcome (succeeded, failed, uncertain) | Darsh | **Tue 24 EOD** | Each operation has HTTP tests on fakes, and the execute endpoint refuses a change set without a matching approval |
| Model interface with a real and a scripted implementation; the agent loop with limits on steps, time, and tokens; cancellation | Vikram | **Mon 23 EOD** | The loop runs with the scripted model and no web framework |
| Tools for the job: names, argument schemas, structured results, validation before execution, at least one tool that combines several verticals | Vikram | **Tue 24 EOD** | Each tool's preconditions, effects, and failures are documented |
| Proposals and approvals: show the exact changes, store approval against that exact proposal, require new approval when a proposal changes, check approval at the execution boundary in the API on every path including retries | Vikram (agent side), Darsh (API enforcement) | **Tue 24 EOD** | The deterministic tests below pass |
| Saved in the database: conversations, proposals, approvals, outcomes (tables and migrations for these are Vikram's). A restart keeps a pending approval and does not replay completed writes. | Vikram; Debasmith hosts the database | **Tue 24 EOD** | The restart test passes |
| Execution records: tool calls, policy decisions, timing, stopping reason, with secrets removed | Vikram | **Tue 24 EOD** | A failed run can be explained from its record |
| Deterministic tests: malformed arguments, unknown tool, clarification, provider error, exhausted limits, cancellation, restart, unapproved write, another user's ID | Prateek | **Tue 24 EOD (new cases through Wed 25 10 am)** | They pass in CI with no live model |
| Task evaluations: five real-model runs per scenario (success count, time, cost, model version); adversarial instruction planted in an issue or document, with a legitimate request as a control | Prateek | **Wed 25 EOD** | Results recorded and linked from the submission |
| One measured improvement: pick a failure trace from the evaluations, change the tool, prompt, context, or loop, and rerun with new wording | Vikram makes the change, Prateek reruns and records | **Wed 25 EOD** | Before and after results recorded |

### E. Level 4: authenticate every user

| Work | Owner | Due | Done when |
|---|---|---|---|
| Sign-in, server-side sessions, sign-out, session revocation; the acting user comes from verified credentials only, and the agent service proves which user it acts for when it calls the API; users and sessions tables | Darsh | **Tue 24 EOD** | The credential lifecycle tests pass |
| Provider connections: OAuth with state and PKCE, narrow scopes, tokens encrypted at rest and refreshed, disconnect and reconnect, no fallback to a shared account; connections table; per-user construction of Team 4's and Team 5's clients (Team 5 through the temporary token file until their tag lands) | Faizal (also the contact for Teams 4 and 5) | **Tue 24 EOD** | Two test users each connect all three verticals |
| Isolation: every query, conversation, approval, cache, and progress stream is scoped to the user; per-user storage prefix | Darsh | **Tue 24 EOD** | User A cannot read or act on User B's objects, through the API directly or through the agent |
| Containing the agent: retrieved content is treated as data, tool authority is limited, approval is bound to user and action, permissions are rechecked when work resumes, limits on request size, rate, and model spending | Vikram (agent), Darsh (API) | **Wed 25 10 am** | The adversarial suite below passes |
| Security tests: isolation, missing/invalid/expired/revoked credentials, mismatched OAuth state, restart persistence, token refresh, no secrets in logs or prompts | Prateek | **Wed 25 EOD** | They pass in CI |
| Threat model in `DESIGN.md` (resource, attacker action, rule, enforcing component, test, plus a valid control request) | Darsh | **Mon 23 EOD (with the design)** | Merged into the design |
| Outside check: someone from another team signs up, connects all three verticals, runs a scenario, comes back later, and disconnects a provider, using only the getting-started page | Faizal arranges it | **First visit Wed 25; return visit in the buffer** | Findings fixed |
| Add course staff and launch-week users to the Google OAuth test-user list | Faizal | **Mon 23 EOD** | Staff emails and the known testers are on the list; add launch-week users during the buffer |

### F. Level 5: production readiness

| Work | Owner | Due | Done when |
|---|---|---|---|
| Deploy both new services with HTTPS through the pipeline; versioned configuration, prompts, and migrations; post-deploy smoke check | Debasmith | **Staging Tue 24 EOD; release candidate Wed 25 10 am** | A tagged release candidate is deployed |
| Launch criteria: SLIs and SLOs for each operation (API p50/p95/p99, time to first progress update, task completion time, error rate, correctness), plus a capacity estimate covering the model quota, Trello, Google, and the database | Debasmith, Faizal (estimate) | **Tue 24 EOD** | Written in the readiness record |
| Load test of realistic user journeys, a burst, and a slow or failing dependency | Prateek | **Wed 25 EOD** | Results recorded with workload, sample size, and limitations |
| Failure map (what the user sees for each failure, and how each one recovers) | Debasmith, with Darsh for the error model | **Tue 24 EOD** | Representative cases tested |
| Kill switch that stops new agent runs or risky writes while reads keep working; rollout plan (team, then one sister team, then the class) with criteria to advance or stop | Debasmith | **Wed 25 EOD** | The switch is tested |
| Dashboard (task success, errors, latency, model usage) and one alert that reaches its owner and clears after recovery, linked to a runbook | Debasmith | **Up Tue 24 EOD; alert tested Wed 25** | The alert test is recorded |
| Game day: a teammate who did not write the runbook recovers an injected failure; release rollback; backup restored into a disposable database | Debasmith runs it, Vikram is the responder | **Wed 25 EOD** | Findings and fixes recorded |
| Readiness record and launch decision (ready / ready with restrictions / not ready), with an owner for each remaining risk; on-call rota for launch week | Faizal | **Wed 25 EOD** | Recorded and linked from the submission |

### G. Release and submit (Wed Nov 25)

| Work | Owner | Due | Done when |
|---|---|---|---|
| Finish the storage service v0.2.0 release (PRs #105 and #106, recreate the tag, GitHub Release; issues #104, #69, #73) | Faizal | **Sun 22 EOD** | GitHub Release exists |
| Milestone 2 GitHub Release on the verified commit | Faizal | **Wed 25 EOD** | Release links the deployed product and the readiness record |
| Brightspace submission (Milestone 2): brief, discovery notes, assumption tests, design and review record, tracker, release and commit, deployed URL, getting-started page, tests, evaluations, readiness evidence. Check that staff can open every link and that staff are invited to the tracker and dashboard. | Faizal | **Wed 25 EOD** | Submitted, a week ahead of the Dec 2 deadline |

### Cut first if time runs short

The handout says to launch only what works and to cut a scenario rather than ship it broken. In
order:

1. The second and third key scenarios (keep the one that uses all three verticals).
2. Extra Credit (background agent) and every optional extension.
3. Interface polish.
4. A large load test. Run a small one at our real launch scale instead.

Never cut sign-in, isolation, approval before changes, or the core scenario. The handout says
broken access controls or a failing core journey block launch.

## Work for Milestone 3 (due Dec 9)

| Work | Owner | When | Done when |
|---|---|---|---|
| Launch post in the Slack channel: one paragraph on what it does and who it is for, a short recording or GIF of a key scenario, and the getting-started link | Faizal (text), Prateek (recording) | Dec 2 | Posted |
| Use two other teams' products as a real user; file `launch-feedback` issues in their repositories (under 300 words per product, including what worked) | Darsh and Vikram on product 1; Prateek and Debasmith on product 2 | Dec 2 to 5 | Issues filed and links collected |
| On call during launch week: watch the dashboard and alerts, fix incidents, write a blameless postmortem if something breaks | Debasmith (primary), Vikram (backup) | Dec 2 to 6 | Incidents logged |
| Triage incoming `launch-feedback` issues every day: fixed, planned, or declined with a reason | Faizal triages; the owner of the affected area fixes | Dec 2 to 8 | Every issue has a visible disposition |
| Fixes for the issues that most affect the key scenarios, each verified the same way as the original behavior. Faizal assigns each issue by area: interface to Prateek, agent to Vikram, sign-in, isolation and API operations to Darsh, provider connections and docs to Faizal, deployment and operations to Debasmith | The person who owns that area | Dec 4 to 8 | PRs merged and issues closed |
| Traction report against the brief's success metrics: completions and drop-offs per scenario, approved-change rate, returning users, launch-week success rate compared with the pre-launch evaluation, quotes | Prateek (data), Faizal (write-up) | Dec 7 to 8 | Linked from the submission |
| Retrospective: which assumptions were right or wrong, what users did that we did not expect, what we would change about the plan | Each member adds three points from their own area by Dec 7; Faizal writes it up | Dec 8 | Merged |
| Final GitHub Release and commit | Faizal | Dec 8 | Released, tag not moved afterwards |
| Demo Day: 3 minutes covering the problem, the insight, a live demo, traction, and what is next; rehearse once; every member can answer questions on their own part | Faizal presents the story, Vikram drives the demo, everyone answers questions | Dec 8 rehearsal, Dec 9 | Presented |
| Brightspace submission for Milestone 3: launch post, feedback we filed, feedback we received and its dispositions, fixes, traction report, retrospective, final release | Faizal | Dec 9 before class | Submitted |
| After the course: revoke test-account access, tear down resources, confirm that nothing is still costing money | Debasmith | After Dec 9 | Confirmed |

## Each person's list

**Faizal**: tracker, product brief and assumption tests (product side),
discovery notes, `DESIGN.md` extension and reviews, `product/` scaffold, registry and migration
setup, test accounts, issues and pull requests to Teams 4 and 5 for per-user credentials,
provider connections, Google
test-user list, outside sign-up check, capacity estimate, readiness record, storage v0.2.0
release, Milestone 2 release and submission, launch post, feedback triage, traction write-up,
retrospective, final release, Demo Day story.

**Vikram**: orchestrator and run record, technical assumption test, the whole agent service (model
interface, loop, tools, proposals and approvals, saved state and its tables, execution records,
containment on the agent side), the measured improvement, game-day responder, launch-week backup
on call, feedback for product 1, Demo Day driver.

**Darsh**: adapters and error tables, API operations for the agent's tools, the execute endpoint
and its approval checks, sign-in and sessions, user isolation, containment on the API side,
threat model, interface usability check, feedback for product 1.

**Prateek**: Milestone 1 tests and live trace, interface (all screens) and getting-started page,
deterministic agent tests, real-model evaluations, adversarial and security tests, load test,
launch recording, traction data, feedback for product 2.

**Debasmith**: Dockerfile, pipeline, hosting, HTTPS, database hosting, SLIs and SLOs, failure
map, dashboard and alert, kill switch and rollout plan, game day and backup restore, primary on
call in launch week, feedback for product 2, teardown.

Every member also writes notes from one discovery conversation (by Mon Nov 23), adds three points to
the retrospective (by Dec 7), fixes launch-feedback issues in their own area, and can explain
their own code at Demo Day.

## Risks to raise now

* **Three days for two milestones.** The Milestone 1 operation does not exist yet, and everything in
  Milestone 2 depends on it. Sections A to F all start Monday morning in parallel, on top of the
  scaffold merged at noon. Each owner should flag a slipping row the same day so we cut scope
  (cut list above) instead of missing the Wednesday release.
* **Rows that depend on people outside the team** may not finish by Wednesday: Team 4's and
  Dayana's design reviews, Teams 4 and 5's answers on per-user credentials, and the outside user
  check (whose return visit happens in the buffer). Faizal asks for all of them on Sunday night
  or Monday morning.
* **Google Testing mode.** Each user, including staff and every launch-week tester, must be on the
  test-user list, and refresh tokens last 7 days. Either verify the app or collect testers' emails
  by Mon Nov 23.
* **Partner packages do not support per-user credentials yet.** Confirmed for Team 4's Trello
  provider (it reads one key and token from the environment). Team 5's package needs a token
  file. Decisions 11 and 12 cover both; if Team 4 does not merge in time, we run from our pull
  request's commit and say so in the readiness record.
* **Groq free-tier limits.** Evaluations, the load test, and launch week all use the same per-minute
  and per-day quota.
  Cache responses during development and use the scripted model in CI.
* **Design reviews still outstanding.** Team 4 and Dayana have not replied. Follow up, or name
  another reviewer.
