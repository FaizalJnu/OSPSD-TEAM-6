# Testing

How to run the checks, how the tests are organized, and what each operation's tests
establish. The contract they check is in [docs/API.md](docs/API.md).

## Commands

```bash
uv sync                                              # install the locked dependencies first
uv run pytest                                        # fast tests: no network, no credentials
uv run --env-file .env pytest -m provider            # only the tests that use your real bucket
uv run ruff check . && uv run ruff format --check .  # lint and formatting
uv run mypy                                          # type check (strict on src/)
```

To fix lint and formatting problems in place, run
`uv run ruff check --fix . && uv run ruff format .`.

To run part of the suite, pass a file or a name filter, for example
`uv run pytest tests/test_delete.py` or `uv run pytest -k cursor`.

CI runs the lint, format, type, and fast test checks on every pull request, every push
to `main`, and every release tag. CI has no provider credentials, so the provider
tests never run there.

## Provider tests

Tests that need a real bucket are marked `provider` and are left out of the fast
suite. With `-m provider`, they fail (rather than skip) if `.env` does not configure
`STORAGE_BACKEND=s3`. They write only under `contract-tests/` and `api-tests/` and
delete their files afterwards.

* **Prerequisites:** a bucket and keys in `.env`. Follow the README's
  [OCI steps](README.md#connect-a-real-provider-oci-object-storage), or see
  [docs/PROVIDERS.md](docs/PROVIDERS.md) for other providers.
* **Selection:** `pyproject.toml` sets `addopts = "-m 'not provider' --strict-markers"`.
  A `-m` on the command line replaces the one there. `--strict-markers` turns a
  misspelled marker into an error instead of a test that silently runs in the fast
  suite.
* **Marking:** mark every test that needs a bucket with `@pytest.mark.provider`.
* **Interrupted runs:** delete anything left under `contract-tests/` or `api-tests/`.

## Test layout

| File | What it covers |
|---|---|
| [tests/conftest.py](tests/conftest.py) | Shared fixtures (below) |
| [tests/test_upload.py](tests/test_upload.py) | Create and Replace: `POST` and `PUT /files/{key}` |
| [tests/test_download.py](tests/test_download.py) | Download: `GET /files/download?path=` |
| [tests/test_metadata.py](tests/test_metadata.py) | Metadata: `GET /metadata/{key}` |
| [tests/test_bucket_errors.py](tests/test_bucket_errors.py) | FIX-2: missing/denied buckets, probe failures, and HTTP checks before writes |
| [tests/test_delete.py](tests/test_delete.py) | Delete: `DELETE /files?path=` |
| [tests/test_move.py](tests/test_move.py) | Move: `PATCH /files?path=` |
| [tests/test_list.py](tests/test_list.py) | List: `GET /files` |
| [tests/test_service.py](tests/test_service.py) | The key and path rules and the content-type choice, without HTTP |
| [tests/test_storage_contract.py](tests/test_storage_contract.py) | The same tests for every storage backend |
| [tests/test_invalid_input.py](tests/test_invalid_input.py) | Invalid input that FastAPI rejects first (a bad List `limit`, a missing `file` field) returns 400 `InvalidInput` |
| [tests/test_injection.py](tests/test_injection.py) | Application tests over a controlled backend: storage calls made, provider failures, how the app is built, and the routes it serves |
| [tests/test_failures.py](tests/test_failures.py) | The error model across operations (Level 5): access denial, sanitized errors, the failure log, errors outside any operation (no route, wrong method, unreadable body, a bug), and the errors `/openapi.json` lists |
| [tests/fakes.py](tests/fakes.py) | `FakeStorage`, the controlled backend (below) |
| [tests/test_cleanup.py](tests/test_cleanup.py) | `delete_everything_under`, the cleanup helper the provider tests rely on |

Each operation's file holds all of that operation's tests. There are three kinds:

| Kind | Fixture | Needs | What it shows |
|---|---|---|---|
| HTTP behavior | `client` | Nothing | Statuses, bodies, headers, and effects through the API, on the in-memory backend |
| Translation | `stubbed_s3` | Nothing | How `S3Storage` turns provider responses and errors into our types and errors |
| Real provider | `provider_client`, marked `provider` | A bucket in `.env` | The operation end to end against a real provider |

Add tests to your own operation's file. A fixture that only one operation needs goes
in that file, not in `conftest.py`.

### Controlled storage

[`FakeStorage`](tests/fakes.py) is a `StorageClient` for application tests. The
`fake` and `fake_client` fixtures build the app over it with
`create_app(FileService(fake, max_upload_bytes=...))`. It:

* records each call in `fake.calls` as `(method, key)`, in order. `list_files` records
  its prefix instead of a key, `delete_many` its keys joined with commas, and `copy`
  its source key.
* raises a given error from a given method after `fake.fail(method, error)`, on every
  later call. The method name is typed, so mypy rejects a misspelled one. The error is
  usually one of ours, but can be any exception, to stand in for a bug in a backend.
  With `after_calls=n`, the first `n` calls succeed, like a provider that fails partway
  through a series of calls.
* leaves the keys in `fake.refused_keys` in place and has `delete_many` report them as
  failed, like S3's `DeleteObjects` when it answers 200 and lists failures in its body.
* with `fake.cut_downloads(error, after_bytes=n)`, lets every later `get` succeed but
  makes its chunks raise `error` after the first `n` bytes, like a provider connection
  that drops while the body is being read.
* with `fake.fail(method, error, after_applying=True)`, applies the call to the store
  first and then raises, like a provider that completed a write but whose response was
  lost. Without it, the error is raised before the store is touched.
* otherwise passes each call to a wrapped `InMemoryStorage`.

mypy checks that it satisfies `StorageClient` through a typed assignment at the end of
the file. Its assumptions:

* Without a configured failure, it behaves exactly like `InMemoryStorage`, which
  `tests/test_storage_contract.py` checks against the real provider.
* A raised failure is either all or nothing: the call changes nothing, or the whole
  change is made. A real provider can fail in other ways too, such as a multipart upload
  left unfinished, which the fake does not model. The only partial result it models is
  `refused_keys`.

`after_applying` tests the "After a failed write" contract in
[docs/API.md](docs/API.md#after-a-failed-write), that a 502 or 503 from a write does not
prove nothing changed:

* [`test_create_that_stores_the_file_then_fails_returns_503_and_a_retry_is_409`](tests/test_upload.py):
  `put` stores the file and then raises `ProviderUnavailable`. Create returns 503,
  Metadata then returns 200, and a retried Create returns 409.
* [`test_delete_that_removes_the_file_then_fails_returns_503_and_a_retry_is_404`](tests/test_delete.py):
  `delete` removes the file and then raises `ProviderUnavailable`. Delete returns 503,
  Metadata then returns 404, and a retried Delete returns 404.

`tests/test_storage_contract.py` runs the same tests against every storage backend to
check that the in-memory test double behaves like the real provider. They check the
rules written in `storage/base.py`. The `memory` run is part of the fast suite; the
`s3` run is marked `provider`.

## Fixtures

From [tests/conftest.py](tests/conftest.py):

* **`client`:** a `TestClient` for a fresh app over empty in-memory storage, so tests
  never share state. Its upload limit is `MAX_UPLOAD_BYTES`, 1024 bytes, so size tests
  stay small.
* **`fake` and `fake_client`:** a fresh [`FakeStorage`](#controlled-storage), and a
  `TestClient` for an app over it with the same upload limit as `client`. Configure
  failures on `fake` and read `fake.calls` to check which storage calls a request made.
* **`send_file(client, method, key, data)`:** a helper, not a fixture. Sends `data` to
  `/files/{key}` as the `file` form field, with `method` `"POST"` or `"PUT"`.
* **`stubbed_s3`:** a `StubbedS3(storage, stubber)` pair. `storage` is a real
  `S3Storage` with dummy credentials and bucket `test-bucket`. `stubber` is botocore's
  `Stubber`, wrapped around that storage's boto3 client. Queue each expected provider
  call with `stubber.add_response(...)` or `stubber.add_client_error(...)`, then call
  the storage method. A call with nothing queued fails the test instead of reaching the
  network, and so does a queued response that was never used.
* **`provider_client`:** a `TestClient` for the app built the way production builds it
  (`create_app()` reading the environment), against the bucket in `.env`. It fails
  rather than skips unless `STORAGE_BACKEND=s3`. Use it only in tests marked
  `provider`.
* **`provider_prefix`:** a unique prefix per test, `api-tests/<random hex>/`. Put every
  key a provider test writes under it. `provider_client` deletes everything there
  afterwards through a separate storage client, even when the test fails.
* **`delete_everything_under(storage, prefix)`:** a helper that deletes every file
  under `prefix`, following every page of the listing. `provider_client` and the
  contract tests clean up with it.
* **`load_provider_settings()`:** a helper that returns the settings from the
  environment, or fails the test with a hint if they do not configure the `s3`
  backend. The contract tests use it too.

[tests/test_delete.py](tests/test_delete.py) has examples for `client`, `fake_client`,
`stubbed_s3`, and `provider_client`.

## Recording a real-provider verification

Each operation's "Real-provider verification" section holds one record per manual run
against a real bucket. Each operation needs records from at least two people. Copy this
template:

````markdown
#### Run by <your name>

- Provider: <provider and region, for example OCI Object Storage, us-ashburn-1>
- Date: <YYYY-MM-DD>
- Commit: <output of `git rev-parse --short HEAD`>
- Request: <the exact curl command>
- Expected: <status and body, or the effect, as docs/API.md promises>
- Observed:
  ```text
  <the output you got>
  ```
- Cleanup: <what you deleted afterwards, and how you checked it was gone>
````

Before pasting output, remove keys and anything that identifies your account, such as
the OCI namespace and the bucket name.

## Known bugs and gaps

* Known provider bugs, with their reproductions and planned fixes, are in
  [fixesRequired.md](fixesRequired.md).
* The provider tests never run in CI. The release manager runs them before each
  release (see "Releases" in [CONTRIBUTING.md](CONTRIBUTING.md)).

Gaps that belong to one operation go in that operation's section.

## Missing-bucket regression (FIX-2)

Owner: **Darsh Shani**. Tests: [test_bucket_errors.py](tests/test_bucket_errors.py).
This regression spans metadata and the shared existence check used by create,
replace, and delete, so it has a separate test file rather than duplicating
the same provider setup in each operation's tests.

### Expected behavior and cause

A HEAD object response can represent a missing key and a missing bucket with
the same generic 404. Previously, every such response became `FileNotFound`,
so a broken bucket configuration incorrectly produced HTTP 404 for metadata,
delete, and replace. The regression test reproduced metadata returning 404
when its expected status was 502, without network or credentials.

`S3Storage.stat` now probes `head_bucket` only after ambiguous 404/NotFound
object errors. A successful probe confirms the bucket is accessible and the
original error becomes `FileNotFound`. A failed probe is translated as
`ProviderError` or `ProviderUnavailable`, never as a missing file. Since Level 5, a
probe the provider answers with 403 is `AccessDenied` instead (see
[Error model and failure logs](#error-model-and-failure-logs-level-5)). Any other
failed probe does not establish whether the bucket is absent or access is denied.

The change stays in [storage/s3.py](src/storage_service/storage/s3.py).
`service.py`, startup wiring, and the shared error translator are unchanged.
Compared with a startup check, the probe keeps startup free of network calls
and handles bucket failures discovered after startup. It costs an extra SDK
call on each ambiguous miss and needs bucket-read permissions. Every successful
Create on a provider returning generic HEAD 404s pays this extra call, because
its existence check must miss. Separate HEAD calls are not an atomic snapshot.

### Verification

Offline cases cover both generic error codes, accessible versus missing or
denied buckets, probe connection failure, and unchanged successful metadata,
explicit `NoSuchKey`, and object permission-denial paths. HTTP tests check
GET metadata, DELETE, PUT, and POST return 502 before a write; only HEAD calls
are queued in Stubber, so an attempted upload or delete fails the test.

```bash
uv run pytest tests/test_bucket_errors.py
uv run --env-file .env pytest -m provider tests/test_bucket_errors.py
```

The provider suite uses a unique bucket name that is never created to check
metadata, delete, and replace errors. A second test checks a missing file in
the configured real bucket still returns 404. It does not modify the configured
bucket or its contents.

### Real-provider evidence and gaps

Run from Darsh's Windows checkout with Codex assistance on **2026-10-14**,
against OCI Object Storage in **us-ashburn-1**, using Darsh's own private test
bucket and keys from the ignored local `.env`.

Before the fix, source commit `0453b66` (metadata branch, unchanged S3 adapter)
was exercised through `TestClient(create_app(build_service(settings)))` with
the bucket changed only in memory to a unique nonexistent name. Observed:

| Request | Expected | Observed before the fix |
|---|---|---|
| `GET /metadata/missing.txt` | 502 `ProviderError` | 404 `FileNotFound` |
| `DELETE /files/missing.txt` | 502 `ProviderError` | 404 `FileNotFound` |
| `PUT /files/missing.txt` with a file form field | 502 `ProviderError` | 404 `FileNotFound` |

All three returned `{"error": "FileNotFound", "detail": "no file named 'missing.txt'"}`.
The original `.env` was unchanged, and no bucket was created or modified.

The original post-fix run used a pre-squash local commit that was not reachable
from the PR branch. It is superseded by the following run.

#### Review follow-up, 2026-10-20

- Run with Codex using Darsh's configured OCI test provider.
- Source commit: `46910b00fe7914912cb5b1dab0a09d2b6d850f2e` on
  `22-missing-bucket`, including `dev` at `fd2d127`. This is a committed ancestor
  of the documentation record, not a discarded pre-squash commit. The latest
  branch-head verification is also recorded in PR #23.
- Before the error-detail change: **11 failed, 6 passed, 2 deselected** in
  `tests/test_bucket_errors.py`. The assertions observed raw `(404)`, `(NotFound)`,
  `(NoSuchBucket)`, or `(403)` details instead of the clear bucket message.
- After the change: **120 passed, 15 deselected** in the fast suite, including
  all 17 offline bucket cases. Ruff lint, Ruff format check (42 files), and
  mypy (31 files) passed.
- Live provider result on that source commit: **2 passed, 17 deselected**.
  Missing buckets returned 502 with detail "the configured bucket does not
  exist or is not accessible" for GET metadata, DELETE, and PUT. A missing key
  in the accessible bucket remained 404 `FileNotFound`. No objects were written.
- The existing virtualenv's Windows launcher was blocked by application control,
  including outside the sandbox. Checks therefore used installed CPython 3.13.16
  with that virtualenv's existing packages and this checkout's `src` on
  `PYTHONPATH`. No dependency, lockfile, or check configuration changed.
- Provider access was blocked inside the sandbox; rerunning with network access
  passed. Tracebacks and captured output were suppressed to keep account details
  out of the record. The ignored `.env` was neither changed nor displayed.

Commands from this worktree (the env-file path points to the main checkout):

```powershell
$env:PYTHONPATH = "$PWD\.venv\Lib\site-packages;$PWD\src"
$python = '../../../.tools/python/cpython-3.13.16-windows-x86_64-none/python.exe'
& $python -m pytest --tb=short --show-capture=no
& $python -m ruff check .
& $python -m ruff format --check .
& $python -m mypy
& '../../../.tools/uv/uv.exe' run --no-project --offline --python $python `
  --env-file '../../../OSPSD-TEAM-6/.env' python -m pytest -m provider `
  tests/test_bucket_errors.py --tb=no --show-capture=no -p no:cacheprovider
```

The normal command in a single checkout with a working virtualenv launcher remains
`uv run --env-file .env pytest -m provider tests/test_bucket_errors.py`.

`test_nonexistent_real_bucket_is_a_provider_error` observed 502 `ProviderError`
with the public error shape for all three requests above. It used a unique
bucket name that was never created. `test_missing_file_in_real_bucket_remains_404`
observed 404 `FileNotFound` for a unique nonexistent key in the accessible test
bucket. Both checks passed; the provider fixture also completed cleanup.

No objects were written by these checks. Provider tests remain explicitly
selectable and fail rather than skip if configuration is missing.

#### Run by Faizal Rahman (second verifier)

- Provider: OCI Object Storage, us-ashburn-1, Faizal's own test bucket
- Date: 2026-10-21
- Commit: `cb623aa` (`dev`, after #23 merged)
- Provider command: `uv run --env-file .env pytest -m provider tests/test_bucket_errors.py`
- Provider result: `2 passed, 17 deselected`
- Request: the same requests as the two provider tests, through
  `TestClient(create_app(build_service(settings)))`. First with the bucket changed in
  memory to a unique name that was never created, then with the configured bucket and
  a key under a fresh prefix
  `P=api-tests/manual-fix2-65294909ff294e52b316fb2066b6dbff/`.
- Expected: with the missing bucket, 502 `ProviderError` with detail "the configured
  bucket does not exist or is not accessible" for Metadata, Delete, and Replace. With
  the configured bucket, a missing key is still 404 `FileNotFound`. See
  [Bucket checks](docs/API.md#bucket-checks).
- Observed (the configured-bucket key shortened to `P/missing.txt`):
  ```text
  missing bucket  GET    /metadata/missing.txt    502 {"error":"ProviderError","detail":"the configured bucket does not exist or is not accessible"}
  missing bucket  DELETE /files/missing.txt       502 {"error":"ProviderError","detail":"the configured bucket does not exist or is not accessible"}
  missing bucket  PUT    /files/missing.txt       502 {"error":"ProviderError","detail":"the configured bucket does not exist or is not accessible"}
  real bucket     GET    /metadata/P/missing.txt  404 {"error":"FileNotFound","detail":"no file named 'P/missing.txt'"}
  ```
- Cleanup: nothing was written. The missing bucket was never created, and
  `GET /files?prefix=P` afterwards returned `{"files":[],"next_cursor":null}`.

## Error model and failure logs (Level 5)

Contract: [Errors](docs/API.md#errors) in docs/API.md, including
[What stays internal](docs/API.md#what-stays-internal) and
[Failure logs](docs/API.md#failure-logs). Tests:
[tests/test_failures.py](tests/test_failures.py), plus the translation tests in each
operation's file.

### Contract checked

* A caller can tell the failure classes apart from `error` alone: 400 `InvalidInput`,
  403 `AccessDenied`, 404 `FileNotFound`, and 502 `ProviderError` or 503
  `ProviderUnavailable`.
* Any provider 403 (`AccessDenied`, `SignatureDoesNotMatch`, a bodiless HEAD `403`, and
  so on) becomes `AccessDenied`, on every operation.
* No response contains the provider's code or message. The code is kept on the error as
  `provider_code` for the log.
* Every error response is `{"error", "detail"}` with a type from the
  [Error types](docs/API.md#error-types) table, including those Starlette raises
  itself: a path with no route is 404 `RouteNotFound`, a method the path does not
  accept is 405 `MethodNotAllowed` with every allowed method in `Allow`, and a
  multipart body that cannot be read is 400 `InvalidInput` with no storage call.
* A bug is 500 `InternalError`, and the response does not contain the exception's text.
* Every failed request logs exactly one JSON line whose `status`, `error`, and `detail`
  match the response, without the provider's message. Only a 500 has a traceback.
* The log claims no more than we know: `operation` is `null` when no operation ran (404
  `RouteNotFound`, 405 `MethodNotAllowed`), and after a 500, `provider_involved` is
  `null` and a write's `write_outcome` is `unknown`.
* `/openapi.json` lists each route's error statuses with the error body, and no 422.
* A download that fails after its 200 headers is left unfinished, so the caller
  receives fewer bytes than `Content-Length`. It logs one line with `"status": 200`,
  `"interrupted": true`, `bytes_sent`, and `size`, at `ERROR`.
* For Create, Replace, and Delete, `write_outcome` is `not_attempted` when the request
  failed before the write call, and `unknown` when the write call failed.

### Tests

All in [tests/test_failures.py](tests/test_failures.py), over `FakeStorage` unless
noted:

* `test_a_successful_request_logs_nothing`
* `test_invalid_input_is_logged_as_rejected_before_the_provider`: 400, `WARNING`,
  `provider_involved` false, no `write_outcome` for a read, and no storage call.
* `test_input_fastapi_rejects_is_logged_like_our_own`: `limit=abc` is logged as
  `list_files`, 400 `InvalidInput`.
* `test_a_missing_file_is_logged_as_reported_by_the_provider`: 404, `storage_call`
  `stat`.
* `test_access_denied_is_403_and_logged_for_whoever_runs_the_service`: 403 with the
  full body, logged at `ERROR` with `provider_code`.
* `test_a_write_that_failed_in_its_check_is_logged_as_not_attempted`: Delete whose
  `stat` is unavailable: 503, `not_attempted`, and `delete` never called.
* `test_a_write_that_failed_in_the_write_call_is_logged_as_unknown`: Create whose `put`
  stores the file and then fails: 503, `unknown`, and Metadata then finds the file.
* `test_a_folder_delete_that_failed_while_listing_is_logged_as_not_attempted`: 503,
  `storage_call` `list_files`, `not_attempted`.
* `test_a_folder_delete_that_stopped_partway_is_logged_as_unknown`: a batch reports a
  failed key: 502, `storage_call` `delete_many`, `unknown`.
* `test_a_create_refused_by_our_own_rules_is_logged_as_not_attempted`: 413
  (`provider_involved` false) and 409 (true, decided by the existence check).
* `test_provider_messages_stay_out_of_responses_and_logs` (`stubbed_s3`): a
  `NoSuchBucket` whose message names a namespace and bucket. The response is the
  generic 502, the log has `provider_code` `NoSuchBucket`, and neither contains the
  namespace, the bucket, or a traceback.
* `test_a_path_with_no_route_is_route_not_found_not_a_missing_file`: `GET /nothing`
  is 404 `RouteNotFound`, logged at `WARNING` with `operation` `null`.
* `test_a_method_the_path_does_not_accept_is_405_with_every_allowed_method`: `POST
  /files` gives `Allow: GET`, and `PATCH /files/notes.txt` gives `Allow: DELETE, GET,
  POST, PUT`. Starlette's own header named only `POST`, the first route matching the
  path. `operation` is `null`, although Starlette matched the path to another route.
* `test_a_multipart_body_that_cannot_be_read_is_invalid_input`: Create and Replace
  with no boundary, 1001 files, or a text field over 1 MB (Starlette's limits) return
  400 `InvalidInput` with `file: ` and the parser's message, `write_outcome`
  `not_attempted`, and no storage call.
* `test_a_bug_is_a_500_internal_error_that_claims_nothing_about_the_write`: `put`
  raises a `RuntimeError`. Create returns 500 `InternalError` without the exception's
  text, and the log line has the traceback, `provider_involved` `null`, and
  `write_outcome` `unknown`.
* `test_a_storage_error_with_no_status_of_its_own_is_an_internal_error`: raising the
  base `StorageError` is a bug, so it is 500 `InternalError` too, not an `error` named
  `StorageError`.
* `test_openapi_lists_each_routes_errors_with_our_body_and_no_422`: pins each route's
  error statuses to its Errors table in docs/API.md, plus 500, each with the
  `ErrorBody` schema, and checks that no 422 or `HTTPValidationError` is left.
* `test_a_download_cut_off_after_its_headers_is_left_unfinished_and_logs_the_200`:
  `FakeStorage` cuts a 100-byte download off after 11 bytes, with `ProviderUnavailable`
  or with a bug. The app is run the way uvicorn runs it, because TestClient shows an
  unfinished response as an empty body. It sends 200 with `content-length: 100`, then
  11 bytes, and never the message that ends the body. The log line has
  `"status": 200`, `storage_call` `get` (or `null` for the bug), `interrupted`,
  `bytes_sent` 11, and `size` 100. Only the bug's line has a traceback.
* `test_wrong_credentials_are_access_denied_on_the_real_provider` (marked `provider`):
  with a wrong secret key, Metadata, List, and Create return 403 `AccessDenied`, and
  nothing is written.

The first tests here failed on `dev` at `a9b8258`: they could not import
`AccessDenied`. The six tests for errors outside any operation, bugs, and `/openapi.json`
(12 cases) fail on `dev` at `d80e145`, which returned FastAPI's own bodies, a plain-text
500, `"error": "StorageError"`, `Allow: POST` for `PATCH /files/notes.txt`, and a 422 on
every route. The interrupted-download tests fail on `59788d2` (step B of
[#69](https://github.com/FaizalJnu/OSPSD-TEAM-6/issues/69)), where the failure reached
the 500 handler and was logged as a 500.

### Real-provider verification

#### Run by Faizal Rahman, with Claude Code

- Provider: OCI Object Storage, us-ashburn-1, Faizal's own test bucket
- Date: 2026-10-21
- Commit: `a9b8258`, plus this branch's changes
- Provider command: `uv run --env-file .env pytest -m provider`
- Provider result: `16 passed, 144 deselected`, including the wrong-credentials test
  and FIX-2's missing-bucket test.
- Observed failure logs (keys shortened to `P/`):
  ```text
  {"level": "ERROR", "event": "request_failed", "operation": "get_metadata", "status": 403, "error": "AccessDenied", "detail": "the storage provider denied access", "provider_involved": true, "storage_call": "stat", "provider_code": "403"}
  {"level": "ERROR", "event": "request_failed", "operation": "list_files", "status": 403, "error": "AccessDenied", "detail": "the storage provider denied access", "provider_involved": true, "storage_call": "list_files", "provider_code": "SignatureDoesNotMatch"}
  {"level": "ERROR", "event": "request_failed", "operation": "create_file", "status": 403, "error": "AccessDenied", "detail": "the storage provider denied access", "provider_involved": true, "storage_call": "stat", "provider_code": "403", "write_outcome": "not_attempted"}
  {"level": "ERROR", "event": "request_failed", "operation": "delete_file", "status": 502, "error": "ProviderError", "detail": "the configured bucket does not exist or is not accessible", "provider_involved": true, "storage_call": "stat", "provider_code": "404", "write_outcome": "not_attempted"}
  {"level": "WARNING", "event": "request_failed", "operation": "get_metadata", "status": 404, "error": "FileNotFound", "detail": "no file named 'P/missing.txt'", "provider_involved": true, "storage_call": "stat", "provider_code": "404"}
  ```
  No line names the namespace or bucket, and none has a traceback.
- Cleanup: the provider fixtures emptied their prefixes. The wrong-credentials test
  checked that its prefix stayed empty.

### Gaps

* Starlette passes a 500's exception on to the server after our handler, so uvicorn
  prints the traceback a second time (`Exception in ASGI application`). Seen with a
  backend whose `stat` raised `KeyError` under uvicorn: one JSON line with its
  traceback, then uvicorn's.
* The 500 test raises from one storage call. Every bug reaches the same handler,
  wherever it happens, but only this path is tested.
* `write_outcome` is `unknown` for any failure of the write call, including an explicit
  403 from it. That is conservative: a refused write most likely changed nothing.
* Throttling and provider-side 5xx errors are still 502 `ProviderError` (F1).

## Filling in an operation section

* **Contract checked:** which promises in [docs/API.md](docs/API.md) the tests
  establish.
* **Cases and boundaries:** the input categories and boundary values you chose, and
  why.
* **Tests:** a link to each test, with what it asserts.
* **Real-provider verification:** records in the format above.
* **Provider observations:** provider behavior that surprised you, or that differs
  between providers. If it breaks our contract, open a bug issue and link it.
* **Gaps:** what is not tested, and why.

## Create and Replace

Owner: **Debasmith Mandal**. Contract: [docs/API.md](docs/API.md#create-and-replace).
Tests: [tests/test_upload.py](tests/test_upload.py).

### Contract checked

On the in-memory backend, through HTTP: the success statuses (201 and 200), all five
file info fields and their formats, that Metadata afterwards agrees with the write,
every error status that bad input can cause (400, 404, 409, 413), that rejected
requests change nothing, and that the server, not the client, picks `content_type`.
Without network, through `stubbed_s3`: how `S3Storage.put` turns the provider's replies
into `FileInfo` and its rejections into `ProviderError`.

### Cases and boundaries

* Size: 0 bytes (allowed), exactly the limit (accepted), one byte over (413). The test
  app's limit is 1024 bytes, so these files stay small.
* Existence: Create on a free key and on a taken key; Replace on an existing key and on
  a missing one.
* Rejected requests: an invalid key stores nothing; a 413 on Replace keeps the old
  contents and info.
* Content type: a `.png` key sent as `text/html` is stored and served as `image/png`.
* Provider boundary: a successful upload with its follow-up `head_object`, and an
  upload the provider rejects.

### Tests

All in [tests/test_upload.py](tests/test_upload.py):

* `test_upload_then_download_returns_identical_bytes`: the bytes survive a round trip.
* `test_create_returns_every_field_and_metadata_agrees`: 201, all five fields with
  their formats, and Metadata returns the same info.
* `test_create_refuses_to_overwrite`: 409, and the first contents stay.
* `test_replace_overwrites_an_existing_file`: 200, and the new contents download.
* `test_replace_changes_etag_and_size`: new `size` and `etag`, and Metadata agrees.
* `test_replace_of_a_missing_file_is_404`
* `test_upload_of_exactly_the_limit_is_accepted`
* `test_upload_over_the_limit_is_413`: and nothing is stored.
* `test_replace_over_the_limit_keeps_the_old_contents`
* `test_empty_file_is_allowed`: 201, size 0, and an empty download.
* `test_invalid_key_is_400`: and nothing is stored.
* `test_client_content_type_is_ignored`
* `test_s3_put_returns_the_info_from_its_follow_up_stat`: also checks that ETag quotes
  are stripped.
* `test_s3_put_turns_a_permission_denial_into_access_denied`
* Both stub tests pin `put_object`'s parameters (bucket, key, content type, and no
  checksum parameter), so they fail if FIX-1's checksum setting is removed.
* `test_create_and_replace_against_the_real_provider` (`provider`): Create, Replace, a
  download, and Metadata against a real bucket.
* `test_multipart_upload_round_trips_against_the_real_provider` (`provider`): a 9 MiB
  upload, which takes the multipart path, downloads byte-identical.

### Real-provider verification

#### Run by Debasmith Mandal: multipart Create

- Provider: OCI Object Storage, us-ashburn-1 (team test bucket), with the FIX-1 checksum
  settings in `.env`
- Date: 2026-10-14
- Commit: `b95bf89`
- Request: 12 MiB of random bytes (`head -c 12M /dev/urandom > big.bin`), uploaded with
  `curl -F "file=@big.bin" $B/files/manual-debasmith/big.bin`, then downloaded, compared,
  checked with Metadata, and deleted.
- Expected: 201 with `size` 12582912 and `content_type` `application/octet-stream`
  (unknown extension); a byte-identical download; Metadata returning the same info; 204
  on delete, then 404.
- Observed:
  ```text
  POST            201 {"size":12582912,"content_type":"application/octet-stream","etag":"fcfc631d29e14c4a4c16d95db5adc40c-2",...}
  cmp             byte-identical
  sha256          9de6a5528d329354a431bc33a6bbc01514d302729a6efbf0d602cbe0c393cdbe for both files
  GET /metadata   200, same info as the POST response
  DELETE          204
  GET /metadata   404 {"error":"FileNotFound","detail":"no file named 'manual-debasmith/big.bin'"}
  ```
- Cleanup: deleted through the API; the final 404 confirms it. Local files removed.

#### Run by Debasmith Mandal: Replace

- Provider: OCI Object Storage, us-ashburn-1 (team test bucket), with the FIX-1 checksum
  settings in `.env`
- Date: 2026-10-14
- Commit: `b95bf89`
- Request: Create `manual-debasmith/notes.txt` containing `first`, Replace it with
  `second, longer` (`curl -X PUT -F "file=@b.txt" ...`), download it, delete it.
- Expected: Create returns 201 with size 5; Replace returns 200 with size 14 and a new
  `etag`; the download returns `second, longer`; Delete returns 204.
- Observed (statuses from the server log; repeated twice with the same results):
  ```text
  POST    201 {"size":5,"content_type":"text/plain","etag":"8b04d5e3775d298e78455efc5ca404d5","last_modified":"2026-10-14T20:40:45Z"}
  PUT     200 {"size":14,"content_type":"text/plain","etag":"db68a5436e7587753f2f604eb05707b5","last_modified":"2026-10-14T20:40:45Z"}
  GET     second, longer
  DELETE  204
  ```
- Cleanup: deleted through the API (204). Local files removed.

#### Run by Darsh Shani: Create, Replace, and multipart round trip

- Provider: OCI Object Storage, us-ashburn-1, using Darsh's own private test bucket
  and the existing ignored `.env`. Executed with Codex assistance.
- Date: 2026-10-20 (America/New_York).
- Source commit: `fd2d127f5a9cf0e0fc3a4af0b04ea764a997e561` (`dev`). The
  verification branch starts at this commit; this record changes documentation only.
- Configuration: the documented FIX-1 workaround was applied to the test process:
  `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` and
  `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required`. The effective SDK configuration
  confirmed both values. No `.env`, source, dependency, or check configuration was
  changed. This run does not verify that the production FIX-1 change has landed.
- Test selection:
  ```bash
  uv run --env-file .env pytest -m provider tests/test_upload.py
  ```
  On this Windows machine, application control blocks the virtualenv's Python
  launcher. The run used installed CPython 3.13.16 with the existing locked
  environment's packages and this checkout's `src` on `PYTHONPATH`, with uv loading
  the main checkout's `.env`. A local audit helper invoked the existing pytest
  selection, observed each `provider_prefix` fixture without replacing it, and
  checked those prefixes after all fixture teardown. The command from the worktree
  was:
  ```powershell
  $env:PYTHONPATH = "$PWD\..\missing-bucket\.venv\Lib\site-packages;$PWD\src"
  & '../../../.tools/uv/uv.exe' run --no-project --offline `
    --python '../../../.tools/python/cpython-3.13.16-windows-x86_64-none/python.exe' `
    --env-file '../../../OSPSD-TEAM-6/.env' python '../../../.tools/r17_verify.py'
  ```
  The helper calls `pytest.main` with `-m provider tests/test_upload.py --tb=no
  --show-capture=no -p no:cacheprovider`; it does not replace test functions, app
  wiring, or provider calls. Account identifiers and credentials are omitted from
  the evidence.
- Expected and observed (all assertions passed):

  | Existing test | Expected | Observed |
  |---|---|---|
  | `test_create_and_replace_against_the_real_provider` | Create `first`: 201, size 5. Replace with `second, longer`: 200, size 14, changed ETag. Download matches the replacement bytes; Metadata equals the replacement info. | Pass |
  | `test_multipart_upload_round_trips_against_the_real_provider` | Create 9 MiB (9437184 bytes): 201 and matching size. Download is byte-identical. This exceeds boto3's 8 MB multipart threshold. | Pass |

  Pytest reported **2 passed, 14 deselected**. The first audit invocation also
  reported one `PytestAssertRewriteWarning` for already-imported `anyio`, caused by
  importing the app before pytest initialized its plugins; no test failed.
- Cleanup: the existing provider fixture deleted its objects. A separate storage
  client then queried each exact prefix with `list_files(prefix, 1000, None)`:

  | Test prefix | Files remaining | `next_cursor` |
  |---|---|---|
  | `api-tests/1cd2a2f838724deda8864c658409c0df/` | 0 | `null` |
  | `api-tests/9bcbf96d5ce54919943440978764c2f5/` | 0 | `null` |

  Only test-prefixed objects were created, replaced, and deleted. No local upload
  files were created: both tests use in-memory bytes.
- Scope: this is a second runner's automated HTTP/provider verification for Create
  and Replace, alongside Debasmith's records above. It does not add live checks of
  error cases, concurrency, or the 1 GiB boundary.

### Provider observations

- OCI returns AWS-style multipart ETags: a 12 MiB upload came back as `<hash>-2`, two
  parts at boto3's 8 MB part size.
- Single-part ETags are the MD5 of the contents (`8b04d5...` is the MD5 of `first`);
  multipart ETags are not.
- `last_modified` has one-second precision: a Create and a Replace in the same second both
  reported `20:40:45Z`. Compare `etag`, not `last_modified`, to detect a change.
- OCI rejects boto3's default upload checksum (`NotImplemented`: aws-chunked encoding not
  supported), which returned 502 for every upload before FIX-1. `S3Storage` now sends
  checksums only when an operation requires them.

### Gaps

* Error cases (409, 413) and files near the 1 GiB limit have not been run on OCI.
* The race between the existence check and the write is documented in
  [docs/API.md](docs/API.md#create-and-replace) but not tested.
* The multipart path is covered only by the `provider` test and the manual run, not by
  the fast suite.

## Download

Owner: **Vikram Markali**. Contract: [docs/API.md](docs/API.md#download).
Tests: [tests/test_download.py](tests/test_download.py).

### Contract checked

* A 200 returns the exact stored bytes with every promised header: `Content-Type`,
  `Content-Length`, the quoted `ETag`, `Content-Disposition`, and
  `X-Content-Type-Options`.
* The header values agree with the file's info: the `ETag` is the Metadata `etag` in
  quotes, and `Content-Length` is the size.
* A missing or invalid `path` returns 400 `InvalidInput` without calling storage, a
  missing file returns 404 `FileNotFound`, and a provider outage in `get` returns 503
  `ProviderUnavailable`, all in the error format.
* A path finds its file with or without the leading `/`, and storage only sees the key.
* The old `GET /files/{key}` route is gone: a `GET` there returns 405
  `MethodNotAllowed` with `Allow: POST, PUT`.
* The `get` contract in `storage/base.py` holds for `S3Storage`: a `get_object` answer
  becomes `FileInfo` plus chunks, provider errors become our errors (also while the
  chunks are read), and the provider stream is closed after reading.
* A failure after the 200 headers leaves the response unfinished and is logged as an
  interrupted download (tested with the Level 5 tests in
  [tests/test_failures.py](tests/test_failures.py)).

### Cases and boundaries

* **Path shape:** a path with a folder and non-ASCII characters (`/docs/résumé.pdf`),
  because `Content-Disposition` drops the folder and percent-encodes the name; the same
  path with and without its leading `/`; invalid paths (empty, `/`, a trailing `/`,
  `//`, `..`, a control character) and no `path` at all; and a missing file.
* **Content type:** a known binary type (`.pdf`), a text type (`.txt`, which gains
  `; charset=utf-8`), and an unknown extension (falls back to
  `application/octet-stream`).
* **Size:** small files in the fast tests, and 10 bytes read with a 4-byte chunk size to
  check that the download is split into chunks, including a short last one. On the real
  provider, 5 MiB, to check a multi-megabyte round trip.
* **Lazy reads:** a provider stream that records every read shows that opening a
  download reads nothing and the first chunk reads exactly one chunk size. A backend
  that read the whole body first and then split it would still pass the chunk-size
  test, but not this one.
* **Provider errors:** `NoSuchKey` (404) and `AccessDenied` (403), which become
  `FileNotFound` and `AccessDenied`, and a connection that breaks after the first read,
  which botocore reports as `ResponseStreamingError` and we report as
  `ProviderUnavailable`.
* **Stream cleanup:** a body read to the end, and a body closed after the first chunk.

### Tests

HTTP behavior, on the in-memory backend through `create_app(service)`:

* [`test_download_returns_the_bytes_and_every_promised_header`](tests/test_download.py):
  identical bytes; `application/pdf`; `Content-Length` equals the size; `ETag` equals
  the Metadata `etag` in quotes; `Content-Disposition` is
  `attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf`; `nosniff`.
* [`test_download_content_type_comes_from_the_extension`](tests/test_download.py):
  `notes.txt` gives `text/plain; charset=utf-8`, and `blob.unknownext` gives
  `application/octet-stream`.
* [`test_download_of_a_missing_file_is_404`](tests/test_download.py): 404, a body with
  exactly `error` and `detail`, and `FileNotFound`.
* [`test_the_old_keyed_download_route_is_gone`](tests/test_download.py): `GET
  /files/notes.txt` returns 405 `MethodNotAllowed` with `Allow: POST, PUT`.

HTTP behavior over [`FakeStorage`](#controlled-storage), with the `fake` and
`fake_client` fixtures:

* [`test_download_returns_503_when_the_provider_is_unavailable`](tests/test_download.py):
  with `get` set to raise `ProviderUnavailable`, 503 with exactly
  `{"error": "ProviderUnavailable", "detail": "could not reach the storage provider"}`,
  and `fake.calls == [("get", "notes.txt")]`.
* [`test_download_finds_the_file_with_or_without_the_leading_slash`](tests/test_download.py):
  `docs/notes.txt` and `/docs/notes.txt` both return the file, and storage is called
  once with the key `docs/notes.txt`.
* [`test_download_of_an_invalid_path_is_400_and_never_calls_storage`](tests/test_download.py):
  each invalid path returns 400 `InvalidInput`, and `fake.calls == []`.
* [`test_download_without_a_path_is_400_and_never_calls_storage`](tests/test_download.py):
  `GET /files/download` with no `path` returns 400 with exactly
  `{"error": "InvalidInput", "detail": "path: Field required"}`, and `fake.calls == []`.

Translation, with `stubbed_s3` (no network):

* [`test_s3_get_translates_the_response_into_file_info_and_chunks`](tests/test_download.py):
  `get_object` is called with the right bucket and key; the answer becomes the expected
  `FileInfo` (ETag quotes stripped), and the chunks join to the original bytes.
* [`test_s3_get_of_a_missing_key_raises_file_not_found`](tests/test_download.py):
  `NoSuchKey` becomes `FileNotFound`.
* [`test_s3_get_closes_the_provider_stream`](tests/test_download.py): the provider
  stream is closed after every chunk is read, and after a caller closes the chunks
  following the first one.
* [`test_s3_get_streams_in_chunks`](tests/test_download.py): with the chunk size set to
  4 bytes, a 10-byte file arrives as chunks of 4, 4, and 2 bytes, so the backend streams
  instead of reading the whole file at once.
* [`test_s3_get_reads_lazily_one_chunk_at_a_time`](tests/test_download.py): with the
  chunk size set to 4 bytes and a stream that records every read, `storage.get` reads
  nothing, and the first chunk reads exactly 4 bytes.
* [`test_s3_get_closes_the_provider_stream_when_no_chunk_was_read`](tests/test_download.py):
  the provider stream is closed when a caller closes the chunks before reading any
  (regression test for [#15](https://github.com/FaizalJnu/OSPSD-TEAM-6/issues/15)).
* [`test_s3_get_translates_a_connection_dropped_mid_download`](tests/test_download.py):
  a provider stream returns 5 bytes, then raises urllib3's `ProtocolError`, as in
  [#26](https://github.com/FaizalJnu/OSPSD-TEAM-6/issues/26). The first chunk arrives;
  the next raises `ProviderUnavailable` with `provider_code` `ResponseStreamingError`
  and without the SDK's message, and the stream is closed. On `59788d2`, botocore's
  `ResponseStreamingError` escaped instead.
* [`test_s3_get_denied_by_the_provider_raises_access_denied`](tests/test_download.py):
  `AccessDenied` becomes our `AccessDenied`, with the provider's code kept in
  `provider_code` and out of the message.

Real provider (marked `provider`):

* [`test_download_of_a_multi_megabyte_file_from_the_real_provider`](tests/test_download.py):
  5 MiB of random bytes come back identical, with the right `Content-Length` and the
  Metadata `etag` in quotes.

### Real-provider verification

#### Run by Vikram Markali

- Provider: OCI Object Storage, us-ashburn-1
- Date: 2026-10-14
- Commit: b95bf89, plus this branch's changes (docs, tests, and the `/docs` description)
- Request:
  ```bat
  curl.exe -s -F "file=@hello.txt" %B%/files/examples/hello.txt
  curl.exe -s -D - -o back.txt %B%/files/examples/hello.txt
  fc /b hello.txt back.txt
  ```
- Expected: 200 with the stored bytes and every header promised in
  [docs/API.md](docs/API.md#download); `fc /b` finds no differences.
- Observed:
  ```text
  HTTP/1.1 200 OK
  date: Wed, 14 Oct 2026 18:48:55 GMT
  server: uvicorn
  content-length: 33
  content-disposition: attachment; filename*=UTF-8''hello.txt
  etag: "d5dd2e893e86e4e636ad6261081837ed"
  x-content-type-options: nosniff
  content-type: text/plain; charset=utf-8

  Comparing files hello.txt and BACK.TXT
  FC: no differences encountered
  ```
  `uv run --env-file .env pytest -m provider`: `8 passed, 45 deselected`.
- Cleanup: `curl.exe -i -X DELETE %B%/files/examples/hello.txt` returned
  `204 No Content`, and a following `GET` returned `404` `FileNotFound`.

#### Run by Debasmith Mandal (second verifier)

- Provider: OCI Object Storage, us-ashburn-1
- Date: 2026-10-21
- Commit: `b3c5242`
- Provider command: `uv run --env-file .env pytest -m provider tests/test_download.py`
- Observed: `1 passed, 13 deselected`
- Manual request, against a local server started with
  `uv run --env-file .env uvicorn storage_service.main:create_app --factory`:
```bash
  B=http://127.0.0.1:8000
  P=api-tests/manual-download-$(date +%s)/
  printf 'hello from debasmith\n' > hello.txt
  curl -s -F "file=@hello.txt" "$B/files/${P}hello.txt"
  curl -s -D - -o back.txt "$B/files/${P}hello.txt"
  cmp hello.txt back.txt && echo "byte-identical"
  curl -s "$B/metadata/${P}hello.txt"
  curl -s -o /dev/null -w "DELETE %{http_code}\n" -X DELETE "$B/files/${P}hello.txt"
  curl -s "$B/files?prefix=api-tests/"
```
- Expected: 201 on upload; 200 with the stored bytes and every header promised in
  [docs/API.md](docs/API.md#download), with the `ETag` equal to the Metadata `etag` in
  quotes; then 204 on delete and an empty listing.
- Observed: 201, 200, 200, 204, 200. Download headers (date and server omitted):
```text
  HTTP/1.1 200 OK
  content-length: 21
  content-disposition: attachment; filename*=UTF-8''hello.txt
  etag: "6362df44bdee741f54c93292482979a4"
  x-content-type-options: nosniff
  content-type: text/plain; charset=utf-8
```
  `cmp` found the files byte-identical. Metadata returned `size` 21 and
  `etag` `6362df44bdee741f54c93292482979a4`.
- Cleanup: DELETE returned 204, and `GET /files?prefix=api-tests/` returned
  `{"files":[],"next_cursor":null}`, so neither run left files behind. Local files
  removed.

### Provider observations

* **Files uploaded outside the service keep the type the provider stored.** On OCI
  (us-ashburn-1, 2026-10-14), a 38-byte `.txt` file uploaded through the OCI Console as
  `console-check/sample.txt` downloaded through the API with `200` and
  `content-type: text/plain; charset=utf-8`. Metadata reported `"content_type":
  "text/plain"` with the same size and etag. Who chose `text/plain` (the console or the
  browser) was not checked. The service does not recompute the type at download, so a
  tool that stores another type is served with that type. This matches the contract in
  the Download assumptions in [docs/API.md](docs/API.md#download), so no bug issue was opened.
* **No stored type means no `Content-Type` header.** Checked with a test double, not on
  a provider: when `content_type` is `None`, the response has no `Content-Type` header
  and still sends `X-Content-Type-Options: nosniff`. Not observed on OCI.
* Cleanup: `DELETE /files/console-check/sample.txt` returned `204`, then
  `GET /files/console-check/sample.txt` returned `404` `FileNotFound`, and
  `GET /files?prefix=console-check/` returned `{"files":[],"next_cursor":null}`.

### Gaps

* **A failure mid-stream cuts the body off.** Once the 200 headers are sent, the status
  can no longer change, so the service logs the failure and leaves the response
  unfinished. Verified with a `FakeStorage` whose chunks raise `ProviderUnavailable`
  after 11 of 100 bytes, served by uvicorn: curl received `200`,
  `content-length: 100`, then 11 bytes, and exited with code 18 (partial file). The
  server logged our one line with `"status": 200` and `"interrupted": true`, then
  uvicorn's one line `ASGI callable returned without completing response.`, and served
  the next request normally. Ending the body normally instead made uvicorn's HTTP
  library raise `Too little data for declared Content-Length`, which reached the 500
  handler: a second, wrong JSON line with `"status": 500` and a traceback, then
  uvicorn's `Exception in ASGI application` traceback, about 150 lines in all. Callers
  detect the cut by comparing the received size with `Content-Length`.
* **The mid-stream S3 translation is tested with a stub, not a real dropped
  connection.** The stub stream raises the urllib3 error that a broken connection
  raises, and botocore wraps it the same way. `ReadTimeoutError` takes the same path
  (it is also a `BotoCoreError`) but has no test of its own.
* **`ProviderUnavailable` from `get` is tested over `FakeStorage`, not through
  `S3Storage`.** The Stubber can only queue answers and client errors, not connection
  failures, so `test_download_returns_503_when_the_provider_is_unavailable` checks the
  HTTP mapping with a fake that raises it.
* **Client disconnects are not tested.** When Starlette stops reading the chunks after
  a client disconnects, and whether it closes them, is not established here.
* **The real-provider runs above used the old `GET /files/{key}` route.** No run of
  `GET /files/download?path=` against a real provider is recorded yet.
* **A folder path is not tested.** It returns 404 `FileNotFound` today, and the shared
  contract has not decided what it should return (Dayana20/ospsd26-cloud-storage
  issue #8).

## Metadata

Owner: **Darsh Shani**. Contract: [docs/API.md](docs/API.md#metadata).
Tests: [tests/test_metadata.py](tests/test_metadata.py).

### Contract checked

`GET /metadata/{key}` returns 200 and all five promised fields without changing
contents. Sizes are integer bytes, ETags have no surrounding quotes, and
timestamps are timezone-aware UTC ISO 8601. An unchanged file has the same key,
size, and ETag in metadata and listing. Invalid keys are rejected before any
storage call; a missing file returns 404 with the public error body.

The provider boundary is `StorageClient.stat`, whose contract is in
[storage/base.py](src/storage_service/storage/base.py). Tests inject storage
into `FileService`, then pass it to `create_app(service)`. The HTTP route and
application decisions are the same ones used in production. No credential or
network access is needed for these tests. The team's `FakeStorage` wraps the
in-memory backend, records calls, and injects failures. The metadata tests use
it for successful reads, invalid-key rejection before storage, and HTTP 502
mapping. The shared HTTP 503 case stays in
`tests/test_injection.py::test_metadata_returns_503_when_the_provider_is_unavailable`;
metadata retains its separate S3 connection-error translation test. Separate
Stubber tests cover the actual S3 translation.

### Cases and boundaries

* Ordinary file: all fields, read-only behavior, and agreement with upload and list.
* Unicode key exactly at the 1024-byte UTF-8 limit is accepted. Empty keys,
  empty segments, trailing slashes, a control character, and an over-limit
  multibyte key are rejected without a storage call.
* Missing file, provider rejection, and provider unavailability use the shared
  HTTP error mapping, without introducing Level 5 logging or retry behavior.
* Provider metadata with and without a content type becomes `FileInfo`.
  Quoted opaque ETags lose only their surrounding quotes. SDK error codes
  `NoSuchKey` becomes `FileNotFound`; explicit `NoSuchBucket` becomes
  `ProviderError`; `AccessDenied` becomes our `AccessDenied`; connection errors
  become `ProviderUnavailable`.

### Tests

Run the offline tests with `uv run pytest tests/test_metadata.py`. Their names
state the behavior checked: complete HTTP response, metadata/list consistency,
missing/invalid keys, injection and failure mapping, S3 response/error
translation, and the published OpenAPI response contract.

The provider-marked test
`test_metadata_reports_real_provider_values_and_matches_listing` creates one
file through HTTP under `provider_prefix`, checks every metadata field, compares
downloaded bytes and listing, and leaves cleanup to `provider_client`. It
compares parsed UTC timestamps allowing less than one second of precision
difference; this is not a guarantee about concurrent changes.

```bash
uv run --env-file .env pytest -m provider tests/test_metadata.py
```

### Real-provider verification

#### Run from Darsh's Windows checkout with Codex assistance

- Provider: OCI Object Storage, `us-ashburn-1`, Darsh's private test bucket.
- Date: 2026-10-14.
- Source commit: `003d529829ff2df776711c9ed0f3598337efbcee`.
- Provider command: `uv run --locked --env-file .env pytest -m provider tests/test_metadata.py
  --tb=short --show-capture=no -p no:cacheprovider`.
- Observed: **1 passed, 19 deselected**. The cache plugin was disabled only for
  this invocation because elevated execution could not write the sandbox-owned
  pytest cache. Test selection and assertions were unchanged.
- Manual verification: a local Uvicorn server at `http://127.0.0.1:8765`, wired
  from `.env`, was exercised with `curl.exe`. The sample contained the 37 UTF-8
  bytes `%PDF-1.7 metadata manual verification`.

Exact HTTP requests used this unique key:

```powershell
$B = 'http://127.0.0.1:8765'
$K = 'api-tests/manual-metadata-1779d5119d034bc8a99c24de24cc6933/report.pdf'
$P = 'api-tests/manual-metadata-1779d5119d034bc8a99c24de24cc6933/'
curl.exe -F 'file=@metadata-sample.pdf' "$B/files/$K"
curl.exe "$B/metadata/$K"
curl.exe "$B/files?prefix=$P"
curl.exe -o metadata-download.pdf "$B/files/$K"
curl.exe -X DELETE "$B/files/$K"
curl.exe "$B/metadata/$K"
curl.exe "$B/files?prefix=$P"
```

Expected and observed statuses, in that order: **201, 200, 200, 200, 204, 404,
200**. The metadata response was:

```json
{
  "key": "api-tests/manual-metadata-1779d5119d034bc8a99c24de24cc6933/report.pdf",
  "size": 37,
  "content_type": "application/pdf",
  "etag": "bac20131ce394b58e1fe6e3b51cf6d59",
  "last_modified": "2026-10-14T17:36:39Z"
}
```

Listing returned the same key, size, ETag, and `2026-10-14T17:36:39Z` timestamp,
with `content_type: null`. No timestamp precision difference was observed in
this run. Downloaded bytes were identical to the sample (SHA-256
`bf0ccb51fc04920038af9f8c011a901d11c25f11c932caf22592e0a21588adb1`).

Cleanup: DELETE returned 204; metadata then returned 404 `FileNotFound`, and
the prefix listing returned `{"files": [], "next_cursor": null}`. The provider
fixture also completed its own cleanup without an error. Only the unique test
prefixes were used. Vikram's run below is the second verification.

#### Run by Vikram Markali

- Provider: OCI Object Storage, us-ashburn-1, my own private test bucket
- Date: 2026-10-20
- Commit: fd2d127
- Provider command: `uv run --env-file .env pytest -m provider tests/test_metadata.py`
- Observed: `1 passed, 18 deselected`
- Setup note: ran with the documented FIX-1 checksum workaround, the two
  `AWS_*_CHECKSUM_*` lines in `.env` (see
  [FIX-1](fixesRequired.md#fix-1-oci-rejects-every-upload)), because FIX-1 is not
  merged yet.
- Manual request, in Windows `cmd.exe` against a local server started with
  `uv run --env-file .env uvicorn storage_service.main:create_app --factory`, with a
  31-byte local file `report.pdf`:
  ```bat
  set B=http://127.0.0.1:8000
  set P=api-tests/manual-metadata-a9d44c7b039a4447a19198f75c7f14cf/
  curl.exe -F "file=@report.pdf" %B%/files/%P%report.pdf
  curl.exe %B%/metadata/%P%report.pdf
  curl.exe -X DELETE %B%/files/%P%report.pdf
  curl.exe %B%/metadata/%P%report.pdf
  curl.exe "%B%/files?prefix=%P%"
  ```
- Expected: 201; then 200 with the same `key`, `size`, `content_type`, `etag`, and
  `last_modified` that Create returned, as [docs/API.md](docs/API.md#metadata)
  promises; then 204, 404 `FileNotFound`, and an empty listing.
- Observed: 201, 200, 204, 404, 200. The metadata response matched Create's exactly:
  ```json
  {"key":"api-tests/manual-metadata-a9d44c7b039a4447a19198f75c7f14cf/report.pdf","size":31,"content_type":"application/pdf","etag":"5112b948fcf05f9c2148d479322db3f6","last_modified":"2026-10-21T02:04:15Z"}
  ```
  After the delete:
  ```text
  {"error":"FileNotFound","detail":"no file named 'api-tests/manual-metadata-a9d44c7b039a4447a19198f75c7f14cf/report.pdf'"}
  {"files":[],"next_cursor":null}
  ```
- Cleanup: the DELETE returned 204, metadata then returned 404, and listing the
  prefix returned `{"files":[],"next_cursor":null}`, so the prefix is empty. The
  provider test's fixture cleaned up its own prefix without an error. The local
  `report.pdf` was deleted.

### Provider observations

The first live attempt returned 502 `ProviderError` with code `NotImplemented`
on upload. Inspection showed boto3's checksum mode was `when_supported`,
matching the team's existing FIX-1 report. Setting
`AWS_REQUEST_CHECKSUM_CALCULATION=when_required` and
`AWS_RESPONSE_CHECKSUM_VALIDATION=when_required` in the ignored local `.env`
made the same provider test pass. No production upload fix is included here.

HEAD and LIST returned equal UTC timestamps with whole-second precision for
this sample. This observation does not promise identical precision on every
provider or request. Ambiguous HEAD 404s are now covered by the
[FIX-2 regression](#missing-bucket-regression-fix-2).

### Gaps

* Missing-bucket behavior and its independent-verification status are recorded
  in the [FIX-2 section](#missing-bucket-regression-fix-2).
* The controlled fake does not validate authentication, provider availability,
  or SDK retry behavior. Stubber validates request parameters and translation,
  not whether the provider actually returns these responses.
* Access denial and failure logs are tested in
  [Error model and failure logs](#error-model-and-failure-logs-level-5), not here.

## Delete

Owner: **Faizal Rahman**. Contract: [docs/API.md](docs/API.md#delete).
Tests: [tests/test_delete.py](tests/test_delete.py).

### Contract checked

`DELETE /files?path=` returns 204 with an empty body and removes the file, so a later
Download or Delete returns 404. The path works with or without its leading `/`, and
storage only ever sees the key. The service checks that the file exists with `stat`
before it calls `delete`. A missing file returns 404 `FileNotFound` and `delete` is
never called. A failed check returns 503 `ProviderUnavailable` or 502 `ProviderError`
and `delete` is never called. A rejected delete returns 502 with the full error body.
`S3Storage.delete` turns a provider rejection into `ProviderError`.

With no file at the path, the service lists every key under `<path>/`, following every
page, and only then calls `delete_many`, with at most 1000 keys per call. A path with
no file and nothing under it returns 404 `FileNotFound`, and `delete_many` is never
called. A failed listing deletes nothing. A first batch that fails keeps its own status.
A later batch that fails, or any batch that reports failed keys, returns 502
`ProviderError` and no further batch is sent. `S3Storage.delete_many` sends a SHA-256
checksum and returns the keys listed in the `Errors` of a 200 response.

### Cases and boundaries

* Existing file, then the same request again: the 404 on the second request is our
  rule, because S3 deletes a missing key silently.
* Missing file: shows the existence check and the empty listing stop the request before
  anything is deleted.
* Folder boundary: `docs` must not match `docs2/` or `docs-backup/`, and `do` must not
  match `docs/`. Deleting a whole folder by accident is the costliest mistake here.
* Batch boundary: 2001 files is three listings and batches of 1000, 1000, and 1, so it
  shows both limits and the short last batch.
* An empty page with a cursor: S3 allows it, so the listing stops only when there is no
  cursor.
* A file and a folder at one path: only the file is deleted.
* Where a folder delete fails: partway through the listing, in the first batch, in a
  later batch, and in a batch that reports failed keys. Each one has different knowledge
  of what changed.
* Retry after a partial delete: 502, then 204, then 404.
* A failure on each of the two provider calls: `stat` unavailable (503) and `delete`
  rejected (502). Together they show which call failed and that nothing runs after a
  failed check.
* Path rules: each rule, and the byte limit at its boundary, is covered in
  [tests/test_service.py](tests/test_service.py). Over HTTP, this file checks that a
  bad or missing path is 400 and calls storage zero times.
* Query-string decoding: a literal `+` has to arrive as `%2B`, because a `+` in a query
  string means a space.
* The old `DELETE /files/{key}` route no longer deletes anything.

### Tests

Run them with `uv run pytest tests/test_delete.py`.

* `test_delete_removes_the_file_and_deleting_again_is_404`: in-memory HTTP round
  trip: 204, then Download 404, then Delete 404.
* `test_delete_checks_the_file_exists_then_deletes_it`: 204, empty body, and calls
  `[("stat", k), ("delete", k)]`.
* `test_delete_finds_the_file_with_or_without_the_leading_slash`: both spellings make
  the same storage calls, on the key without a leading `/`.
* `test_delete_of_a_missing_file_is_404_and_never_calls_delete`: 404 `FileNotFound`,
  calls `[("stat", k), ("list_files", k + "/")]`.
* `test_delete_of_a_missing_file_reports_the_canonical_path`: the error names the path
  with its leading `/`, even when the request left it out.
* `test_delete_of_an_invalid_path_is_400_and_never_calls_storage`: empty, root, trailing
  `/`, `//`, `..`, a control character, and too long.
* `test_delete_without_a_path_is_400_and_never_calls_storage`: no `path` parameter gives
  400 `InvalidInput`, and calls nothing.
* `test_delete_decodes_the_path_from_the_query_string`: `%2B` and `%20` reach the service
  decoded.
* `test_the_old_keyed_delete_route_no_longer_deletes`: the file survives a request to
  the old route.
* `test_delete_returns_503_and_never_deletes_when_the_check_cannot_reach_the_provider`:
  503 with the full body, calls `[("stat", k)]`.
* `test_delete_returns_502_when_the_provider_rejects_the_delete`: 502 with the full
  body, calls `[("stat", k), ("delete", k)]`.
* `test_delete_of_a_folder_removes_everything_under_it_and_nothing_else`: 204, empty
  body, both nested files gone, and `docs2/`, `docs-backup/`, and `other.txt` survive.
* `test_deleting_a_folder_again_is_404`: 204, then 404.
* `test_delete_of_a_folder_lists_it_then_deletes_its_keys`: both spellings make the
  calls `stat`, `list_files` on `docs/`, then `delete_many` on both keys.
* `test_delete_of_a_large_folder_reads_every_page_then_deletes_1000_keys_per_call`: 2001
  files give three listings and batches of 1000, 1000, and 1, and nothing is left.
* `test_delete_of_a_folder_follows_the_cursor_past_an_empty_page`: the key on the
  second page is still deleted.
* `test_delete_removes_only_the_file_when_a_file_and_a_folder_share_a_path`: calls
  `stat` then `delete`, and `docs/a.txt` survives.
* `test_delete_does_not_treat_the_start_of_a_name_as_a_folder`: `do` is 404, and
  `docs/a.txt` survives.
* `test_a_folder_listing_that_fails_partway_deletes_nothing`: the second page fails:
  503, and `delete_many` is never called.
* `test_a_folder_delete_whose_first_batch_fails_reports_that_failure_unchanged`: 503,
  502, and 403 keep their own bodies, and only one batch is sent.
* `test_a_folder_delete_that_fails_after_a_finished_batch_is_502_and_stops`: a timeout
  on the second of three batches is 502 `ProviderError`, and the third is never sent.
* `test_a_folder_delete_whose_batch_reports_failed_keys_is_502_and_stops`: one refused
  key in the first of two batches gives 502, and the second is never sent.
* `test_retrying_a_partly_deleted_folder_deletes_what_is_left`: 502, then 204, then 404.
* `test_s3_delete_denied_by_the_provider_raises_access_denied`: Stubber test that
  `DeleteObject` is sent with the right bucket and key, and that `AccessDenied` becomes
  our `AccessDenied`.
* `test_s3_delete_many_sends_the_keys_in_one_call_and_reports_no_failures`: Stubber test
  of the exact `DeleteObjects` parameters, including `Quiet` and
  `ChecksumAlgorithm="SHA256"`.
* `test_s3_delete_many_returns_the_keys_the_provider_could_not_delete`: the `Errors` of
  a 200 response come back as a list of keys.
* `test_s3_delete_many_denied_by_the_provider_raises_access_denied` and
  `test_s3_delete_many_rejected_by_the_provider_raises_provider_error`: a whole call
  that fails becomes our error type.
* `test_delete_removes_the_file_from_the_real_provider` (marked `provider`): create,
  delete (204), then Metadata 404 against a real bucket.
* `test_delete_removes_a_nested_folder_from_the_real_provider` (marked `provider`): 204,
  both nested files are 404, and a file beside the folder survives.

[tests/test_storage_contract.py](tests/test_storage_contract.py) adds
`test_delete_many_removes_the_keys_and_ignores_missing_ones`, for both backends.

Making `service.delete` skip the existence check and go straight to `delete` makes 24
test cases in this file fail.

### Real-provider verification

#### Run by Prateek Saxena

- Provider: OCI Object Storage, us-ashburn-1, my own private test bucket
- Date: 2026-10-21
- Commit: 560ee5d, boto3 1.43.108
- Provider command: `uv run --env-file .env pytest -m provider -k delete`
- Observed: `3 passed, 154 deselected`: the HTTP test in this file and the two Delete
  contract tests on S3. The full `pytest -m provider` run on the same commit gave
  `16 passed, 141 deselected`.
- Manual requests against a local server started with
  `uv run --env-file .env uvicorn storage_service.main:create_app --factory --port 8765`,
  with `K=manual-delete-<uuid>/x.txt` and a one-byte local file `a.txt`:
  ```bash
  curl -F "file=@a.txt" "$B/files/$K"
  curl -i -X DELETE "$B/files/$K"
  curl -i -X DELETE "$B/files/$K"
  curl -i "$B/metadata/$K"
  curl "$B/files?prefix=manual-delete-<uuid>/"
  ```
- Expected: 201; 204 with an empty body; 404 `FileNotFound` for the repeated delete
  (our rule, since S3 deletes a missing key silently); 404 for Metadata; an empty
  listing.
- Observed: 201, 204 (empty body), 404, 404, 200 `{"files":[],"next_cursor":null}`.
  Both 404s had the body
  `{"error":"FileNotFound","detail":"no file named 'manual-delete-<uuid>/x.txt'"}`.
- Missing bucket: with `S3_BUCKET` overridden to a bucket that does not exist,
  `curl -i -X DELETE "$B/files/x.txt"` returned
  `502 {"error":"ProviderError","detail":"the configured bucket does not exist or is not accessible"}`,
  as [Bucket checks](docs/API.md#bucket-checks) says.

#### Folder delete, run from Faizal Rahman's checkout

- Provider: OCI Object Storage, us-ashburn-1
- Dates: 2026-11-09, and again on 2026-11-10 after moving onto `dev`
- Commits: 44b6b69, then c6902a0 (`dev` with #74), each plus the then-uncommitted
  folder delete changes, boto3 1.43.108
- Provider commands: `uv run --env-file .env pytest -m provider -k delete`, then
  `uv run --env-file .env pytest -m provider`
- Expected: every test passes. The nested-folder test sends `DELETE /files?path=` for a
  folder holding `a.txt` and `sub/b.txt`: 204, both files then 404 from Metadata, and a
  file beside the folder still 200.
- Observed on 44b6b69: `5 passed, 239 deselected` and `19 passed, 225 deselected`.
- Observed on c6902a0: `5 passed, 246 deselected` and `20 passed, 231 deselected`. The
  extra provider test is the List cursor check from #74.
- Cleanup: the tests delete everything under their unique `api-tests/` and
  `contract-tests/` prefixes, even when they fail.

### Provider observations

* Repeating a delete on OCI gives 404 from our existence check, so the provider's
  silent delete of a missing key is never reached through the API. The contract test
  `test_delete_of_a_missing_key_is_silent[s3]` confirms that OCI itself returns success
  for it.
* OCI rejects boto3's default `DeleteObjects` checksum, CRC32, with 400 `InvalidRequest`
  and `Missing required header for this request: Content-MD5 or x-amz-checksum-sha256 or
  x-amz-checksum-crc32c`, and deletes nothing. The FIX-1 `when_required` setting does not
  help, because this call always requires a checksum. Asking for SHA-256 deleted the
  keys, and so did a `Content-MD5` header sent by hand.

### Gaps

* Prateek's run above used the old `DELETE /files/{key}` route, so only one run of
  `DELETE /files?path=` is recorded. Level 2 needs runs by two people.
* The real-provider tests delete small folders. Splitting a folder of more than 1000
  files into batches is tested only on `FakeStorage`.
* Folder Delete has run only against OCI, not AWS S3 or Google Cloud Storage. The
  results in [docs/PROVIDERS.md](docs/PROVIDERS.md) for those two predate it.
* A `DeleteObjects` that reports failed keys is tested only with Stubber and
  `FakeStorage`. No real provider has been made to return one.
* The missing-bucket behavior is tested in
  [test_bucket_errors.py](tests/test_bucket_errors.py) (FIX-2), not here, including
  that Delete returns 502 before deleting anything.
* The race between the check and the delete is documented, not tested.

## Move

Owner: **Vikram Markali**. Contract: [docs/API.md](docs/API.md#move).
Tests: [tests/test_move.py](tests/test_move.py), plus the `copy` contract tests in
[tests/test_storage_contract.py](tests/test_storage_contract.py).

### Contract checked

* A move returns 200 with the shared file info at the new path, with the original's
  size, etag, and content type. Afterwards Metadata finds the file at `new_path` and
  returns 404 at `path`.
* The service checks the source, then the destination (file and folder), then
  copies, then deletes, and copies nothing if any check fails.
* 400 `invalid_request` for a missing or invalid `path` or `new_path` and for a body
  that is not JSON, 404 `not_found` for a missing source, 409 `conflict` for a file or
  folder at the destination, 422 `invalid_operation` for the same path, a case-only
  rename, or a folder source, and 503 when the provider is unreachable, all in the
  shared error format.
* A delete that fails after a successful copy is a 502 `provider_error` whatever the
  delete's own error was (502, 403, or 503), and the file is then at both paths.
* `copy` follows its contract in `storage/base.py` on both backends, and
  `S3Storage.copy` sends `CopyObject` with the right source and destination.

### Cases and boundaries

* **Request shape:** no body, a body that is not JSON, no `new_path`, an invalid
  `new_path`, no `path`, and an invalid `path`. None of them may reach storage.
* **Paths that change nothing real:** the same path written with and without its
  leading `/`, and a path that differs only in letter case. Both are refused before
  storage is called.
* **What exists:** a missing source, a folder as source, a file at the destination,
  and a folder at the destination.
* **Failures at each provider step:** the source check (503), the copy (502), and the
  delete after the copy, with each of the three provider errors the delete can raise.
* **Over a stubbed S3:** the full provider call sequence, including the bucket probe
  that a HEAD 404 triggers (FIX-2), with `DeleteObject` refused after `CopyObject`
  succeeded.

### Tests

Run them with `uv run pytest tests/test_move.py`.

HTTP behavior over [`FakeStorage`](#controlled-storage):

* `test_move_copies_then_deletes_and_returns_the_file_at_its_new_path`: 200 with
  `id` null, the new `name` and `path`, the original's size, etag, and content type;
  Metadata 404 at the old path and 200 at the new one; calls `stat` source, `stat`
  destination, `list_files` destination folder, `copy`, `delete`.
* `test_move_of_a_missing_file_is_404_and_copies_nothing`: 404 `not_found` with
  `no file at '/docs/a.txt'`, and no `copy` call.
* `test_move_onto_something_that_exists_is_409_and_changes_nothing`, for a file and
  for a folder at the destination: 409 `conflict`, no `copy` or `delete` call, and
  both files still there.
* `test_move_that_changes_nothing_real_is_422_and_never_calls_storage`, for the same
  path and a case-only rename: 422 `invalid_operation`, and `fake.calls == []`.
* `test_move_of_a_folder_is_422_and_copies_nothing`: 422 `invalid_operation`, and
  only the source `stat` and its folder listing were called.
* `test_move_with_a_bad_request_is_400_and_never_calls_storage`, for the six request
  shapes above: 400 `invalid_request`, and `fake.calls == []`.
* `test_move_whose_delete_fails_after_the_copy_is_502_whatever_the_cause`, with the
  delete raising `ProviderError`, `AccessDenied`, or `ProviderUnavailable`: 502
  `provider_error` with the "could not be confirmed" message, and the file at both
  paths.
* `test_move_whose_copy_fails_leaves_the_original_alone`: 502, no `delete` call, and
  the original still there.
* `test_move_returns_503_when_the_source_check_cannot_reach_the_provider`: 503
  `provider_unavailable` with the full body, and only the source `stat` was called.

Translation, with `stubbed_s3` (no network):

* `test_s3_copy_sends_copy_object_and_returns_the_copys_info`: `CopyObject` gets the
  destination key and `CopySource` with the bucket and source key, and the copy's
  info comes from a follow-up `HeadObject`.
* `test_s3_copy_of_a_missing_source_raises_file_not_found`: `NoSuchKey` becomes
  `FileNotFound`.
* `test_move_over_s3_is_502_when_delete_object_fails_after_copy_object`: the app over
  a stubbed `S3Storage` sends `HeadObject`, `HeadObject` (404) with its `HeadBucket`
  probe, `ListObjectsV2` on the destination folder, `CopyObject`, `HeadObject`, then
  `DeleteObject`, which is refused with `AccessDenied`. The response is 502
  `provider_error`, not 403.

Contract, on every backend (S3 with `-m provider`):

* `test_copy_makes_a_second_file_and_keeps_the_original`: the copy has the same bytes
  and content type, and the original is unchanged.
* `test_missing_key_raises_file_not_found` now also checks that `copy` from a missing
  key raises `FileNotFound`.

Real provider (marked `provider`):

* `test_move_against_the_real_provider`: a move under the test prefix returns 200 with
  the new path, `id` null, and the original's size, etag, and content type; Metadata
  then returns 404 at the old path and 200 at the new one.

Two temporary defects showed that these tests check the rules: turning only a
`ProviderError` from the delete into the partial-move 502 failed the 403 and 503 cases
and the stubbed S3 test, and removing the destination folder check failed the folder
409 test.

### Real-provider verification

#### Run by Vikram Markali

- Provider: OCI Object Storage, us-ashburn-1, my own private test bucket
- Date: 2026-11-11
- Commit: d5067e4 (dev after #81 was merged; it includes #83 and #84) plus this
  branch's Move commit, the one that adds this record
- Command: `uv run --env-file .env pytest -m provider tests/test_move.py`
- Expected: the move returns 200 with the new path, Metadata returns 404 at the old
  path and 200 at the new one, and the size, etag, and content type are unchanged.
- Observed: `1 passed, 21 deselected`
- Also ran: `uv run --env-file .env pytest -m provider tests/test_storage_contract.py
  -k "copy or missing_key"`, which gave `3 passed, 19 deselected`, including `copy`
  on S3.
- Cleanup: both runs write under a unique `api-tests/` or `contract-tests/` prefix,
  and their fixtures delete everything under it afterwards.

### Provider observations

* On OCI, `CopyObject` kept the source's ETag for a small (single-part) file and its
  content type, so the moved file reports the same `etag` and `content_type` as the
  original.

### Gaps

* Only one real-provider run is recorded. Level 2 needs runs by two people.
* The 5 GB per-call `CopyObject` limit is from the AWS documentation and is not
  verified on OCI. No test copies a file that large.
* A partial move against a real provider is not tested: a provider cannot be made to
  refuse the delete on cue. The fake and the stubbed S3 test cover it.
* The race between the checks and the copy (another client creating a file at
  `new_path` in between) is documented, not tested.

## List

Owner: **Prateek Saxena**. Contract: [docs/API.md](docs/API.md#list).
Tests: [tests/test_list.py](tests/test_list.py).

### Contract checked

* A 200 returns exactly `files` and `next_cursor`, and each file has exactly the five
  [file info](docs/API.md#file-info) fields: `content_type` is `null`, `etag` has no
  quotes and equals the Create response's `etag`, and `last_modified` is UTC.
* Following `next_cursor` until it is `null` returns every matching file exactly once,
  sorted by UTF-8 bytes. No page holds more than `limit` files, and no file outside the
  prefix appears.
* The prefix is plain text matched at the start of the key, at every depth.
* `limit` from 1 to 1000 and a `prefix` of up to 1024 bytes are accepted. The values
  just outside are 400 `InvalidInput`.
* A cursor this API did not produce, or one from another prefix, is 400 `InvalidInput`
  on both backends, without a provider call. `S3Storage` wraps the provider's token
  with its prefix, sends the token back unchanged, and turns the provider's
  `InvalidArgument` for a sent token (for example an expired one) into `InvalidInput`.
  It keeps `InvalidArgument` a `ProviderError` when no cursor was sent.
* A file that exists for the whole traversal appears once, even when other files are
  created between pages.
* The service makes exactly one storage call per request, with `prefix`, `limit`, and
  `cursor` passed through unchanged, and returns storage's page unchanged. Invalid
  input never reaches storage. A `ProviderError` or `ProviderUnavailable` from storage
  becomes 502 or 503 in the [error format](docs/API.md#error-format).
* The `list_files` contract in
  [storage/base.py](src/storage_service/storage/base.py) holds for `S3Storage`: a
  `list_objects_v2` answer becomes a `FilePage` with ETag quotes stripped,
  `content_type` `None`, and `NextContinuationToken` wrapped in `next_cursor`, and
  provider errors become `ProviderError` or `ProviderUnavailable`. Both backends match the prefix
  as text, at every depth, in UTF-8 byte order.

### Cases and boundaries

These follow the collection traversal example in `docs/testing.txt`. Expected keys are
written out by hand, not computed with the code under test.

* **Collection size against the limit.** With `limit=3`: n = 0, n = 2 (below the
  limit), n = 3 (at it), and n = 4 (one above it). The smallest limit, 1, with three
  files. Seven files at three per page, which takes at least three pages.
* **Prefix.** Neighbors just before and just after the prefix in sort order
  (`seven.txt` and `seven2/h.txt` around `seven/`). Look-alikes `docs2/c.txt`,
  `docsx.txt`, and `other/docs/d.txt`. A nested key, `docs/sub/b.txt`. The same files
  listed with `docs` instead of `docs/`.
* **Order.** Keys uploaded out of order, with uppercase, `.` against `/`, and a
  non-ASCII character.
* **Limits.** `limit` of 1 and 1000 are accepted; 0, 1001, and `abc` are rejected. A
  `prefix` of exactly 1024 bytes is accepted and 1025 bytes is rejected. It is built
  from `é`, two bytes each, to show that the limit counts bytes, not characters.
* **Changes between pages.** After the first page, one file is created before the
  position reached so far and one after it.
* **Cursors this API did not produce.** A plain string (`garbage`), a string shaped
  like a provider token (`abc123`), and a key name (`docs/a.txt`, which the old
  in-memory cursor format accepted), plus a real cursor sent with another prefix. On
  S3, also a bare provider token, a cursor with our mark but a broken body, and a real
  cursor sent with another prefix, none of which reach the provider. Also the same
  provider code with and without a cursor, to show that only a sent cursor becomes
  `InvalidInput`. The contract test sends a real cursor with another prefix on every
  backend, including OCI.
* **What storage answers (controlled storage).** A page with a cursor, given the
  caller's own cursor; the default parameters; each kind of invalid input; and each of
  the two provider errors.
* **What the provider answers (translation).** A page with more to come, with a plain
  MD5 ETag and a multipart ETag (`-2` suffix), and provider-only fields such as the
  storage class. The last page, without `NextContinuationToken`. No matches, where S3
  leaves out `Contents` entirely. Keys sent URL-encoded. `AccessDenied` (403) and
  `NoSuchBucket` (404): List names no file, so even a 404 must not become
  `FileNotFound`. A connection failure.

The tests follow the cursor until it is `null` and never require a particular number of
pages, because the contract allows short pages. The traversal helper fails after 50
pages, so a cursor that never runs out fails the test instead of hanging it.

### Tests

The tests reach storage in four ways, from fastest to slowest:

* **In-memory storage** (`client`): the API's behavior over a small real collection.
* **Controlled storage** (Level 4): `controlled_storage` is
  `create_autospec(StorageClient, instance=True, spec_set=True)`. It has exactly
  `StorageClient`'s methods and signatures, so a call with the wrong arguments fails,
  and it does only what a test tells it to. `controlled_client` passes it to
  `FileService` and then `create_app(service)`, the same path production uses with
  the `S3Storage` that `main.build_storage` creates. It does not imitate S3 at all.
  It shows what the service sends to storage and how storage's answers and failures
  reach the caller. It needs only the standard library, so these tests do not depend
  on `tests/fakes.py` (L4-FAKE), which records only the prefix of a List call.
* **Translation** (`stubbed_s3`, Level 3): the real `S3Storage` over a stubbed boto3
  client. The Stubber checks the request parameters and the response shape against
  the S3 API model.
* **Real provider** (`provider_client`): the whole path against a bucket.

None of the first three need network access or credentials.

HTTP behavior, on the in-memory backend through `create_app(service)`:

* [`test_list_returns_every_promised_field`](tests/test_list.py): 200; the body has
  exactly `files` and `next_cursor`; the file has exactly the five fields, with the
  right key and size, `content_type` `null`, the Create `etag` without quotes, and a
  UTC `last_modified` ending in `Z`.
* [`test_list_of_empty_storage_with_default_parameters_is_one_empty_page`](tests/test_list.py):
  `GET /files` with no parameters on empty storage returns
  `{"files": [], "next_cursor": null}`.
* [`test_traversal_returns_every_file_once_in_order`](tests/test_list.py), for n = 0,
  n < limit, n = limit, n = limit + 1, and limit = 1: following the cursor lists
  exactly the expected keys, in order, with no page over the limit and a file outside
  the prefix left out.
* [`test_seven_files_three_per_page_each_appear_once_in_order`](tests/test_list.py):
  all seven keys exactly once, in order, without the neighbors on either side.
* [`test_list_sorts_keys_by_their_utf8_bytes`](tests/test_list.py):
  `B.txt`, `a.txt`, `a/x.txt`, `b.txt`, `é.txt`.
* [`test_prefix_is_plain_text_matched_at_the_start_of_the_key`](tests/test_list.py):
  `docs/` lists only the two keys under it, nested one included; `docs` also lists
  `docs2/c.txt` and `docsx.txt`; `other/docs/d.txt` never appears.
* [`test_largest_limit_is_accepted`](tests/test_list.py): `limit=1000` returns 200.
* [`test_prefix_of_1024_bytes_is_accepted_and_1025_is_400`](tests/test_list.py): 200,
  then 400 `InvalidInput`.
* [`test_files_present_for_the_whole_traversal_appear_once_despite_changes`](tests/test_list.py):
  the three original files appear exactly once each.
* [`test_list_with_a_cursor_this_api_did_not_produce_is_400`](tests/test_list.py):
  `garbage`, `abc123`, and a key name (`docs/a.txt`, which the old in-memory cursor
  format accepted) each return 400 `InvalidInput`.
* [`test_list_with_a_cursor_from_another_prefix_is_400`](tests/test_list.py): a real
  `next_cursor` from `docs/` sent with `img/` returns 400 `InvalidInput`.
* [`test_list_pages_through_files_with_a_cursor`](tests/test_list.py) and
  [`test_list_rejects_an_out_of_range_limit`](tests/test_list.py), from before this
  section: two pages with a prefix; `limit` 0 and 1001 return 400. The error body for
  `limit` 0, 1001, and `abc` is checked in
  [tests/test_invalid_input.py](tests/test_invalid_input.py).

HTTP behavior over controlled storage:

* [`test_list_returns_the_page_storage_gives_and_passes_the_cursor_through`](tests/test_list.py):
  storage's page comes back as JSON unchanged, `next_cursor` included, and the only
  storage call is `list_files("docs/", 5, "cursor-from-caller")`.
* [`test_list_defaults_reach_storage_as_every_file_100_per_page`](tests/test_list.py):
  `GET /files` calls `list_files("", 100, None)`.
* [`test_invalid_list_input_never_reaches_storage`](tests/test_list.py), for `limit`
  0, 1001, and `abc`, and a 1025-byte prefix: 400 `InvalidInput`, and no storage call
  at all.
* [`test_list_reports_storage_failures_in_our_error_format`](tests/test_list.py):
  `ProviderError` gives 502 and `ProviderUnavailable` gives 503, each with exactly
  `error` and `detail`.

Translation, with `stubbed_s3` (no network):

* [`test_s3_list_translates_a_provider_page_into_a_file_page`](tests/test_list.py):
  `list_objects_v2` is called with the bucket, prefix, and `MaxKeys`, and no
  `ContinuationToken`. The answer becomes exactly the expected `FilePage`: quotes
  stripped from both ETags, `content_type` `None`, `NextContinuationToken` as
  `next_cursor`, and the provider-only fields left out.
* [`test_s3_list_sends_the_cursor_as_the_continuation_token`](tests/test_list.py):
  the cursor is sent as `ContinuationToken`; an answer without
  `NextContinuationToken` gives `next_cursor` `None`.
* [`test_s3_list_with_no_matches_is_an_empty_page`](tests/test_list.py): an answer
  without `Contents` gives an empty page, not an error.
* [`test_s3_list_returns_keys_decoded_when_the_provider_sends_them_url_encoded`](tests/test_list.py):
  boto3 asks for `EncodingType=url` and decodes the keys itself, so
  `docs/r%C3%A9sum%C3%A9.pdf` reaches callers as `docs/résumé.pdf`.
* [`test_s3_list_rejected_by_the_provider_raises_our_error`](tests/test_list.py):
  `AccessDenied` becomes `AccessDenied` and `NoSuchBucket` becomes `ProviderError`. The
  provider's code is in `provider_code`, not in the message.
* [`test_s3_list_turns_a_rejected_cursor_into_invalid_input`](tests/test_list.py):
  `InvalidArgument` (OCI's "unable to decode the token") for a request with a
  `ContinuationToken` becomes `InvalidInput`, and the provider's code is not in the
  message.
* [`test_s3_list_invalid_argument_without_a_cursor_is_still_a_provider_error`](tests/test_list.py):
  the same code without a cursor stays `ProviderError`.
* [`test_s3_list_that_cannot_reach_the_provider_raises_provider_unavailable`](tests/test_list.py):
  a connection failure becomes `ProviderUnavailable`. The Stubber cannot simulate one,
  so the test replaces the boto3 call. It also checks that the cause is the
  connection error. Without that check it could pass by mistake, because an unstubbed
  call ends as `ProviderUnavailable` too (the Stubber's error is a `BotoCoreError`).

Every backend, in
[tests/test_storage_contract.py](tests/test_storage_contract.py) (in-memory in the fast
suite, S3 with `-m provider`):

* `test_list_with_a_cursor_this_backend_did_not_produce_is_invalid_input`: `garbage`
  raises `InvalidInput`. On S3 this is the check that OCI really rejects it.
* `test_list_matches_the_prefix_as_text_at_every_depth_in_byte_order`: `docs/` lists
  `docs/B.txt`, `docs/a.txt`, `docs/sub/b.txt`, and `docs/é.txt`, in that order, and
  not `docs2/c.txt`.

Real provider (marked `provider`):

* [`test_list_pages_through_the_real_provider`](tests/test_list.py): seven files with
  uppercase, nested, and non-ASCII keys, listed three per page. At least three pages;
  the keys in UTF-8 byte order; `size` and `etag` equal to the Create response;
  `content_type` `null`; UTC `last_modified`. With `limit=7` (n = limit), the same
  seven keys.

**A test that detects a defect** (`docs/testing.txt` section 1.5). The in-memory backend
was changed to end the listing one file early whenever the last page would hold exactly
one file (`len(keys) > limit + 1` instead of `len(keys) > limit`). Five tests failed,
among them `test_traversal_returns_every_file_once_in_order[n=limit+1]`, which got
`p/a.txt` to `p/c.txt` instead of `p/a.txt` to `p/d.txt`, and
`test_seven_files_three_per_page_each_appear_once_in_order`, which was missing
`seven/g.txt`. The change was reverted, and all List tests pass again.

Two more changes were tried and reverted the same way. With the service passing `None`
instead of the caller's cursor, six tests failed. The controlled-storage test showed the
wrong call, and the traversal tests stopped at the 50-page limit instead of hanging.
With `S3Storage` keeping the ETag quotes in listings, the page translation test failed.

### Real-provider verification

#### Run by Faizal Rahman, with Claude Code (covering for Prateek)

- Provider: OCI Object Storage, us-ashburn-1
- Date: 2026-10-14
- Commit: b95bf89, plus this branch's changes (List tests, docs, and the `/docs`
  description)
- Request: seven one-byte files `a.txt` to `g.txt`, uploaded in the order g, c, e, a, f,
  b, d, under `P=api-tests/manual-list-72a78e9ab397440b8fae69f043abde02/`. Also one
  neighbor, `api-tests/manual-list-72a78e9ab397440b8fae69f043abde02-other/h.txt`,
  which sorts just before `P`. Then, with each cursor percent-encoded:
  ```bash
  curl -s "$B/files?prefix=$P&limit=3"
  curl -s "$B/files?prefix=$P&limit=3&cursor=<page 1 next_cursor>"
  curl -s "$B/files?prefix=$P&limit=3&cursor=<page 1 next_cursor>"   # the same cursor again
  curl -s "$B/files?prefix=$P&limit=3&cursor=<page 2 next_cursor>"
  curl -s "$B/files?prefix=$P&limit=7"
  ```
- Expected: 200 every time. Pages `a`–`c`, `d`–`f`, and `g`, with `next_cursor`
  `null` only on the last. The neighbor never appears. Repeating a cursor returns the
  same page. With `limit=7`, all seven files and `next_cursor` `null`.
- Observed (keys shortened to `P/`, cursors shortened):
  ```text
  page 1          200  P/a.txt P/b.txt P/c.txt   next_cursor "1:n3txocCZ..." (110 characters)
  page 2          200  P/d.txt P/e.txt P/f.txt   next_cursor "1:4cV6sgeJ..."
  page 2 again    200  P/d.txt P/e.txt P/f.txt   next_cursor "1:rnvcKuLw..."
  page 3          200  P/g.txt                   next_cursor null
  limit=7         200  P/a.txt ... P/g.txt       next_cursor null
  ```
  Page 3 in full:
  ```json
  {"files":[{"key":"api-tests/manual-list-72a78e9ab397440b8fae69f043abde02/g.txt","size":1,"content_type":null,"etag":"9dd4e461268c8034f5c8564e155c67a6","last_modified":"2026-10-14T20:30:21Z"}],"next_cursor":null}
  ```
  Every file had `"size":1`, `"content_type":null`, and the same `etag`. The
  `last_modified` values were `20:30:21Z` or `20:30:22Z`.
  `uv run --env-file .env pytest -m provider`: `8 passed, 50 deselected`. After the
  Level 3 and 4 changes on this branch, the same command gave `9 passed, 66 deselected`
  (the new contract test runs on S3 too).
- Cleanup: all eight deletes returned 204, and
  `GET /files?prefix=api-tests/manual-list-72a78e9ab397440b8fae69f043abde02` (no
  trailing slash, so the neighbor is included) returned `{"files":[],"next_cursor":null}`.

The example in [docs/API.md](docs/API.md#list) was also run as written against the
same bucket. Its output is the one shown there, and its prefix was empty afterwards.

#### Run by Prateek Saxena (second verifier)

- Provider: OCI Object Storage, us-ashburn-1, my own private test bucket
- Date: 2026-10-21
- Commit: 560ee5d (`dev` after #49, FIX-3), boto3 1.43.108
- Provider command: `uv run --env-file .env pytest -m provider -k list`
- Observed: `5 passed, 152 deselected`. This includes
  `test_list_with_a_cursor_this_backend_did_not_produce_is_invalid_input[s3]`, so
  FIX-3's contract test passes on OCI. The full `pytest -m provider` run on the same
  commit gave `16 passed, 141 deselected`.
- Cleanup: before and after the `-k list` run, the bucket held the same objects under
  `api-tests/` (left by an earlier run that failed on a new key's credentials) and none
  under `contract-tests/`. So the cleanup from #43, which reads every page, removed
  everything this run created.
- Manual requests against a local server started with
  `uv run --env-file .env uvicorn storage_service.main:create_app --factory --port 8765`,
  with `P` a fresh prefix and `<c>` the percent-encoded `next_cursor` of page 1:
  ```bash
  curl -i "$B/files?cursor=garbage"
  curl -i "$B/files?prefix=docs/&cursor=abc123"
  # upload one-byte files a.txt, b.txt, c.txt under $P
  curl "$B/files?prefix=$P&limit=2"
  curl "$B/files?prefix=$P&limit=2&cursor=<c>"
  curl -i "$B/files?prefix=other/&cursor=<c>"
  # delete the three files
  curl "$B/files?prefix=$P"
  ```
- Expected: 400 `InvalidInput` for both made-up cursors; `a.txt`, `b.txt` and a cursor,
  then `c.txt` and `next_cursor: null`; for the cursor sent with another prefix, either
  400 or a page decided by the provider (see the List assumptions in
  [docs/API.md](docs/API.md#list)); an empty listing after cleanup.
- Observed: both made-up cursors returned
  `400 {"error":"InvalidInput","detail":"cursor is not a next_cursor this API returned for this prefix"}`
  (502 `ProviderError` before FIX-3). Paging returned `a.txt`, `b.txt`, then `c.txt`
  with `next_cursor: null`. The cursor sent with `prefix=other/` returned
  `200 {"files":[],"next_cursor":null}`. All three deletes returned 204, and the
  listing was then `{"files":[],"next_cursor":null}`.

### Provider observations

* **A cursor from another prefix.** OCI does not reject it. A cursor from page 1 of
  `P`, sent with `prefix=other/`, returned 200 with an empty page and
  `next_cursor: null`, because `other/` sorts before the cursor's position. A prefix
  that sorts after it could return files. That is why `S3Storage` now wraps the token
  with its prefix and rejects the mismatch itself (#72).
* **Cursor format.** OCI's tokens, which our cursors wrap, are `1:` followed by about
  108 base64url characters, sometimes ending in `=`. They worked both percent-encoded
  and not, but callers should encode them, as the API docs say.
* **A new cursor string on every request.** Asking for the same page twice gave two
  different `next_cursor` strings, and both continued correctly. Nothing may compare
  cursor strings. This is now in the List assumptions in [docs/API.md](docs/API.md#list).
* **No cursor with an empty page.** With n = limit (seven files, `limit=7`), and on the
  last page of 3 + 3 + 1, OCI returned `next_cursor: null`. Every page before the last
  was full. The contract still allows short or empty pages with a cursor, and the tests
  rely on neither.
* **Order.** In the provider test, `C.txt`, `a.txt`, `a/x.txt`, `b.txt`, `e.txt`,
  `g.txt`, and `é.txt` came back in UTF-8 byte order, the same as the in-memory backend.
* **Timestamps.** OCI's `last_modified` has whole seconds; the in-memory backend has
  microseconds.

### Gaps

* **The Stubber checks shapes, not real answers.** Whether OCI really sends what the
  translation tests feed in is shown only by the provider tests.
* **Connection failures are simulated by replacing the boto3 call**, so botocore's own
  retries (up to 3 attempts) are not exercised.
* **Changes between pages** are tested only on the in-memory backend.
* **Short or empty pages that still have a cursor** never happened on OCI, so the
  "continue until `null`" rule was exercised only with full pages.
* **Cursor lifetime** and **more than 1000 matching files** are not tested.
