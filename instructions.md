# Team 6 work plan: finish Levels 1 to 4

This is a temporary plan for the **review release, due Oct 14 before class**. It covers
what is still missing from Levels 1 and 2 and all of Levels 3 and 4. Level 5 gets its
own plan later. Only the coordinator (Faizal) edits this file. If something here is
wrong, say so in Slack.

## 0. Where things stand

The service already has six working operations, an S3 backend (tested on OCI), an
in-memory backend for tests, and green CI. Most of the Level 3 and 4 code also exists:
`storage/base.py` is the provider-independent interface, and `main.py` supplies the
implementation to the app. What is missing:

* **Ownership.** Level 1 says each of us owns one operation through all five levels.
  All six operations came from one PR, so nobody owns one yet.
* **Contracts.** Success status codes and response fields are not documented per
  operation. Some error responses (the 422s) don't match the documented error format.
* **Real-provider evidence.** We have no HTTP-level test against a real bucket, and no
  recorded request, expected result, and observed result for any operation.
* **Two likely provider bugs.** A wrong bucket name probably looks like "file not
  found". A malformed list cursor probably gives 502 on S3 but 200 on the memory backend.
* **Level 3 and 4 explanation.** The interface methods need full contracts. We need
  translation tests that run without network, a test double that can simulate
  failures, and a short written explanation of the boundary that everyone understands.

## 1. Before you start

1. Read the course handouts in `docs/`, in this order: `introduction.txt`,
   `level1.txt` to `level4.txt`, `testing.txt`, then sections 1 to 4, 6 to 8, and 10 of
   `grading.txt`. Skim `level5.txt` so you don't design yourself into a corner.
2. Read `README.md`, `AGENTS.md`, and `CONTRIBUTING.md`.
3. Install uv (`brew install uv`, or see https://docs.astral.sh/uv/), then run
   `uv sync` and `uv run pytest`. Everything should pass.
4. Set up your own provider account (section 2).
5. Find your tasks in section 5, and open one issue per task (section 3).

## 2. Set up your own provider account

Everyone tests against **their own bucket with their own keys**. Never share keys, and
never paste them into Slack, issues, PRs, commits, or test output.

Our backend speaks the S3 API, so pick a provider with an S3-compatible endpoint:

| Provider | `S3_ENDPOINT` | Credentials | Notes |
|---|---|---|---|
| OCI Object Storage | `https://<namespace>.compat.objectstorage.<region>.oraclecloud.com` | Customer secret key | Our main provider. Step-by-step setup is in `README.md`. |
| AWS S3 | `https://s3.<region>.amazonaws.com` | IAM user access key, limited to one bucket | |
| Google Cloud Storage | `https://storage.googleapis.com` | HMAC key (Cloud Storage > Settings > Interoperability) | Not identical to S3. See the checksum note in `.env.example`. |
| Cloudflare R2 | `https://<account-id>.r2.cloudflarestorage.com` | R2 API token (access key + secret) | `S3_REGION=auto` |
| MinIO or Garage in Docker | `http://127.0.0.1:<port>` | Keys you choose | Fine for development, but it does not count as real-provider verification. |

**Azure Blob Storage has no S3-compatible API**, so it will not work with our backend.
Supporting it would mean writing a new backend, which is out of scope for this round.

Steps:

1. Create a private bucket used only for this project.
2. Create keys that can only read, write, list, and delete objects in that bucket.
3. Run `cp .env.example .env` and fill it in. `.env` is gitignored.
4. Check the connection by running the contract tests against your bucket. Before
   F1 is merged, run `uv run --env-file .env pytest tests/test_storage_contract.py`.
   After F1 is merged, run `uv run --env-file .env pytest -m provider`. Every test
   should pass. A failure probably means your provider differs from S3, so open an
   issue with the output.
5. Start the server against your bucket and work through "Try it" in the README.
6. If you are not using OCI, add your provider's setup notes and contract-test result to
   `docs/PROVIDERS.md` (created by F2). This is the evidence behind the README's claim
   that switching providers only takes a configuration change.
7. Clean up as you go. At the end of the course, delete your keys and your bucket.

Releases are verified against OCI, because that is the provider the README documents.
The release manager reruns the provider tests on OCI before tagging.

## 3. How we work

### Issues, branches, and PRs

* Open one issue per task with the feature template (or the bug template for BUG-*
  tasks), and assign it to yourself. Copy the acceptance criteria from this file.
* Branch from the latest `main`, named `<issue-number>-<short-name>`.
* Open one PR per task with `Closes #<issue>`. Keep it to one purpose.
* Write the PR title as the change in behavior, for example "Return 400 for malformed
  list cursors". The title becomes the squash commit message, so titles like "Updates"
  or "Fix stuff" are not acceptable.
* Merge rules (from `CONTRIBUTING.md`): the reviewer listed in section 5 approves, CI
  is green, every comment is resolved, and the branch is up to date with `main`. Then
  the author squash-merges and deletes the branch.
* Don't change routes, field names, or status codes unless the change was agreed in the
  issue first. Other people's docs and tests depend on them. ERR-400 is the one
  contract change this plan has already agreed.

### PR description

The course asks us to **write our own PR descriptions and commit messages**. An agent
can collect facts for you, such as which files changed and the test output, but the
explanation must be yours. Graders read these descriptions (grading section 10.2). Use
this template. F2 also makes it the repository's PR template.

```markdown
## Which issue does this PR close?
Closes #

## Problem and resulting behavior
What was missing or wrong, and what the service does now. For a change to existing
behavior, show before and after: request, status, body.

## Approach and why
Why this approach. Alternatives you considered. Assumptions you made. Compatibility
consequences (if this breaks the API, add the `breaking change` label).

## What changed
One line per changed file, naming the responsibility that required the change. If you
extended a teammate's code, say which module or interface changed and why the change
spread to other files.

## How it was verified
- Fast checks: commands run and results (for example, `uv run pytest`: 41 passed).
- Tests added or changed, and what each one asserts.
- Real-provider check: provider, request, expected result, observed result (paste the
  output, with no keys in it).
- Bug fixes: the failing test output before the fix, and the passing output after it.

## Status
- What works:
- What remains / known gaps:
- Who owns the next steps:
- Blocked on:

## AI assistance
Which tool you used and what it produced. "I reviewed every line and can explain it."

## Checklist
- [ ] Linked to an issue, one purpose
- [ ] ruff check, ruff format --check, mypy, and pytest pass locally; CI is green
- [ ] Tests cover the new behavior; a bug fix starts with a failing test
- [ ] docs/API.md, TESTING.md, and README updated where behavior or setup changed
- [ ] No .env, keys, or other secrets committed
- [ ] I reviewed my own diff
```

### Reviewing a teammate's PR

1. Read the linked issue and the contract in `docs/API.md` first.
2. Check out the branch and run the fast checks. Then run the PR's provider tests
   against **your own** bucket (`uv run --env-file .env pytest -m provider -k <name>`).
   This is also how we meet the Level 2 rule that at least two people can run each
   operation against a real provider.
3. Look for:
   * documentation, examples, and code that disagree
   * tests that would still pass if the code were wrong
   * provider details outside `storage/s3.py`
   * secrets
4. Label each comment as **blocking**, **design concern**, **question**, or
   **suggestion**. A blocking comment must name the requirement it breaks or give a
   concrete failing case.
5. In your approval, say what you checked and what you observed. "LGTM" alone earns no
   review credit.

## 4. Using your coding agent

AGENTS.md is read automatically by most agents. Start your session with this prompt,
filling in your task ID:

```text
Read AGENTS.md, README.md, CONTRIBUTING.md, and instructions.md. Then read the course
handouts docs/level1.txt to docs/level4.txt and docs/testing.txt.

I own task <ID> in section 7 of instructions.md. Do only that task.

Before changing anything:
1. Restate the contract you will implement or document, list the files you will
   touch, and list the tests you will add and what each one asserts.
2. Wait for my OK.

While working:
- Follow the architecture rules in AGENTS.md.
- Don't edit files outside my task without asking. Don't edit instructions.md, CI, or
  the lint, type, or test configuration. Don't weaken or delete existing tests.
- Don't add dependencies.
- Never print or commit .env or any credential.
- If provider behavior is unclear, tell me what to run against my bucket instead of
  guessing.

Before saying you are done, run
  uv run ruff check --fix . && uv run ruff format . && uv run mypy && uv run pytest
and show me the output. Then list every acceptance criterion from my task that is
not done yet.
```

You are responsible for every line the agent writes. At the demo, staff can ask you to
trace your operation through the code, or to name the test that would catch a given
bug.

## 5. Who owns what

Each person owns one operation through Levels 1 to 5. Create and replace share one
upload path, so one person owns both. You can swap assignments if you want, but keep
one owner per operation.

| Engineer | Operation | Interface method | Other tasks |
|---|---|---|---|
| Faizal Rahman | Delete: `DELETE /files/{key}` | `delete` | F1, F2, review-release manager |
| Debasmith Mandal | Create + Replace: `POST` and `PUT /files/{key}` | `put` | ERR-400 |
| Vikram Markali | Download: `GET /files/{key}` | `get` | L4-FAKE, ARCH |
| Darsh Shani | Metadata: `GET /metadata/{key}` | `stat` | BUG-BUCKET |
| Prateek Saxena | List: `GET /files` | `list_files` | BUG-CURSOR, verifying the release from a fresh checkout |

Debasmith wrote the original code for every operation. For everyone else, the
operation PR therefore counts as **extending a teammate's feature** (introduction
section 6.3). In the PR, say which modules changed and why.

| ID | PR | Owner | Reviewer | Merge after |
|---|---|---|---|---|
| F1 | Test layout by operation, opt-in provider tests, shared fixtures | Faizal | Debasmith | none |
| F2 | Docs skeleton, PR template, remove duplicate templates | Faizal | Vikram | none |
| OP-UPLOAD | Create + Replace, Levels 1 to 4 | Debasmith | Prateek | F1, F2 |
| OP-DOWNLOAD | Download, Levels 1 to 4 | Vikram | Darsh | F1, F2 |
| OP-METADATA | Metadata, Levels 1 to 4 | Darsh | Faizal | F1, F2 |
| OP-DELETE | Delete, Levels 1 to 4 | Faizal | Darsh | F1, F2 |
| OP-LIST | List, Levels 1 to 4 | Prateek | Vikram | F1, F2 |
| BUG-BUCKET | Missing bucket reported as a missing file | Darsh | Faizal | F1 |
| BUG-CURSOR | Malformed cursor: 502 on S3, 200 in memory | Prateek | Vikram | F1 |
| ERR-400 | All invalid input returns 400 `InvalidInput` | Debasmith | Darsh | F2 |
| L4-FAKE | Test double that records calls and can be told to fail | Vikram | Debasmith | F1 |
| ARCH | Provider boundary and wiring explained, plus team walkthrough | Vikram | Debasmith, Prateek | the OP PRs |
| REL | Review prerelease | Faizal | Prateek verifies | everything |

## 6. Order of work

1. **Now, everyone:** do section 1, set up your provider, and try your operation with
   curl against your bucket. Open your issues.
2. **First, Faizal:** F1 and F2. Everything else builds on them, so reviewers should
   turn them around within a few hours.
3. **In parallel, everyone:** the OP, BUG, ERR-400, and L4-FAKE PRs. Rebase on `main`
   once F1 and F2 are merged.
4. **ARCH:** Vikram can draft it early, but should finalize it once the OP PRs settle,
   then hold the team walkthrough.
5. **REL:** once everything above is merged.

Files more than one person will touch:

* **`storage/s3.py`:** Darsh (`stat` and error translation) and Prateek
  (`list_files`). Talk to each other before changing the shared `_translate_errors`
  function. Whoever merges second rebases.
* **`storage/base.py`:** each owner edits only their own method's docstring. Vikram
  edits only the module docstring.
* **`docs/API.md` and `TESTING.md`:** each owner edits only their own section.
* **`tests/conftest.py`:** only F1 edits it. Put any fixture you need only for your
  operation in your own test file.

## 7. Tasks

### F1: Test foundation (Faizal)

Goal: five people can add tests in parallel without conflicts, and real-provider tests
only run when someone asks for them.

* Move the `client` fixture and the `send_file` helper from `tests/test_api.py` into
  `tests/conftest.py`.
* Split `tests/test_api.py` into one file per operation: `test_upload.py` (create,
  replace, size limit, invalid key), `test_download.py`, `test_metadata.py`,
  `test_delete.py`, and `test_list.py`. Move the tests exactly as they are, then delete
  `test_api.py`.
* Register a `provider` marker in `pyproject.toml` and add `addopts = "-m 'not
  provider'"`. After this, `uv run pytest` never contacts a provider, and
  `uv run --env-file .env pytest -m provider` runs only the provider tests. In
  `test_storage_contract.py`, replace the `skipif` with this marker on the `s3` param.
* Add two fixtures to `conftest.py`:
  * `provider_client`: a `TestClient` over `create_app(build_service(load_settings()))`,
    with a unique key prefix (`api-tests/<uuid>/`). It deletes everything under that
    prefix afterwards. It must **fail** rather than skip unless `STORAGE_BACKEND=s3`,
    so a provider test can never silently pass against the memory backend.
  * `stubbed_s3`: an `S3Storage` built with dummy credentials, with botocore's `Stubber`
    active on its client. It makes no network calls and fails the test if a stubbed
    response was never used.
* Update the test commands in `README.md` and `AGENTS.md`, and the test layout in
  `AGENTS.md`.
* **Done when:**
  * `uv run pytest` passes 32 tests with none skipped. The six S3 tests are deselected
    instead.
  * Without a `.env`, `-m provider` fails quickly with a clear error.
  * With your `.env`, `-m provider` passes against your bucket.
  * mypy and ruff are clean.

### F2: Docs foundation (Faizal)

Goal: every owner has a section to fill in, and there is one place for each kind of
information.

* Create `docs/API.md`:
  * Move these shared sections out of the README: key rules; the file info fields
    (`key`, `size` in bytes, `content_type`, `etag`, `last_modified` in UTC ISO 8601,
    each with its meaning); and the error format (a table of error type, status, when
    it happens, and whether retrying helps).
  * Add one empty section per operation, with its owner's name and these headings:
    Meaning, Request (with constraints), Success (status and body), Side effects,
    Errors, Retry, Assumptions, Example.
* Create `TESTING.md` with:
  * the commands for fast tests, provider tests, lint, and type checks
  * the test layout
  * one section per operation with these headings: Contract checked, Cases and
    boundaries, Tests (links), Real-provider verification (provider, date, commit,
    request, expected, observed, cleanup), Provider observations, Gaps
* Create `docs/PROVIDERS.md`. Point the OCI section to the README, and add empty
  sections for AWS, GCS, R2, and local MinIO or Garage.
* In the README, keep the API table (method, path, description) and link to
  `docs/API.md` for statuses and errors. Also link `TESTING.md` and `docs/PROVIDERS.md`.
* Replace `.github/pull_request_template.md` with the template in section 3.
* Delete the root `BUG_REPORT.md`, `FEATURE_REQUEST.md`, and `PULL_REQUEST_TEMPLATE.md`;
  they duplicate the copies in `.github/`.
* Fix or remove `.vscode/settings.json`, which selects conda although the project uses
  uv.
* Add the new docs to the code map in `AGENTS.md`.
* **Done when:** nothing is lost from the README (only moved and linked), and every
  operation has a section with its owner.

### Operation tasks: checklist for every owner

Before changing anything, read your operation's code path end to end:
`routes.py` → `service.py` → `storage/base.py` → `storage/s3.py` and
`storage/memory.py`. Put all your tests in your own operation's test file.

**Level 1: contract**

- [ ] Fill in your section of `docs/API.md`:
  * what the operation means
  * inputs and their constraints
  * success status and every response field
  * side effects
  * each error (status, error type, when it happens)
  * whether retrying helps
  * assumptions that affect what callers see
  * a complete curl example with its expected output, including how to pick a sample
    key and how to clean up
- [ ] Your HTTP success test (memory backend) asserts the status and **every** promised
  field. For writes, it also checks the resulting state with a follow-up read.
- [ ] `docs/API.md`, the README's "Try it", `/docs`, and the code all agree. Fix
  whichever one is wrong.

**Level 2: real provider**

- [ ] Add a `@pytest.mark.provider` HTTP test for your operation that uses
  `provider_client`. For writes, confirm the effect with a follow-up read.
- [ ] Run your operation by hand with curl against your bucket. In your section of
  `TESTING.md`, record the request, the expected result, and the observed result, and
  name the provider.
- [ ] Record any provider behavior that surprised you. If it breaks our contract, open a
  bug issue.

**Level 3: provider boundary**

- [ ] Rewrite the docstring of your `StorageClient` method in `storage/base.py`: its
  purpose, inputs, result, whether it reads or changes provider state, and what callers
  may assume.
- [ ] Add translation tests that use `stubbed_s3` and need no network. Show how
  `S3Storage` turns provider responses into our types (`FileInfo`, `FilePage`,
  `FileDownload`) and provider errors into our errors.

**Level 4: injection**

- [ ] Your application tests build the app with `create_app(service)` and a controlled
  implementation. They need no network or credentials.
- [ ] Fill in your strategy section in `TESTING.md`.

### OP-UPLOAD: Create and Replace (Debasmith)

* Test the size-limit boundaries: exactly `max_upload_bytes` is accepted, one byte more
  returns 413. Decide whether an empty (0-byte) file is allowed, then test and document
  that decision.
* Rejected input changes nothing in storage:
  * an invalid key or a 413 on create leaves the key absent
  * a 413 on replace leaves the old content intact
* The client's claimed content type is ignored. For example, upload `a.png` sent as
  `text/html` and check that you get `image/png` back.
* Replace changes `etag` and `size`, and a metadata request afterwards shows the new
  values.
* Real provider: upload a file larger than 8 MB (this takes the multipart path), then
  download it and compare the bytes. Record what you see.
* Translation tests: `put` returns the `FileInfo` built from the follow-up `stat`, and a
  provider rejection becomes `ProviderError`. If `Stubber` can't cleanly drive
  `upload_fileobj`, say so in the PR and cover what you can.

### OP-DOWNLOAD: Download (Vikram)

* The success test checks:
  * the bytes are identical
  * `Content-Type` comes from the key
  * `Content-Length`
  * the quoted `ETag`
  * `Content-Disposition` for a key with folders and a non-ASCII name (such as
    `docs/résumé.pdf`)
  * `X-Content-Type-Options: nosniff`
* Check on your provider what happens to an object uploaded outside the service, for
  example through the console. What content type does it come back with? Decide the
  behavior and document it.
* Real provider: download a file of several MB and compare its bytes and size.
* Translation tests: a `get_object` response becomes `FileInfo` plus chunks,
  `NoSuchKey` becomes `FileNotFound`, and the body is closed after the chunks are
  consumed.

### OP-METADATA: Metadata (Darsh)

* The success test checks all five fields and their formats:
  * `size` is an integer number of bytes
  * `etag` has no quotes
  * `last_modified` is ISO 8601 with a UTC offset
* Consistency across operations (grading section 6.1): for the same file, metadata and
  listing must report the same `key`, `size`, and `etag`. On your provider, also compare
  `last_modified` from both. They may differ in precision. If they do, document it.
* Translation tests: a `head_object` response becomes `FileInfo`, with quotes stripped
  from the ETag.
* Coordinate with Faizal: BUG-BUCKET affects delete too.

### OP-DELETE: Delete (Faizal)

* The success test checks:
  * 204 with an empty body
  * afterwards, download and metadata return 404 and the listing omits the file
  * deleting again returns 404 (our rule, which differs from S3's silent delete)
* An invalid key returns 400 and deletes nothing. Check this with another file that is
  still present afterwards.
* Real provider: delete a file, then confirm it is gone with a follow-up read, and once
  in the provider console.
* Translation tests: `delete_object` errors become `ProviderError` or
  `ProviderUnavailable`, and deleting a missing key is silent at the storage layer (the
  rule in `base.py`).

### OP-LIST: List (Prateek)

* Write partition tests following the worked example in `testing.txt`. Hard-code the
  expected results; don't compute them with the code under test.
  * n = 0, n < limit, n = limit, n = limit + 1, and limit = 1
  * create 7 files and page through them 3 at a time: every key appears exactly once,
    in sorted order
  * a prefix excludes other keys, including look-alikes (`docs/` must not match
    `docs2/`)
  * `limit` of 0, 1001, and `abc` are rejected
* Real provider: page through at least three pages and record the result. Check whether
  your provider ever returns a cursor together with an empty page.
* Translation tests: a `list_objects_v2` response becomes `FilePage`, with ETag quotes
  stripped, `content_type` set to `None`, and `NextContinuationToken` used as
  `next_cursor`.

### Bug tasks: shared process

For each bug (from `testing.txt` section 1.6), the issue records:

* the expected and observed behavior
* the smallest reproduction you found
* the cause, and the evidence for it
* the fix, and how you verified it

**Write the failing test first** and paste its failing output in the PR, then paste
the passing output after the fix. This also covers grading section 3.4 ("one test
detects a plausible defect"). If the bug does **not** reproduce on your provider,
record what you observed in the issue and in `TESTING.md`, then close the issue without
a fix.

### BUG-BUCKET: Missing bucket reported as a missing file (Darsh)

* **Likely cause.** A `head_object` response has no body, so for a missing bucket the
  SDK's error code is just `"404"`, the same as for a missing key. `s3.py` maps `"404"`
  to `FileNotFound`.
* **Reproduce it.** Start the server with `S3_BUCKET` set to a bucket that does not
  exist, then run `curl -i $B/metadata/x.txt` and `curl -i -X DELETE $B/files/x.txt`.
  * Expected: 502 `ProviderError` (a configuration problem).
  * Likely observed: 404 `FileNotFound`.
* **Fix it inside `s3.py`.** Two options:
  * (a) Check the bucket once at startup, through an explicit method that `main.py`
    calls. Don't put network calls in `S3Storage.__init__`, because `stubbed_s3` builds
    one.
  * (b) When `head_object` returns 404, call `head_bucket` to tell the two cases apart.
    This costs one extra call, only on misses.

  Pick one and explain the tradeoff in the PR. `service.py` must not change.

### BUG-CURSOR: Malformed list cursor (Prateek)

* **Observed on the memory backend:** `GET /files?cursor=garbage` returns 200 with an
  empty list.
* **Likely on S3:** the provider rejects the unknown token, and we report 502
  `ProviderError` as if the provider were misconfigured.

Both responses are wrong, because a bad cursor is the caller's mistake.
* **Contract:** a cursor this API did not produce returns 400 `InvalidInput`. Make
  both backends behave the same way and prove it with a contract test, which runs on
  both backends. Also add an HTTP test.
* Find out what happens when a cursor from one prefix is used with another prefix, and
  document it in `docs/API.md`.
* Keep provider error codes inside `s3.py`.

### ERR-400: Invalid input is always 400 `InvalidInput` (Debasmith)

* Today, an invalid key returns 400 `{"error": "InvalidInput", ...}`, but these return
  422 in FastAPI's `{"detail": [...]}` shape, which breaks our documented error format:
  * a missing `file` form field
  * `limit` out of range
  * `limit=abc`
* After this PR, every request that breaks an input rule returns 400 with
  `{"error": "InvalidInput", "detail": "<short message>"}`.
* Keep the `{"error", "detail"}` shape for now. Level 5 may revisit it.
* `/docs` and `/openapi.json` list each route's possible error statuses with our error
  body, and no longer advertise a 422 that can't happen.
* Only the HTTP layer changes: `routes.py` and `main.py`.
* Update the errors section of `docs/API.md` and the README. Add the `breaking change`
  label.
* Tests: `limit=0`, `limit=1001`, `limit=abc`, and a POST without a `file` field each
  return 400 with our body, and nothing was written to storage.

### L4-FAKE: Controlled test implementation (Vikram)

* Add `tests/fakes.py` with a test-only `StorageClient` that:
  * records every call (method and key)
  * can be told to raise a given error from a given method
  * otherwise behaves like `InMemoryStorage`, by wrapping it rather than copying it
* Make mypy prove that it satisfies `StorageClient`.
* Add HTTP tests that use it:
  * an invalid key returns 400 and the storage was **never called**
  * `stat` set to raise `ProviderUnavailable` makes `GET /metadata/...` return 503 with
    our error body
  * `put` set to raise `ProviderError` makes `POST` return 502
* Don't change anything in `src/`. Describe the fake and its assumptions in the test
  layout section of `TESTING.md`.
* This is the controlled implementation Level 5 builds on, so keep it small.

### ARCH: Provider boundary and wiring (Vikram)

Write `docs/ARCHITECTURE.md`, about two pages. Link to code instead of copying it.

* Layers and dependency direction. Which code knows about the provider (only
  `storage/s3.py`) and which code chooses it (only `main.build_storage`).
* One request traced end to end, for example `GET /metadata/{key}`: what FastAPI does,
  what our code does (validation, then the decision, then translation), and what boto3
  does.
* The interface. `storage/base.py` is the source of truth. Explain why each method
  exists (which operation needs it) and what stays hidden behind it.
* Wiring (Level 4):
  * where the real implementation is selected, created, and supplied
    (`build_storage` → `create_app` → `app.state` → `Depends(get_service)`)
  * how tests substitute another implementation
  * what would change to replace S3: one new module, one branch in `build_storage`,
    and passing the contract tests
* State and resources:
  * the boto3 client lives as long as the app
  * FastAPI owns the temp files for uploads
  * the download generator closes the provider stream
  * the service stores no data of its own
* Update the module docstring in `base.py`. Replace the README's "Layers" design note
  with a link to this doc.
* **Before merging, hold a 20-minute walkthrough with the whole team.** Everyone should
  be able to answer the questions in Level 3 section 3.7 and Level 4 section 4.6. In
  the PR, record who attended and any open questions.

### REL: Review prerelease (Faizal manages, Prateek verifies)

* Follow "Releases" in `CONTRIBUTING.md`. Suggested tag: `v0.1.0-rc.1`, marked as a
  **prerelease**. Make the version in `pyproject.toml` match it (`0.1.0rc1`). Add a
  line to `CONTRIBUTING.md` explaining how prerelease tags are named.
* Run the full provider suite on OCI against the exact commit you will tag.
* Release notes:
  * the behavior included
  * the issues and PRs included
  * the breaking change from ERR-400
  * which providers each operation was verified on
  * known gaps (at least Level 5, plus anything unfinished here)
  * a link to the CI run for the tagged commit
* Prateek verifies the release from a fresh clone of the tag, in a new directory,
  following only the README. He records the steps and results in the release issue.
* After the release, Faizal records one observation about our workflow and any change
  we'll make (introduction section 2.5).

## 8. Done for this round

* [ ] Each operation has one owner, a complete contract in `docs/API.md`, and an HTTP
  success test that checks every promised field (Level 1).
* [ ] Each operation has a provider-marked HTTP test and a recorded manual verification
  against a real bucket. At least two people have run each operation against a real
  provider (Level 2).
* [ ] Each `StorageClient` method has a full contract docstring. Translation tests run
  without network. `docs/ARCHITECTURE.md` is merged, and the team has done the
  walkthrough (Level 3).
* [ ] The tests substitute a controlled implementation that can be told to fail.
  `uv run pytest` needs no network or credentials. Everyone can explain where the
  provider is chosen and how it reaches the app (Level 4).
* [ ] BUG-BUCKET and BUG-CURSOR are fixed, or closed with recorded evidence.
* [ ] `v0.1.0-rc.1` is published as a prerelease and verified from a fresh checkout.

## 9. Not in this round

These come later. Don't let your agent start them:

* Level 5: the final error model, structured failure logging, retry guidance in logs
* optional extensions (caching, idempotency keys, and so on)
* reviewing our sister team (it has its own plan, after the review release)
* the write-ups on one design decision and the cost of one operation (due with the
  final release)
* new backends, such as Azure Blob Storage, and switching providers at runtime
