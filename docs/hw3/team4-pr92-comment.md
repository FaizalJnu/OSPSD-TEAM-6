# Comment for Team 4 PR #92 (post on the PR; it closes #91)

Post only after `docs/hw3/trello-pr92-check.py` has run and every line printed True / the
expected error. If anything differs, tell Claude the output first.

---

Team 6 here. We need the same change for our HW3 product (each signed-in user brings their own
Trello account and list), so we'll build on this instead of opening a second PR. Thanks for doing it.

**Live check.** The PR notes it hasn't been run against real Trello, so we ran commit `b687c86`
against our Trello test account with all `TRELLO_*` environment variables removed. The
provider only got values through the new arguments:

- No arguments and no environment: constructs, and the first call fails with
  `SERVICE_NOT_CONFIGURED` / `missing_credentials`.
- Two providers on the same account, one on list "To Do" and one on "Doing": interleaved
  `create_tagged_issue` / `create_issue` calls each landed in their own list. `list_issues`
  and `find_tagged_issue` saw only their own list's cards. `get_issue` by card ID works from
  either provider. Titles were kept exactly.
- A provider with a wrong token fails with `ACCESS_DENIED` (cause `provider_status=401`) and
  no credentials in the error text. A correct provider in the same process keeps working.
- All cards deleted afterwards.

Code looks good to us. Every request path now goes through `_headers()` / `_target_list_id()`,
and the environment is only the fallback for an omitted argument.

**Timing.** We're aiming to submit Milestone 2 by Nov 25. Until the
`team-4-issue-tracker-trello-v1.1.0` tag exists, we'll pin this PR's merge commit and switch to
the tag when it's out. Could you comment here when it's tagged?

**One suggestion for later (not for this PR).** `create_tagged_issue` and `find_tagged_issue`
are what make a lost create response safe to retry. They archive-proof the lookup and match on
the description, not the title. They currently sit outside `IssueProvider` in
`issue-tracker-contract`, so a consumer has to feature-detect them, and another tracker
implementation can't advertise them. Consider adding them to the contract in a later minor
version, for example as a separate optional protocol (`TaggedIssueProvider`), so existing
implementations stay conformant. Happy to open an issue for it if you'd like.
