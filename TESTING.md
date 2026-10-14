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
Tests: [tests/test_download.py](tests/test_download.py).

### Contract checked

* A 200 returns the exact stored bytes with every promised header: `Content-Type`,
  `Content-Length`, the quoted `ETag`, `Content-Disposition`, and
  `X-Content-Type-Options`.
* The header values agree with the file's info: the `ETag` is the Metadata `etag` in
  quotes, and `Content-Length` is the size.
* An invalid key returns 400 `InvalidInput`, and a missing file returns 404
  `FileNotFound`, both in the error format.
* The `get` contract in `storage/base.py` holds for `S3Storage`: a `get_object` answer
  becomes `FileInfo` plus chunks, provider errors become our errors, and the provider
  stream is closed after reading.

### Cases and boundaries

* **Key shape:** a key with a folder and non-ASCII characters (`docs/résumé.pdf`),
  because `Content-Disposition` drops the folder and percent-encodes the name. An
  invalid key (`a//b.txt`) and a missing key cover the two rejections.
* **Content type:** a known binary type (`.pdf`), a text type (`.txt`, which gains
  `; charset=utf-8`), and an unknown extension (falls back to
  `application/octet-stream`).
* **Size:** small files in the fast tests. On the real provider, 5 MiB, so the download
  streams as several 1 MiB chunks.
* **Provider errors:** `NoSuchKey` (404) and `AccessDenied` (403), one for each of the
  two translations in `_translate_errors`.
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
* [`test_download_with_an_invalid_key_is_400`](tests/test_download.py): 400, a body
  with exactly `error` and `detail`, and `InvalidInput`.
* [`test_download_of_a_missing_file_is_404`](tests/test_download.py): 404, a body with
  exactly `error` and `detail`, and `FileNotFound`.

Translation, with `stubbed_s3` (no network):

* [`test_s3_get_translates_the_response_into_file_info_and_chunks`](tests/test_download.py):
  `get_object` is called with the right bucket and key; the answer becomes the expected
  `FileInfo` (ETag quotes stripped), and the chunks join to the original bytes.
* [`test_s3_get_of_a_missing_key_raises_file_not_found`](tests/test_download.py):
  `NoSuchKey` becomes `FileNotFound`.
* [`test_s3_get_closes_the_provider_stream`](tests/test_download.py): the provider
  stream is closed after every chunk is read, and after a caller closes the chunks
  following the first one.
* [`test_s3_get_rejected_by_the_provider_raises_provider_error`](tests/test_download.py):
  `AccessDenied` becomes `ProviderError`.

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

* **A provider failure mid-stream cuts the body off.** Once the 200 headers are sent,
  the status can no longer change. Verified with a test double whose chunks raise
  `ProviderUnavailable` after 11 of 100 bytes, served by uvicorn: curl received
  `200`, `content-length: 100`, then 11 bytes, and exited with code 18 (partial file);
  there was no error body. The server logged `Exception in ASGI application`. With
  `S3Storage`, an error while reading chunks also is not translated into our errors
  (see the `get` docstring). Callers can detect the cut by comparing the received size
  with `Content-Length`. Not covered by an automated test.
* **A download dropped before its first chunk does not close the provider stream.**
  `S3Storage` closes the stream in a generator's `finally`, which only runs once the
  generator has started. Tracked in [#15](https://github.com/FaizalJnu/OSPSD-TEAM-6/issues/15).
* **`ProviderUnavailable` from `get` is not tested here.** The Stubber can only queue
  answers and client errors, not connection failures. L4-FAKE adds an HTTP test for a
  503.
* **Client disconnects are not tested.** When Starlette stops reading the chunks after
  a client disconnects, and whether it closes them, is not established here.

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
