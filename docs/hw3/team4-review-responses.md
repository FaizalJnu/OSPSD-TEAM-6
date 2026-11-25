# Team 4 review: answers to T4-1 to T4-8

Final version, 2026-11-23. Local only (`docs/hw*` is gitignored).

**Review:** Joseph Jiminian (Team 4) commented on `design_hw3.docx` on Drive (file
1d3hNBxkHy3uiJMPyqPVTz-KepOA_zLo4) on 2026-11-23. The file is a .docx, so the Drive reader
doesn't return its comments; read them by downloading it and parsing `word/comments.xml`.

**Checked:** every Team 4 claim against their source at tag
`team-4-issue-tracker-trello-v1.0.0`, and the plan against `docs/hw3/remaining-work.md`.

**Contents**

1. Decisions made
2. The eight 6.2 rows, ready to paste
3. Edits elsewhere in the design that the rows promise (make these first)
4. Who to tell
5. Faizal's checklist, including the Trello setup state

The rows and edits don't mention `remaining-work.md` or its decision numbers, because Team 4 and
course staff read the design.

---

## 1. Decisions made (Faizal, 2026-11-23)

| # | Question | Decision | Why |
|---|---|---|---|
| D1 | How the tracker recovers a lost create (T4-1, T4-2) | Use `create_tagged_issue` / `find_tagged_issue` when the implementation has them; otherwise fall back to the `[<run_id>]` title search | Fixes both duplicate cases Joseph found, and keeps any `IssueProvider` usable. The fallback is the code the current design already describes |
| D2 | Tracker `PROVIDER_ERROR` with `may_have_applied=False` (T4-4) | Never retryable. The failure log records `cause` | Uses only contract fields. The contract defines `cause` only as a log reason, and its format is each implementation's choice. Meets Joseph's minimum asks |
| D3 | Trello test-account token expiry (T4-6) | `expiration=30days`, created on Nov 23 (expires **Dec 23**) | Outlasts Demo Day (Dec 9) and the latest final release (Dec 16) with no renewal, and lapses on its own if teardown misses it |
| D4 | Per-user Trello (not a comment, but it changes T4-5) | Our pull request to Team 4 adds optional **key, token and list** arguments | Team 4's provider has "One list per process", and a user's token can only reach that user's own boards |
| D5 | Filing the contract gap that the tagged pair sits outside `IssueProvider` | One paragraph in the per-user credentials issue to Team 4 | No new work item |
| D6 | Tracker readiness check (T4-7) | Keep `list_issues(limit=1)` | One request either way; stays on the contract |

---

## 2. Rows for 6.2

Add this sentence after the paragraph above the table:

> Team 4 reviewed the current draft, so the section numbers in their comments match. Where a
> response changes code that is not yet written, the status names the owner and the date.

### T4-1

**Reviewer:** Team 4

**Comment:** The package already supports idempotent creation outside the IssueProvider protocol: create\_tagged\_issue(title, creation\_token) and find\_tagged\_issue(creation\_token). The token is 64 lowercase hex characters, so the full SHA-256 behind run\_id fits. Use them for recovery in 2.3 and drop the gap row. Feature-detect them and fall back to the title marker for other implementations, or the configuration swap breaks.

**Response:** Changed (Overview, 1.5, 2.1, 2.3). The creation token is the full SHA-256 of the canonical request; the run ID is its first 12 characters. Once runs are per user, the hash also covers the user ID. When the configured implementation has both methods, the tracker adapter creates with create\_tagged\_issue(title, token), and recovery calls find\_tagged\_issue(token) before creating again. The adapter checks for the two methods once, when it is built. An implementation without them uses create\_issue and the \[\<run\_id\>\] title search (T4-2 states that path's assumptions). The title keeps the marker either way, so a person can still find the card by its run ID. The 1.5 gap row now covers only the IssueProvider interface, which still has no idempotent create.

**Status:** Closed in the design. Code: tracker adapter (Darsh) and orchestrator recovery (Vikram), Nov 23

### T4-2

**Reviewer:** Team 4

**Comment:** Recovering through list\_issues can create a duplicate. It returns only open cards, so if the card is archived between the lost response and the retry, the search misses it and a second card is created. Anyone can also rename the card in Trello and remove the title marker. find\_tagged\_issue includes archived cards for this reason. If the approach stays, state the 100-card window as an assumption.

**Response:** Changed (2.3, 3.1). With Team 4's package, recovery now uses find\_tagged\_issue (T4-1). It includes archived cards and matches the card's description, not its title, so neither archiving nor renaming leads to a duplicate. The title search remains only as the fallback for implementations without the tagged methods. 2.3 now states its assumptions (Assumed): between the lost response and the retry, the card stays open, keeps its title, and stays among the newest 100 open issues. All three hold on our dedicated test list, which only this service and its smoke check write to.

**Status:** Closed in the design. Code: orchestrator (Vikram), Nov 23

### T4-3

**Reviewer:** Team 4

**Comment:** Answers to the questions in 6.1, checked against v1.0.0. (1) list\_issues is newest first (sorted by card ID, which starts with the creation time) and never cached; get\_issue reads Trello every time, so fresh changes nothing. (2) Titles are sent to Trello unchanged; Trello's own whitespace handling isn't verified, so cover it in test\_live.py. (3) The settings are TRELLO\_API\_KEY, TRELLO\_TOKEN and TRELLO\_LIST\_ID. (4) A failed create sets may\_have\_applied=False on any Trello 4xx, failed DNS lookup or refused connection, and True on a 5xx, timeout, reset or unreadable 2xx body. (5) Every Trello request has a 10 s timeout and nothing retries internally. The timeout is passed explicitly, so socket.setdefaulttimeout(30) doesn't affect it.

**Response:** Changed (1.5, 2.2, 3.3, open question 2). We confirmed each answer in the v1.0.0 source. 1.5 records (1) and (4) as what we rely on. (2): step 0 trims the title, so no leading or trailing spaces reach Trello. test\_live.py will check that get\_issue returns exactly the title sent, marker included. (3) and (4) close open question 2. (5): the Trello bullet in 2.2 is now Observed, because every request passes timeout=10 to urlopen and the package has no retry loop. The tracker's worst case is then 20 s guard + 10 s connect + 10 s response = 40 s, under the 120-second lease.

**Status:** Closed in the design. Live title check: Prateek, Nov 24

### T4-4

**Reviewer:** Team 4

**Comment:** Not every tracker PROVIDER\_ERROR with may\_have\_applied=False can be retried. A Trello 429 (rate limit) and a wrong TRELLO\_LIST\_ID (a 4xx on create) both arrive as provider\_error with may\_have\_applied=False. Retrying fixes the first and never the second. Only ServiceError.cause (provider\_status=429 vs 400/404) tells them apart. Translate on cause, or at least log it, and don't return retryable: true for a configuration error.

**Response:** Changed (1.5, 3.1). A tracker PROVIDER\_ERROR with may\_have\_applied=False now returns retryable: false. The message asks an operator to check the tracker settings, or wait if the tracker is rate limiting, and then resend. The failure log line records cause next to the provider's code, so the log tells a rate limit from a wrong list. We don't translate on cause itself. The contract defines it only as a short internal reason for logs, and its format belongs to each implementation. A rate limit on our test list is unlikely, so making a person resend costs little. A PROVIDER\_ERROR with may\_have\_applied=True doesn't change: it is retryable, and recovery finds the card (T4-1).

**Status:** Closed in the design. Code: tracker adapter and failure log (Darsh), Nov 23

### T4-5

**Reviewer:** Team 4

**Comment:** The startup check won't catch missing Trello settings. TrelloIssueProvider reads TRELLO\_API\_KEY, TRELLO\_TOKEN and TRELLO\_LIST\_ID on every call, not at construction. The team4-trello builder therefore always succeeds, and a missing value only surfaces as SERVICE\_NOT\_CONFIGURED on the first request. factories.py should check the three variables itself, so startup fails and names the variable, as 2.4 promises.

**Response:** Changed (1.1). The team4-trello builder in factories.py checks the three variables before it builds the provider. A missing value stops startup, and the error names the variable, never its value. This is in the product/ scaffold, with a test that startup fails and names TRELLO\_LIST\_ID when it is unset. The builder checks only that each value is present. A wrong value still fails on the first call (T4-4), and the post-deploy smoke check (4.3) catches it before a deploy counts as successful. The check covers the shared test account. When per-user Trello credentials land (our pull request to Team 4 adds key, token and list arguments), each user's values come from their connection, and the builder checks only the settings that stay in the environment.

**Status:** Closed (product/ scaffold)

### T4-6

**Reviewer:** Team 4

**Comment:** The setting names are right, so "to be confirmed" can go. The Trello token expires too: Team 4's README authorize URL uses expiration=30days, and 4.4 only has a renewal procedure for the 7-day Google token. Either generate a never-expiring token for the dedicated test account and revoke it at teardown (4.7 already plans that), or add a Trello renewal step before each demo and grading window.

**Response:** Changed (4.4, open question 2). Removed "to be confirmed" from the Trello settings in 4.4. The test user's token uses expiration=30days and was created on November 23, so it expires on December 23. That is after Demo Day (December 9) and the latest final release (December 16), so no renewal falls inside the course. If teardown (4.7) misses the token, it lapses on its own a week later. 4.4 records the expiry date. A token created again before a grading window would need the same check.

**Status:** Closed

### T4-7

**Reviewer:** Team 4

**Comment (minor):** list\_issues fetches the whole Trello list and then cuts it, so readiness's list\_issues(limit=1) still downloads every card. Fine on a test list. The package's ping() is lighter, but it isn't in the contract, so it would need the same feature-detect-and-fall-back as T4-1.

**Response:** Accepted as is. Readiness makes one Trello request either way; only the response size differs. The test list stays small, because the smoke check deletes the cards it creates (4.3). Calling list\_issues keeps readiness on a contract method, so it behaves the same for every tracker implementation. We will revisit if the test list grows past a few hundred cards.

**Status:** Closed

### T4-8

**Reviewer:** Team 4

**Comment:** "Team 4 chose this" (2.2, Alternative 1) may be out of date. Team 4's issue service doesn't rely on caller-held state for creates: app/idempotency.py stores a creation token and recovers lost creates with find\_tagged\_issue before creating again. Re-check against the current repository before citing it.

**Response:** Accepted as is, with the wording clarified (2.2). The sentence refers to Team 4's HW3 operation, not their HW2 issue service. Their product/docs/DESIGN.md (decision "Caller-held state", unchanged since commit d18a415 on November 18, checked November 23) says the service stores nothing and the caller sends plan and created back as replay. That decision lists the issue service's server-side Idempotency-Key as the alternative it didn't take. 2.2 now reads "Team 4's HW3 operation chose this". Alternative 2 already credits the HW2 service's SQLite store for idempotency keys.

**Status:** Closed

---

## 3. Edits the rows promise

Section numbers are the current draft's. Make these before pasting the rows.

**Header and status**

1. Reviewers line: "Team 4 (Issue Tracker implementation owner): reviewed, comments answered in 6.2."
2. Milestone 1 status table, last row: "Reviewed by Debasmith (Team 6), Team 5 (Calendar) and Team 4 (Issue Tracker); their comments answered in 6.2. Dayana (Team 1) review requested."
3. Last updated: 2026-11-23.
4. Section 6 table, Team 4 row, Status: "Reviewed; comments answered".

**Overview** (T4-1). In "Why a storage team builds it this way", after "takes no idempotency key", add: "Team 4's package adds a tagged create outside that interface, which the tracker step uses when it is present (2.3)."

**1.1** (T4-5). Implementation registry row: after "calls that implementation's constructor", add: "A builder checks every setting its implementation needs, including those the implementation itself reads only on first use."

**1.5, tracker row of "What we rely on"** (T4-1, T4-3). Replace with:

| Issue Tracker (issue-tracker-contract v1.1.0) | create\_issue, get\_issue(fresh=True), list\_issues; create\_tagged\_issue and find\_tagged\_issue when the implementation has them (Team 4's does) | find\_tagged\_issue finds a card by its creation token, archived or not. list\_issues returns open issues only, newest first, never cached, at most 100. Titles are stored as sent. ServiceError.may\_have\_applied is False for a refused or unsent write and True for an uncertain one. Titles 1 to 256 characters. Each Trello request times out after 10 s and is never retried (Team 4 review, 6.2) |

**1.5, gap table.** Replace the tracker row (T4-1) and add the two per-user rows. The per-user rows aren't from the review: your per-user credentials row says its issues and pull requests are linked from 1.5. In the docx the Reported column says "To raise …" or "To file with a pull request, owner Faizal", like the other gap rows; replace that with the links once they're opened.

| Gap | Owner | Effect on this design | Workaround | Reported |
| --- | --- | --- | --- | --- |
| IssueProvider has no idempotent create. Team 4's package adds create\_tagged\_issue and find\_tagged\_issue outside the interface | Tracker contract (Team 4) | An implementation without the tagged pair can only be searched by title | The adapter uses the tagged pair when present; otherwise the title marker and list\_issues (2.3) | Raised in our per-user credentials issue to Team 4 (link) |
| Team 4's Trello provider reads one key, token and list from the environment ("One list per process"), so it cannot act for more than one user | Team 4 | Milestone 2 needs each user's own Trello account and list | Our pull request adds optional key, token and list arguments, with the environment as the default. We run from its commit until Team 4 tags a release | Issue and pull request (links) |
| Team 5's package builds a client only from a token file | Team 5 | Milestone 2 needs each user's own Google token | Our pull request adds a credentials argument. Until it is tagged, the user's token is written to a per-request temporary file (mode 0600, tmpfs) and deleted after the call | Issue and pull request (links) |

**1.5, error translation table** (T4-4). Replace the "Tracker PROVIDER\_ERROR" row with:

| From | To |
| --- | --- |
| Tracker PROVIDER\_ERROR, may\_have\_applied: true | provider\_error, retryable; recovery finds the card (2.3) |
| Tracker PROVIDER\_ERROR, may\_have\_applied: false | provider\_error, not retryable. The message asks an operator to check the tracker settings, or wait out a rate limit, then resend. The failure log records cause |

**2.1, Tradeoff** (T4-1). Replace "Over HTTP, Team 4's server-side Idempotency-Key would make step 2 safe to retry, which the package does not offer." with "Team 4's package offers the same protection as its HTTP service's Idempotency-Key through its tagged create (2.3)."

**2.2** (T4-3, T4-8)

- Replace the Trello bullet with: "Team 4's Trello package passes a 10-second timeout to every request and never retries (Observed in the v1.0.0 source; Team 4 review, 6.2 T4-3). The explicit timeout overrides the socket default set below. Tracker worst case: 20 s guard + 10 s connect + 10 s response = 40 s, under the 120-second lease."
- Alternative 1: replace "Team 4 chose this." with "Team 4's HW3 operation chose this."

**2.3, the "Tracker second" paragraph** (T4-1, T4-2). Replace with:

> Tracker second. A lost create\_issue response can be recovered. Team 4's package has create\_tagged\_issue(title, token) and find\_tagged\_issue(token) outside the contract interface. The token is the full SHA-256 of the canonical request, whose first 12 characters are the run ID; once runs are per user, the hash also covers the user ID. On resume, an attempting or unknown issue step calls find\_tagged\_issue. If it finds a card, the ID is adopted; if not, the issue is created. The lookup includes archived cards and matches the description, not the title, so archiving or renaming the card cannot cause a duplicate. The adapter checks for the two methods when it is built. An implementation without them falls back to the \[\<run\_id\>\] marker in the title, searched with list\_issues(limit=100). That fallback assumes the card stays open, keeps its title and stays among the newest 100 open issues until the retry (Assumed; true on a dedicated test list). The title carries the marker either way. The 120-second lease means the earlier request's call has finished by then.

**3.1** (T4-2, T4-4)

- New row after "Tracker refuses": Trigger "Tracker rejects the create (PROVIDER\_ERROR, not applied: a wrong list, a rate limit)". Caller sees "502 provider\_error, not retryable, failed". State "Record only; issue step not\_applied". Recovery "Operator reads cause in the failure log, fixes the list setting or waits out the rate limit, then same request". Test "C: test\_tracker\_rejects\_is\_not\_retryable".
- "Tracker response lost" row, Recovery: "Same request: find\_tagged\_issue looks for the run's token, archived cards included, and adopts or creates. Without the tagged pair, the newest 100 open cards are searched for \[\<run\_id\>\]". Test: add test\_tracker\_lost\_response\_without\_tagged\_methods.

**3.3** (T4-3). In "Other layers", after the test\_live.py description, add: "test\_live.py also checks that get\_issue returns exactly the title sent, marker included."

**4.4** (T4-6)

- Trello row, Settings: "TRELLO\_API\_KEY, TRELLO\_TOKEN, TRELLO\_LIST\_ID (names per Team 4's package)".
- After the Google token renewal steps, add: "Trello token. Created with expiration=30days on 2026-11-23; it expires on 2026-12-23, after Demo Day and the latest final release, so no renewal falls inside the course. A token created again must still outlast the next grading window."

**7, Open questions**. Row 2: "Closed (6.2 T4-3, T4-6): settings are TRELLO\_API\_KEY, TRELLO\_TOKEN and TRELLO\_LIST\_ID; may\_have\_applied is False on a refusal or unsent request" | Faizal, with Team 4 | Done.

**Revision notes**. Add above the 2026-11-18 notes:

> Revision notes, 2026-11-23
>
> After Team 4's review (6.2):
>
> Tracker recovery uses Team 4's tagged create and lookup when the implementation has them, and falls back to the title marker otherwise; the fallback's assumptions are stated (2.3).
>
> A tracker error that refused the write is no longer retryable; the failure log records its cause (1.5, 3.1).
>
> The team4-trello builder checks its three settings at startup (1.1). The Trello token's expiry is recorded (4.4).
>
> Trello timeout marked Observed (2.2). Closed open question 2. Added the per-user credential gaps for Teams 4 and 5 (1.5).
>
> Reviewers: Team 4 (Issue Tracker) reviewed.

---

## 4. Who to tell

| Who | Their row and due date | What changes for them |
|---|---|---|
| Vikram | Orchestrator, run record, agenda (Mon 23 EOD) | Recovery tries `find_tagged_issue` first, then the title search. Creation token = full SHA-256 of the canonical request |
| Darsh | Adapters and error tables, failure log line (Mon 23 EOD) | Tracker adapter checks for the tagged pair when built. Tracker `PROVIDER_ERROR` with `may_have_applied=False` is not retryable. Failure log records `cause` |
| Prateek | Fast tests, live test, smoke check (Tue 24 noon) | `test_live.py` checks the exact title. New 3.1 tests: tracker rejects (not retryable), lost response without the tagged pair |
| Debasmith | Pipeline and secrets | Three Trello values for the staging and demo CI secrets, once the check passes |

`FakeTracker` (in the scaffold) has no `create_tagged_issue` or `find_tagged_issue`. Add a variant
with them and keep one without, so both recovery paths can be tested. Either do it as a small
follow-up to the scaffold, or Vikram adds it with the orchestrator.

---

## 5. Faizal's checklist

### Trello test account (your test-accounts row, Mon 23 EOD)

State as of this file:

- **Board:** "Team 6 Review Meetings" in `fr2471's workspace`, with lists To Do, Doing, Done.
- **App:** "Team 6 Review Meetings", made in the Power-Ups admin portal. API key and secret are
  saved in `product/.env` (gitignored, mode 600) as `TRELLO_API_KEY` and `TRELLO_API_SECRET`.
  `TRACKER_PROVIDER=team4-trello` is set there.
- **Allowed origins:** empty. They're not needed for the 30-day token flow.

Done on 2026-11-23 (evening, US Eastern):

- [x] **Token** created with `expiration=30days` (expires 2026-12-23) and saved in `product/.env`.
- [x] **List ID**: "To Do", `6b04d166cb38711df465c005`, saved in `product/.env`.
- [x] **Live check** (`docs/hw3/trello-check.py`): ping True, tagged create, exact title kept
  (double spaces included), `find_tagged_issue` finds it, newest in `list_issues`, card deleted.
- [x] **Account check**: the token sees only the "Team 6 Review Meetings" board.

Still to do:

- [x] **Rechecked 2026-11-23** (later the same day): live check passed again; the app's own
  `team4-trello` builder starts from `product/.env` and reaches the list (0 open cards).
- [x] **Secret.** Decided: not replaced. The Trello app is deleted after the course ends.
- [ ] Share the three values with the team through a password manager, for Debasmith's CI
  secrets. (The product CI workflow reads no Trello secret today; they are for the staging and
  demo deploy.)

### The design (your design row; comments recorded by Wed 25 EOD)

- [x] Edits from part 3 and the rows from part 2 applied to `docs/hw3/design_hw3.docx` (built on
  your Drive version of 2026-11-24 00:10 UTC, with your header changes kept; validated and rendered).
- [ ] Upload it in Drive: right-click `design_hw3.docx`, File information, Manage versions,
  Upload new version. Same link. Do it before anyone else edits the doc, or their edits are lost.
- [ ] Reply "Answered in 6.2" on the four comments still open (T4-2, T4-3, T4-4, T4-6) and resolve them.
  The other four (T4-1, T4-5, T4-7, T4-8) were already removed from the file.
- [ ] Send part 4 to Vikram, Darsh and Prateek today (their rows are due Mon 23 EOD and Tue 24 noon).

### Per-user credentials to Team 4 (your row, pull requests opened Mon 23 EOD)

Found 2026-11-23: Team 4 already has this, requested by Team 5. Issue
Tyler-Arciniaga/OSPSD-Team-4#91 and PR #92 (head `b687c86`, open, review required) add
`TrelloIssueProvider(*, api_key=None, token=None, list_id=None)`. `None` falls back to the
environment, `""` counts as missing, and the version goes to 1.1.0. Tag
`team-4-issue-tracker-trello-v1.1.0` after merge, target about Nov 26. So we don't open our own.

- [ ] Run `docs/hw3/trello-pr92-check.py` (live check of #92, command in its docstring).
- [ ] Post `docs/hw3/team4-pr92-comment.md` on #92: we build on it, the live results, and the
  tagged-pair contract suggestion (D5).
- [ ] 1.5 gap row in the design: "Our pull request adds..." becomes "Team 4's PR #92 (requested
  by Team 5) adds...", linking #91 and #92.
- [ ] Until the tag exists, pin #92's merge commit in `product/pyproject.toml`.

### Provider connections (your row, Tue 24 EOD)

- [ ] When users connect Trello: add the staging, demo and local origins to the app's
  Allowed origins (`https://meetings.packapunch.xyz`, `https://meetings-staging.packapunch.xyz`,
  `http://localhost:<port>`).
- [ ] The team4-trello builder stops requiring `TRELLO_TOKEN` and `TRELLO_LIST_ID` for per-user
  construction (the T4-5 response promises this).
- [ ] The creation token's hash includes the user ID once runs are per user (the T4-1 response
  promises this).

### `remaining-work.md` lines now stale (not edited)

- "Where we stand", design row: Team 4 has now reviewed.
- Test-accounts row: "answers from Team 4 (open question 2)" is done (T4-3, T4-6).
- Decision 11: key and token arguments, plus list (D4).
- "Risks to raise now", last bullet: only Dayana's review is still outstanding.
