# Working on this repository

Guidance for contributors and coding agents. Read `README.md` first for setup.

## Code map

```
src/storage_service/
  main.py            Builds the app and picks the storage backend (the only wiring point)
  config.py          Reads settings from environment variables
  routes.py          HTTP layer: endpoints, request parsing, error-to-status mapping
  service.py         The rules: validation, create vs replace, size limits
  errors.py          Our error types (plain Python, no HTTP)
  models.py          Data shapes: FileInfo, FilePage, FileDownload
  storage/base.py    The StorageClient contract every backend implements
  storage/s3.py      S3-compatible backend (the only module that imports boto3)
  storage/memory.py  In-memory backend for tests and local experiments
tests/
  test_api.py              HTTP behavior, in-memory backend
  test_service.py          Input rules
  test_storage_contract.py Same tests for every backend; S3 runs only with credentials
```

## Architecture rules

* Dependencies point one way: `routes` -> `service` -> `storage.base` <- backends.
* Only `routes.py` and `main.py` import FastAPI. Only `storage/s3.py` imports
  boto3 or botocore. Provider SDK types and exceptions never leave their backend.
* The service never mentions HTTP status codes. Routes never contain rules.
* A new backend is one new module in `storage/` that passes
  `tests/test_storage_contract.py`, plus one branch in `main.build_storage`.
* Stream file contents. Never read a whole file into memory outside tests and
  `storage/memory.py`.

## Commands

```bash
uv sync                                    # install exactly what uv.lock says
uv run pytest                              # fast tests, no network
uv run --env-file .env pytest              # include real-provider contract tests
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
* Say in the pull request if code was written with an AI assistant. The person
  who opens the pull request must be able to explain every line.
* Add dependencies with `uv add` and commit `uv.lock`. Justify new dependencies
  in the pull request.
* Never commit `.env` or any credential. Update `.env.example` when adding a setting.
