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
| [tests/test_invalid_input.py](tests/test_invalid_input.py) | Invalid input that FastAPI rejects first (a bad List `limit`, a missing `file` field) returns 400 `InvalidInput` |
| [tests/test_injection.py](tests/test_injection.py) | Application tests over a controlled backend: storage calls made, provider failures, and how the app is built |
| [tests/fakes.py](tests/fakes.py) | `FakeStorage`, the controlled backend (below) |

Each operation's file holds all of that operation's tests. There are three kinds:

| Kind | Fixture | Needs | What it shows |
|---|---|---|---|
| HTTP behavior | `client` | Nothing | Statuses, bodies, headers, and effects through the API, on the in-memory backend |
| Translation | `stubbed_s3` | Nothing | How `S3Storage` turns provider responses and errors into our types and errors |
| Real provider | `provider_client`, marked `provider` | A bucket in `.env` | The operation end to end against a real provider |

Add tests to your own operation's file. A fixture that only one operation needs goes
in that file, not in `conftest.py`.

### Controlled storage

[`FakeStorage`](tests/fakes.py) is a `StorageClient` for application tests. Build the
app with `create_app(FileService(fake, max_upload_bytes=...))`, as
[tests/test_injection.py](tests/test_injection.py) does. It:

* records each call in `fake.calls` as `(method, key)`, in order. `list_files` records
  its prefix instead of a key.
* raises a given error from a given method after `fake.fail(method, error)`, on every
  later call. The method name is typed, so mypy rejects a misspelled one.
* otherwise passes each call to a wrapped `InMemoryStorage`.

mypy checks that it satisfies `StorageClient` through a typed assignment at the end of
the file. Its assumptions:

* Without a configured failure, it behaves exactly like `InMemoryStorage`, which
  `tests/test_storage_contract.py` checks against the real provider.
* A configured failure is raised before the store is touched, so a failed `put` stores
  nothing. A real provider makes no such promise (see "After a failed write" in
  [docs/API.md](docs/API.md#after-a-failed-write)), so do not use the fake to test what
  a failed write left behind.

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
* `test_s3_put_turns_a_provider_rejection_into_provider_error`
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

### Provider observations

- OCI returns AWS-style multipart ETags: a 12 MiB upload came back as `<hash>-2`, two
  parts at boto3's 8 MB part size.
- Single-part ETags are the MD5 of the contents (`8b04d5...` is the MD5 of `first`);
  multipart ETags are not.
- `last_modified` has one-second precision: a Create and a Replace in the same second both
  reported `20:40:45Z`. Compare `etag`, not `last_modified`, to detect a change.
- Uploads to OCI need the FIX-1 checksum settings until FIX-1 merges; without them every
  upload returns 502.

### Gaps

* Level 2 asks for two people per operation. Replace has only been run on OCI by its
  owner so far; Create was also exercised in Darsh's metadata run.
* Error cases (409, 413) and files near the 1 GiB limit have not been run on OCI.
* The race between the existence check and the write is documented in
  [docs/API.md](docs/API.md#create-and-replace) but not tested.
* The multipart path is covered only by the `provider` test and the manual run, not by
  the fast suite.
* The stub test does not pin the upload's parameters, because boto3 adds a checksum
  parameter that FIX-1 changes.

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
* **Size:** small files in the fast tests, and 10 bytes read with a 4-byte chunk size to
  check that the download is split into chunks, including a short last one. On the real
  provider, 5 MiB, to check a multi-megabyte round trip.
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
* [`test_s3_get_streams_in_chunks`](tests/test_download.py): with the chunk size set to
  4 bytes, a 10-byte file arrives as chunks of 4, 4, and 2 bytes, so the backend streams
  instead of reading the whole file at once.
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
  there was no error body. The server logged `Exception in ASGI application`. Callers
  can detect the cut by comparing the received size with `Content-Length`. Not covered
  by an automated test.
* **`S3Storage` lets a mid-stream SDK error escape.** When the connection drops while
  chunks are being read, botocore's `ResponseStreamingError` leaves the backend instead
  of becoming `ProviderUnavailable`, which breaks the `get` contract and the AGENTS.md
  rule. Tracked in [#26](https://github.com/FaizalJnu/OSPSD-TEAM-6/issues/26).
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
  `NoSuchKey` becomes `FileNotFound`; explicit `NoSuchBucket` and
  `AccessDenied` become `ProviderError`; connection errors become
  `ProviderUnavailable`.

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
prefixes were used. A second teammate still needs to repeat verification.

### Provider observations

The first live attempt returned 502 `ProviderError` with code `NotImplemented`
on upload. Inspection showed boto3's checksum mode was `when_supported`,
matching the team's existing FIX-1 report. Setting
`AWS_REQUEST_CHECKSUM_CALCULATION=when_required` and
`AWS_RESPONSE_CHECKSUM_VALIDATION=when_required` in the ignored local `.env`
made the same provider test pass. No production upload fix is included here.

HEAD and LIST returned equal UTC timestamps with whole-second precision for
this sample. This observation does not promise identical precision on every
provider or request. Ambiguous HEAD 404s (FIX-2) remain a separate change.

### Gaps

* Darsh's local automated and manual OCI verification is recorded above. A
  second person's independent provider run and Faizal's review remain pending.
* The missing-bucket HEAD 404 ambiguity is intentionally handled in a separate
  FIX-2 / BUG-BUCKET change; no missing-bucket fix is claimed here.
* The controlled fake does not validate authentication, provider availability,
  or SDK retry behavior. Stubber validates request parameters and translation,
  not whether the provider actually returns these responses.
* Level 5 error-model and structured-logging work remains outside this task.

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
* A file that exists for the whole traversal appears once, even when other files are
  created between pages.
* The service makes exactly one storage call per request, with `prefix`, `limit`, and
  `cursor` passed through unchanged, and returns storage's page unchanged. Invalid
  input never reaches storage. A `ProviderError` or `ProviderUnavailable` from storage
  becomes 502 or 503 in the [error format](docs/API.md#error-format).
* The `list_files` contract in
  [storage/base.py](src/storage_service/storage/base.py) holds for `S3Storage`: a
  `list_objects_v2` answer becomes a `FilePage` with ETag quotes stripped,
  `content_type` `None`, and `NextContinuationToken` as `next_cursor`, and provider
  errors become `ProviderError` or `ProviderUnavailable`. Both backends match the prefix
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
* [`test_s3_list_rejected_by_the_provider_raises_provider_error`](tests/test_list.py):
  `AccessDenied` and `NoSuchBucket` both become `ProviderError`.
* [`test_s3_list_that_cannot_reach_the_provider_raises_provider_unavailable`](tests/test_list.py):
  a connection failure becomes `ProviderUnavailable`. The Stubber cannot simulate one,
  so the test replaces the boto3 call. It also checks that the cause is the
  connection error. Without that check it could pass by mistake, because an unstubbed
  call ends as `ProviderUnavailable` too (the Stubber's error is a `BotoCoreError`).

Every backend, in
[tests/test_storage_contract.py](tests/test_storage_contract.py) (in-memory in the fast
suite, S3 with `-m provider`):

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

### Provider observations

* **Cursor format.** OCI cursors are `1:` followed by about 108 base64url characters,
  sometimes ending in `=`. They worked both percent-encoded and not, but callers should
  encode them, as the API docs say.
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

* **A second person's provider run.** Only Faizal has run List against a real provider.
  Level 2 needs two people, so the reviewer should run
  `uv run --env-file .env pytest -m provider -k list` against their own bucket and add a
  record above.
* **Malformed cursors**, and cursors reused with another prefix, belong to BUG-CURSOR
  ([FIX-3](fixesRequired.md#fix-3-a-malformed-list-cursor-returns-the-wrong-error)).
* **The Stubber checks shapes, not real answers.** Whether OCI really sends what the
  translation tests feed in is shown only by the provider tests.
* **Connection failures are simulated by replacing the boto3 call**, so botocore's own
  retries (up to 3 attempts) are not exercised.
* **Changes between pages** are tested only on the in-memory backend.
* **Short or empty pages that still have a cursor** never happened on OCI, so the
  "continue until `null`" rule was exercised only with full pages.
* **Cursor lifetime** and **more than 1000 matching files** are not tested.
