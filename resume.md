# Resume point (handoff to another device)

Written 2026-11-25, 23:00 UTC (18:00 ET). Branch `wip/handoff-2026-11-25` holds everything
that was only on the old laptop. `plan.md`, `resume.md`, `docs/hw2/` and `docs/hw3/` are in
`.gitignore`; this branch force-adds them only to move them. Do not merge this branch as is:
split it into pull requests (see "What is on this branch").

## 1. Set up the new device

```bash
git clone git@github.com:FaizalJnu/OSPSD-TEAM-6.git && cd OSPSD-TEAM-6
git checkout wip/handoff-2026-11-25
uv python install 3.13 3.14          # root and interface use 3.13 (3.12 also works for root); product needs 3.14
uv sync                              # storage service
(cd product && uv sync)              # Meeting Prep product
(cd interface && uv sync)            # web interface
uv run pytest && (cd product && uv run pytest) && (cd interface && uv run pytest)
```

Pushing needs your SSH key on GitHub (the old laptop pushed over SSH; its `gh` token was read-only).

Not in git, copy them from the old laptop over a private channel, never into the repository:

* `.env` (storage service: `STORAGE_BACKEND`, `S3_*` for OCI). Template: `.env.example`.
* `product/.env` (Groq key, Google sign-in client, Trello test account, S3, database URL,
  `PRODUCT_API_KEY`, and the new `CONNECTION_TOKEN_KEY`, `TRELLO_APP_KEY`). Template:
  `product/.env.example`.
* Google Calendar token: `~/.config/team6-meeting-prep/calendar-token.json`.
* The HW3 handout (`docs/hw3/HW3.md`) and HW2 handout were left out on purpose (course
  material in a public repository). Download them from Brightspace.

## 2. Deadlines

* **HW3 Milestone 2: Wed Dec 2.** The team's target was Nov 25, so it is late against our
  own plan, not the deadline. Launch week Dec 2 to 6 (does not move). Milestone 3 and
  Demo Day: Dec 9.
* **Google Testing-mode refresh token dies about Dec 2, 13:07.** Re-authorize before launch
  week and again before Demo Day. Trello token expires Dec 23.
* HW2 Brightspace submission (release, DESIGN.md, infrastructure, pipeline run with
  conformance, dashboard/logs/traces, extra credit): item 4 is blocked, see section 5.

## 3. What is on this branch

On top of `dev` at 508000b, in this order. Make each pull request from `origin/dev` with
`git cherry-pick <commit>`, so the notes commit never reaches `dev`.

| Commit | What | Next step |
|---|---|---|
| a5180a0 | Create/Replace on the shared `POST /files` and `PUT /files` routes; old `/files/{key}` kept, deprecated. 357 fast tests, ruff, mypy clean; smoke check passes locally. Provider tests and conformance suite NOT run. | Open the issue (`docs/hw3/create-replace-issue.md`), then the PR into `dev` (`docs/hw3/create-replace-pr.md`; fill the issue number, owner, review box). Run `uv run --env-file .env pytest -m provider` first. |
| ea978ff | WIP snapshot of provider connections, step 1: tables + migration 0005, token cipher, connection store, `USER_PROVIDERS=connections`, Team 4 pin v1.1.0, `cryptography`. 475 product tests pass. | Another Claude session on the old laptop was still working on this on local branch `provider-connections` (not pushed). If that branch gets pushed, prefer it; otherwise continue from this commit. PR text: `docs/hw3/connections-pr.md`. Step 2 (OAuth flows, `/v1/connections`) not built. |
| 57913b7 | Drafts: `product/docs/BRIEF.md`, `DISCOVERY.md`, `READINESS.md` | Fill the **To fill** parts (section 6), then a docs PR. |
| notes | `plan.md`, this file, `docs/hw2/`, `docs/hw3/` drafts | Keep local. Never into `dev`/`main`. |

## 4. Partner work

* **Team 5 PR #65 is open:** https://github.com/OSPSD-Team-5/OSPSD-Team-5/pull/65, from
  `FaizalJnu/OSPSD-Team-5` branch `hw3/calendar-credentials-and-upcoming` (e1821c6):
  `create_calendar_service(credentials=...)` and `list_upcoming(start, end)`. Fill the live-check
  block in `docs/hw3/team5-pr.md` (run `docs/hw3/team5-pr-check.py`). Then pin
  `product/pyproject.toml` `team5-calendar` to the fork URL + `rev=e1821c6` (or their tag once
  merged) and `uv lock`; the calendar builder in provider connections waits on this.
  Team 5 issue #64: no reply.
* **Team 4:** #92 merged, tag `team-4-issue-tracker-trello-v1.1.0`; the pin bump is in ea978ff.
* **Team 2 (1mpossible-code), our issue #99:** they asked for an installable adapter on Python
  3.12; we shipped it in v0.2.0 (#100, #101) and told them on Nov 23. Waiting for their
  verification; close when they confirm.

## 5. HW2 submission, item 4 (pipeline run + conformance)

v0.2.0 (b021b36 = `main`) cannot serve: its CI has no conformance step and the deploy
workflow did not exist yet. Plan:

1. Merge the Create/Replace PR (a5180a0). Without it, 46 of 55 conformance tests fail.
2. Add the CI conformance job: ready-to-paste YAML and steps in `docs/hw3/conformance-ci-job.md`.
   Run the suite locally first.
3. Release per `CONTRIBUTING.md`: release issue, `uv version --bump minor` (0.3.0) PR into
   `dev`, `dev` -> `main`, provider tests, `git tag -a v0.3.0`, GitHub Release. This can be the
   same release Milestone 2 needs. The first deploy of `main` to https://ds.packapunch.xyz
   runs from this merge: watch it.
4. Submit: the CI run on the tag (conformance job, "55 passed", results artifact) and the
   "Deploy storage service" run for the same commit. Point items 1 to 3 at the new tag.

Item 5 (dashboard, logs, traces): nothing exists in the repository. Section 10.5 of
`docs/hw2/DESIGN_Hw2_final.md` is the plan (Debasmith).

## 6. HW3 Milestone 2 checklist

The handout's list: brief, discovery notes, assumption tests, updated DESIGN.md + review
record, tracker, GitHub Release + commit, deployed product + getting-started page, and the
tests, evaluations and readiness evidence per level. Staff must open every link; invite
them to the tracker and dashboard; add their emails as Google OAuth test users.
`docs/hw3/m2-submission.md` has the Brightspace entry; `docs/hw3/remaining-work.md` the owners.

| Item | State on Nov 25 evening |
|---|---|
| Brief | Drafted (57913b7). To fill: evidence quotes, assumption 3, product assumption test, tracker + design links |
| Discovery notes | Template only. Outside interviews are optional in the handout; the team discussion counts |
| Assumption tests | Groq budget test on `dev`; no product assumption test yet |
| DESIGN.md + review record | Google Doc (Drive file `1d3hNBxkHy3uiJMPyqPVTz-KepOA_zLo4`), PRIVATE: share it. Paste `docs/hw3/design-m2-sections.md` (sections 9-15); 8.2 and 8.8 empty. Local copy `docs/hw3/design.md` |
| Tracker | No GitHub milestones or project board yet |
| Release | None since v0.2.0 (see section 5) |
| Deployed product | NOT deployed: no DNS for `meetings*.packapunch.xyz`, no product Dockerfile/workflow, no Neon (Debasmith) |
| Getting-started page | `interface/GETTING_STARTED.md` on `dev` |
| L2 interface | Scenario runs through the interface, CI runs its tests. Record the no-coaching usability check |
| L3 agent | Tool contracts (`product/docs/agent.md`), deterministic tests, Vikram's prompt v1 -> v2 measurement. Missing: live execution trace, evaluation results link (Prateek) |
| L4 security | Sign-in, user API, approvals merged (#124, #129). Provider connections in progress. Outside-team getting-started run not done |
| L5 readiness | `READINESS.md` drafted ("not ready"; next decision Tue Dec 1 18:00 ET). No load test, dashboard, alert test, backup restore (Debasmith, Prateek) |

### Conversations to consolidate (Faizal)

These are all the product conversations we had:

* **Team WhatsApp:** chose the recommended approaches and Groq. Goes into DISCOVERY.md "Team
  discussion" and the design's decision record. Needed from you: dates, who took part, a
  few quoted messages, what was disagreed and how it was settled. Do not invent quotes.
* **Google Doc comments from Teams 4 and 5:** go into the design's review record, each with
  our response. Sources: `docs/hw3/team4-review-responses.md`, `docs/hw3/team5-credentials-issue.md`,
  `docs/hw3/team5-pr.md`; follow-through Team 4 #92 and Team 5 #65.
* **Issue #99 (Team 2):** about our storage package, not product discovery. Use it in the
  design's dependencies section, or in Milestone 3 ("issues you received and their dispositions").

## 7. Working notes

* Several Claude sessions shared one checkout on the old laptop. Give each its own git
  worktree; never switch branches in a folder another session is using.
* Never commit `.env` or tokens. Claude attribution in commits and PRs: decide later (none
  added so far).
* The old laptop still has the worktree `.claude/worktrees/shared-create-replace-routes`
  (this branch) and the main folder on `provider-connections` with uncommitted work.
