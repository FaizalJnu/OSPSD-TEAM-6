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
| [tests/test_download.py](tests/test_download.py) | Download: `GET /files/{key}` |
| [tests/test_metadata.py](tests/test_metadata.py) | Metadata: `GET /metadata/{key}` |
| [tests/test_delete.py](tests/test_delete.py) | Delete: `DELETE /files/{key}` |
| [tests/test_list.py](tests/test_list.py) | List: `GET /files` |
| [tests/test_service.py](tests/test_service.py) | The key rules and the content-type choice, without HTTP |
| [tests/test_storage_contract.py](tests/test_storage_contract.py) | The same tests for every storage backend |

Each operation's file holds all of that operation's tests. There are three kinds:

| Kind | Fixture | Needs | What it shows |
|---|---|---|---|
| HTTP behavior | `client` | Nothing | Statuses, bodies, headers, and effects through the API, on the in-memory backend |
| Translation | `stubbed_s3` | Nothing | How `S3Storage` turns provider responses and errors into our types and errors |
| Real provider | `provider_client`, marked `provider` | A bucket in `.env` | The operation end to end against a real provider |

Add tests to your own operation's file. A fixture that only one operation needs goes
in that file, not in `conftest.py`.

`tests/test_storage_contract.py` runs the same tests against every storage backend to
check that the in-memory test double behaves like the real provider. They check the
rules written in `storage/base.py`. The `memory` run is part of the fast suite; the
`s3` run is marked `provider`.

## Fixtures

From [tests/conftest.py](tests/conftest.py):

* **`client`:** a `TestClient` for a fresh app over empty in-memory storage, so tests
  never share state. Its upload limit is `MAX_UPLOAD_BYTES`, 1024 bytes, so size tests
  stay small.
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
* **`load_provider_settings()`:** a helper that returns the settings from the
  environment, or fails the test with a hint if they do not configure the `s3`
  backend. The contract tests use it too.

[tests/test_delete.py](tests/test_delete.py) has one example test for `stubbed_s3` and
one for `provider_client`.

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
* `provider_client` and the contract tests clean up with one listing of at most 1000
  keys. A test that writes more than 1000 files under its prefix leaves the rest
  behind.
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
`ProviderError` or `ProviderUnavailable`, never as a missing file. A failed
probe does not establish whether the bucket is absent or access is denied.

The change stays in [storage/s3.py](src/storage_service/storage/s3.py).
`service.py`, startup wiring, and the shared error translator are unchanged.
Compared with a startup check, the probe keeps startup free of network calls
and handles bucket failures discovered after startup. It costs an extra SDK
call on each ambiguous miss and needs bucket-read permissions. Separate HEAD
calls are not an atomic snapshot.

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

After the fix, source commit `e487ada`, the command
`uv run --locked --env-file ../../../OSPSD-TEAM-6/.env pytest -m provider
tests/test_bucket_errors.py --tb=short --show-capture=no -p no:cacheprovider`
observed **2 passed, 13 deselected**. The env-file path refers to the existing
configuration in the main checkout; credentials were not copied or displayed.
The normal command in a single checkout remains `uv run --env-file .env pytest
-m provider tests/test_bucket_errors.py`.

`test_nonexistent_real_bucket_is_a_provider_error` observed 502 `ProviderError`
with the public error shape for all three requests above. It used a unique
bucket name that was never created. `test_missing_file_in_real_bucket_remains_404`
observed 404 `FileNotFound` for a unique nonexistent key in the accessible test
bucket. Both checks passed; the provider fixture also completed cleanup.

No objects were written by these checks. Provider tests remain explicitly
selectable and fail rather than skip if configuration is missing. Human review
and a second person's independent verification by Faizal remain pending.

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
Tests: [tests/test_upload.py](tests/test_upload.py). Not written yet.

### Contract checked

### Cases and boundaries

### Tests

### Real-provider verification

### Provider observations

### Gaps

## Download

Owner: **Vikram Markali**. Contract: [docs/API.md](docs/API.md#download).
Tests: [tests/test_download.py](tests/test_download.py). Not written yet.

### Contract checked

### Cases and boundaries

### Tests

### Real-provider verification

### Provider observations

### Gaps

## Metadata

Owner: **Darsh Shani**. Contract: [docs/API.md](docs/API.md#metadata).
Tests: [tests/test_metadata.py](tests/test_metadata.py). Not written yet.

### Contract checked

### Cases and boundaries

### Tests

### Real-provider verification

### Provider observations

### Gaps

## Delete

Owner: **Faizal Rahman**. Contract: [docs/API.md](docs/API.md#delete).
Tests: [tests/test_delete.py](tests/test_delete.py). Not written yet.

### Contract checked

### Cases and boundaries

### Tests

### Real-provider verification

### Provider observations

### Gaps

## List

Owner: **Prateek Saxena**. Contract: [docs/API.md](docs/API.md#list).
Tests: [tests/test_list.py](tests/test_list.py). Not written yet.

### Contract checked

### Cases and boundaries

### Tests

### Real-provider verification

### Provider observations

### Gaps
