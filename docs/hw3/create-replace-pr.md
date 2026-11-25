Title: Move Create and Replace to the shared POST /files and PUT /files routes

Base: dev. Branch: shared-create-replace-routes

## Which issue does this PR close?
Closes #<issue number>

## Problem and resulting behavior
Create and Replace were the last operations not on the shared contract's routes. The
shared contract sends `POST /files` and `PUT /files` with the form fields `path` and
`file`, and our service answered 405. That made 46 of the 55 shared conformance tests
fail against our routes, because they create their files with `POST /files`.

Before:
```text
curl -F "path=docs/a.txt" -F "file=@a.txt" $B/files
405 {"error": {"code": "method_not_allowed", "message": "this path does not accept POST"}}
Allow: DELETE, GET, PATCH
```

After:
```text
curl -F "path=demo/me/hello.txt" -F "file=@hello.txt" $B/files
201 {"id":null,"name":"hello.txt","path":"/demo/me/hello.txt","size":5,"modified_at":"2026-11-25T22:40:51.408414Z","etag":"5d41402abc4b2a76b9719d911017c592","type":null,"content_type":"text/plain"}
```
The same request again returns 409 `conflict`. `PUT /files` with the same fields returns
200 with the new size and etag. `PUT` on a missing file returns 404 `not_found`.

## Approach and why
* `POST /files` and `PUT /files` read `path` and `file` from the form and return the
  shared file info, the same model as Metadata and Move. The path follows the same rules
  as every other `?path=` route, with or without its leading `/`.
* New service methods `create_at` and `replace_at` turn the path into a key and call the
  existing `create` and `replace`. All the existing rules (existence check, size limit,
  content type from the extension) stay in one place, and the route holds no rules.
* The old `POST /files/{key}` and `PUT /files/{key}` routes still work and are marked
  `deprecated` in `/docs` and `/openapi.json`. Removing them would break any caller
  still using them, and nothing requires their removal yet. They keep returning the
  legacy file info (`key`, `last_modified`).
* Both pairs of routes log failures under the same operation names, `create_file` and
  `replace_file`, so failure-log queries and dashboards do not change.
* FastAPI treats an empty form field as missing, so `path=""` returns 400
  `path: Field required` instead of a path-rule message. Both are `invalid_request`.
* Not a breaking change: every request that worked before still works. The only visible
  difference for old requests is that `/files` now lists `POST` and `PUT` in a 405's
  `Allow` header.

## What changed
- `src/storage_service/routers/upload.py`: the new `POST /files` and `PUT /files` routes; the `/files/{key}` routes renamed `create_file_by_key` and `replace_file_by_key`, marked deprecated, and still logged as `create_file` and `replace_file`.
- `src/storage_service/service.py`: `create_at` and `replace_at`, Create and Replace for a file named by its path.
- `src/storage_service/routers/deps.py`: `PathForm`, the `path` form field, sharing its description with `PathQuery`.
- `src/storage_service/routers/error_handlers.py`: docstring only (the multipart body now has a `path` field too).
- `src/storage_service/routers/__init__.py`: route list in the docstring (also fixes the stale List row).
- `deploy/smoke-check.sh`: creates its test file with `POST /files`.
- `tests/conftest.py`: `send_file` now uses `/files` with a `path` field; new `send_file_by_key` for the deprecated routes.
- `tests/test_upload.py`: tests for the new routes and the deprecated ones (below).
- `tests/test_failures.py`: 405 examples no longer use `POST /files`; the unreadable-body test covers both routes; OpenAPI error list includes the new routes.
- `tests/test_injection.py`: the route inventory includes the new routes, and a key with folders reaches all four upload routes.
- `tests/test_bucket_errors.py`, `tests/test_invalid_input.py`: use the new routes.
- `tests/test_metadata.py`: sends the 1023-byte key raw in the form (a form field is not percent-decoded).
- `tests/test_list.py`: the provider test reads `path` from the Create response instead of `key`.
- `docs/API.md`: Create and Replace section rewritten for the new routes, with a migration note; operations table, keys, paths, file info and error table updated.
- `README.md`: curl examples and route table use the new routes; the deprecated routes are listed; the List row now says `?path=`.
- `TESTING.md`, `AGENTS.md`: test layout rows and the `send_file` helper.

## How it was verified
- Fast checks: `uv run pytest`: 357 passed, 29 deselected. `uv run ruff check .`,
  `uv run ruff format --check .` and `uv run mypy`: clean.
- New tests in `tests/test_upload.py`:
  - Create returns the shared file info with every field, and Metadata right
    afterwards returns exactly the same object.
  - `docs/notes.txt` and `/docs/notes.txt` name the same file: the second Create is a
    409, and Replace works with either form.
  - The path reaches storage as its key (`put` on `docs/notes.txt`).
  - Both form fields are required, for POST and PUT: missing `path`, empty `path`, and
    missing `file` each give 400 `invalid_request` and make no storage call.
  - Paths that break a rule (`/`, trailing `/`, `//`, `.`, `..`, a control character,
    over 1024 bytes) give 400 before any storage call, for POST and PUT.
  - The deprecated routes still create and replace, return the legacy file info, follow
    the key rules, and name the same file as the new routes.
  - OpenAPI marks only the `/files/{key}` routes as deprecated.
- Smoke check: `deploy/smoke-check.sh` against a local server on the in-memory backend:
  every step ok, "Smoke check passed".
- The curl examples in README.md and docs/API.md were run against a local server and
  returned the documented statuses.
- Real-provider check: not run yet. The provider tests now create through `POST /files`:
  `uv run --env-file .env pytest -m provider`.
- Shared conformance suite: not run yet against this branch.

## Status
- What works: Create and Replace on the shared routes, with the old routes kept.
- What remains / known gaps: run the provider tests and the shared conformance suite
  against this branch; then add the conformance job to CI. Remove the deprecated routes
  in a later release.
- Who owns the next steps: <name>
- Blocked on: nothing.

## AI assistance
Claude Code wrote the code, tests and doc changes in this PR from my instructions.
<!-- Confirm after reviewing the diff: -->
I reviewed every line and can explain it.

## Checklist
- [x] Linked to an issue, one purpose
- [ ] ruff check, ruff format --check, mypy, and pytest pass locally; CI is green
- [x] Tests cover the new behavior; a bug fix starts with a failing test
- [x] docs/API.md, TESTING.md, and README updated where behavior or setup changed
- [x] No .env, keys, or other secrets committed
- [ ] I reviewed my own diff
