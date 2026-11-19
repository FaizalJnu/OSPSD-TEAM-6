# Working on this repository

Guidance for contributors and coding agents. Read `README.md` first for setup.

## Code map

```
src/storage_service/
  main.py            Builds the FastAPI app over the service from wiring.py
  wiring.py          Picks the storage backend (the only wiring point); imports no web framework
  config.py          Reads settings from environment variables
  routers/           HTTP layer: one module per operation, plus deps.py and error_handlers.py
  service.py         The rules: validation, create vs replace, size limits
  shared_storage.py  Tagged DocumentStorage adapter; streaming and bounded bytes compatibility
  errors.py          Our error types (plain Python, no HTTP)
  models.py          Data shapes: FileInfo, FilePage, FileDownload
  storage/base.py    The StorageClient contract every backend implements
  storage/s3.py      S3-compatible backend (the only module that imports boto3)
  storage/memory.py  In-memory backend for tests and local experiments
tests/
  conftest.py              Shared fixtures: in-memory client, FakeStorage client, stubbed S3, real-provider client
  test_upload.py           POST and PUT /files/{key} (create and replace)
  test_download.py         GET /files/download?path=
  test_metadata.py         GET /files/metadata?path=
  test_bucket_errors.py    Missing-bucket errors across metadata and existence checks
  test_delete.py           DELETE /files?path=
  test_move.py             PATCH /files?path= (move: copy, then delete)
  test_list.py             GET /files
  test_service.py          Input rules
  test_storage_contract.py Same tests for every backend; S3 runs only with -m provider
  test_invalid_input.py    FastAPI's own input rejections also return 400 InvalidInput
  test_injection.py        Application tests: storage calls, provider failures, how the app is built
  test_failures.py         The error model across operations: access denial, sanitized errors, failure logs,
                           errors outside any operation, and the errors /openapi.json lists
  fakes.py                 FakeStorage: records calls, raises configured errors, cuts downloads off
  test_cleanup.py          The provider-test cleanup helper follows every page
  test_health.py           GET /health and GET /health/provider
  test_packaging.py        The shared adapter installs and imports without the HTTP service
docs/
  API.md             HTTP contract: keys, file info, errors, one section per operation
  PROVIDERS.md       Settings and provider-test results for each S3-compatible provider
TESTING.md           Check commands, test layout, fixtures, and each operation's test record
```

Each operation's file holds all of its tests: HTTP behavior on the in-memory
backend (`client`), translation of provider responses and errors (`stubbed_s3`,
no network), and checks against a real bucket (`provider_client`, marked
`@pytest.mark.provider`).

## Architecture rules

* Dependencies point one way: `routers` -> `service` -> `storage.base` <- backends.
* Only `routers/` and `main.py` import FastAPI. FastAPI, Uvicorn and
  python-multipart are in the `server` extra, so other teams can install the
  shared adapter without them. Only `storage/s3.py` imports boto3 or botocore. Provider SDK types and exceptions never leave their backend.
  (Tests may use botocore's `Stubber` to test `storage/s3.py` without network.)
* The service never mentions HTTP status codes. Routes never contain rules.
* A new backend is one new module in `storage/` that passes
  `tests/test_storage_contract.py`, plus one branch in `wiring.build_storage`.
* Stream file contents. Never read a whole file into memory outside tests and
  `storage/memory.py`, except the explicit legacy `DocumentStorage.download`
  compatibility method in `shared_storage.py`, capped at 150 MiB. HTTP downloads
  must use `open_download`; they never use the legacy bytes method.

## Commands

```bash
uv sync                                    # install exactly what uv.lock says
uv run pytest                              # fast tests, no network
uv run --env-file .env pytest -m provider  # only the real-provider tests
uv run mypy                                # type check (strict on src/)
uv run ruff check --fix . && uv run ruff format .
```

CI runs lint, the format check, the type check, and the fast tests on every pull
request, every push to `main`, and every release tag. All must pass to merge.

## Contribution rules

* Small pull requests with one purpose, linked to an issue. At least one human
  review before merging. Task ownership, merge rules, versioning, and releases
  are in `CONTRIBUTING.md`.
* Annotate every function in `src/`. mypy runs in strict mode there.
* New behavior comes with tests. A bug fix starts with a failing test.
* Anything that needs a real bucket is marked `@pytest.mark.provider`. The fast
  suite must stay free of network access and credentials.
* Say in the pull request if code was written with an AI assistant. The person
  who opens the pull request must be able to explain every line.
* Add dependencies with `uv add` and commit `uv.lock`. Justify new dependencies
  in the pull request.
* Never commit `.env` or any credential. Update `.env.example` when adding a setting.
