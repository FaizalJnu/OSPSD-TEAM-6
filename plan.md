# Personal plan: Faizal Rahman, OSPSD

Local only, listed in `.gitignore`. Last updated: 2026-11-18.

Read this with `resume.md`, which holds the exact state of the current work. This file
changes when a duty or decision changes. No credentials or `.env` values go here.

## Goal

Deliver Team 6's part of Milestone 3 by **Nov 11, 2026**. Team 6 is in the Document
Storage vertical with Teams 1 and 3. We can complete everything, so plan the work
rather than questioning whether it fits.

- Team repo: `FaizalJnu/OSPSD-TEAM-6`. One issue per PR, PR into `dev`, squash merge.
- Shared repo: `Dayana20/ospsd26-cloud-storage`.
- Source of truth: `docs/hw2/DESIGN.docx.md`, the consolidated design. Work breakdown
  starts around line 446. `DESIGN_team6.md` is the older team design.
- The design's owners are provisional until the team confirms them.

## HW3 timeline (handout: `docs/hw3/HW3.md`, design: `docs/hw3/design.md`)

- M1 Compose the Services: due 2026-11-18 (passed). Implementation not started as of 11-21.
- M2 Build and Ship (Levels 1-5; Extra Credit optional): due 2026-12-02. Needs a product
  brief, interface, separate agent service, stateless API, persisted database, per-user
  sign-in and provider connections, evals, readiness record, GitHub Release.
- Launch week 2026-12-02 to 12-06 (does not move). M3 Launch and Demo Day: 2026-12-09.
- Slack days: max two per deadline, requested before the original deadline.

## HW3 Milestone 2 decisions (2026-11-22, Faizal)

Full table, owners and due dates: `docs/hw3/remaining-work.md`. Target: all of M2 released
and submitted by Wed 2026-11-25, 4:30 pm; Nov 26 to Dec 1 is buffer.
Meeting prep agent for student project leads; scenarios: prepare a review (must), post-meeting
follow-ups, what's on for my next review. PRD one-pager brief. Python web UI (FastAPI + Jinja/
HTMX). Google OIDC sign-in, server-side cookie session. Groq free tier, own agent loop. Neon
Postgres. Existing OCI VM. Storage isolated by `users/<id>/` prefix. PRs to Team 4 (Trello
key/token constructor args) and Team 5 (credentials arg; temp token file until tagged).

## HW3 Milestone 1: Compose the Services (due 2026-11-18)

Deliver a deployed API operation that uses all three verticals (Storage, Calendar,
Issue Tracker) with fixed steps and one test account, documented in
`docs/hw3/DESIGN.md`, reviewed by another team with comments answered.

Decisions made 2026-11-18 (with Claude):
- Operation: `POST /v1/review-meetings`. Steps: claim run record in storage, Trello
  issue, Google Calendar event, agenda doc, finish record.
- In-process contract packages, not HTTP. New uv project `product/` (Python 3.14,
  needed by Team 5's package), separate from the storage service.
- Partners: Team 4 Trello `team-4-issue-tracker-trello-v1.0.0`; Team 5 calendar
  `team5-calendar-v0.1.0` (uses our own Google Cloud project and OAuth client;
  Testing-mode tokens expire after 7 days). Team 2 needs Python <3.13, so not used.
- Dev deployment on Oracle Cloud was set up by a teammate outside this repo; the
  design leaves its details as TBD.
- Reference: Team 4's HW3 design, `Tyler-Arciniaga/OSPSD-Team-4` `product/docs/DESIGN.md`.

Still to do: fill the TBDs in DESIGN.md 5.1 and 5.3, pick the reviewing team, confirm
owners in section 7, implement `product/`, deploy, replace the planned trace with a
live run.

## HW2 duties (for reference)

| # | Duty | Status | What is left |
|---|---|---|---|
| 1 | Paths and routes: normalize paths, map to keys, `?path=` routes | Done: #79 squash-merged into `dev` on 2026-11-10 | Conformance path tests have not run. Teammates move their own routes on top of it. |
| 2 | Folder delete: `DELETE /files?path=` with `delete_many` | Done: #83 squash-merged into `dev` on 2026-11-10 | Second person's OCI run (Level 2). Over-1000-keys OCI run passed 2026-11-11, record not yet in TESTING.md. |
| 3 | Cross-team communication with other teams and Dayana | Ongoing | Team 1 deploys its own service; our Health is ours. Tell Debasmith the liveness route is `GET /health`. |
| 4 | Consolidated design | Not started | Restore section 8 (open questions), change v0.3.0 to v0.2.0, name the reviewers, record how each comment was handled. |
| 5 | Docs (from the older design) | Delete docs done | README examples, API migration notes, architecture, testing, and provider docs once teammates' routes land. |
| 6 | Release manager (from the older design) | Not started | Follow `CONTRIBUTING.md`: release issue, version bump, `dev` to `main`, provider tests, tag, GitHub release. |

Release notes: the next version is v0.2.0, because `pyproject.toml` is at 0.1.0 on
`dev`. The notes must say that `DELETE` on a folder now deletes its contents. The open
`dev` to `main` PR, #29, had changes requested when last checked.

## What remains (checked 2026-11-11 evening, deadline today)

Merged into `dev` since the morning: #87, #88, #81, #90 (List route), #92 (shared
streaming 0.3.1). `dev` is at 07f3168.

Faizal's items:
1. #90 merged. README route table and `routers/__init__.py` still describe
   `prefix`/`limit`/`cursor` (docs sweep).
2. Health routes: built locally on `health-routes` at 07f3168 (not committed). Issue
   and PR texts written. Provider check is 503-only, per the shared interface.
3. Provider test fix: `test_wrong_credentials_are_access_denied_on_the_real_provider`
   fails on `dev` since #81 (metadata without `path` gives 400) and breaks further
   after #90. Patch in the session scratchpad; small PR of its own.
4. Docs sweep after #90 and Health: README List row, `routers/__init__.py`,
   ARCHITECTURE.md Metadata trace and `list_files` row, AGENTS.md code map (InvalidInput,
   test_move, test_shared_contract), TESTING.md layout row for Metadata. Add the
   1000+ key folder-delete OCI record (run 2026-11-11, passed).
5. Design (Nov 11 docx): status is stale (#81 "open", #87/#88/#90, 0.3.0 and 0.3.1
   tags now exist, Health owner). Review dispositions still to record.
6. Release v0.2.0: bump `pyproject.toml` + `uv lock`, get zeedorien's stale
   CHANGES_REQUESTED on #29 cleared, full provider suite, `dev` to `main`, tag, notes.
   Decide whether to wait for Create/Replace.
7. Close #80, #86, #89, #91, #72 (done by #81, #87, #90, #92, #74; PRs into `dev`
   do not auto-close issues).
8. Ask a teammate for the second real-provider run of folder `DELETE` and of Health.

Others: Create/Replace on `?path=` (Debasmith, not started); Move failure logs lack
`write_outcome` (Vikram: `move_file` not in `_WRITE_OPERATIONS`); conformance run
(Prateek); redeploy (Debasmith); streaming 0.3.x adoption (Debasmith/Darsh).

## To settle at the team meeting

- Confirm every owner in the design, including the end-to-end run, docs, and release.
- Health: Faizal understands it was assigned to Team 1, to be confirmed. The memo gives
  Team 1 the health clause, but the design still lists `GET /health` and
  `GET /health/provider` on our service, so confirm who builds ours too.
- Owner for the early end-to-end run on OCI. The older design gave it to Darsh,
  Debasmith, and Vikram.
- The hosting decision, which the design wants before Milestone 3 work starts.
- The Team 6 reviewer for the consolidated design.
- Issue #69: unassigned, asks for a recorded team sign-off on the error model.
- A second person's real-provider run of `DELETE /files?path=`, needed for Level 2.

## Team map

| Person | Owns |
|---|---|
| Darsh Shani | Errors; Metadata and file info; shared error clause #4; external reviews of Teams 1 and 3 |
| Debasmith Mandal | Create and Replace; conditional PutObject on OCI; implementation contact; Download clause (shared #8) |
| Vikram Markali | Download; Move with `copy`; Move clause (shared #5) |
| Prateek Saxena | List with delimiter; conformance suite (shared #7, PR #6) and its run against our service |

## Watch out for

- Route order: the old `GET /files/{key:path}` swallows a new `GET /files/metadata`,
  because Download is registered first. Metadata has to land after Download's route
  changes, or be registered ahead of it.
- Shared #8 still keeps `GET /files/{key}`, against Decision 2.
- No team has run conformance against its own service, and Milestone 3 requires it.
- Team 3 has been silent on the shared repo, though their own PR #39 was opened and
  approved on Nov 9.
