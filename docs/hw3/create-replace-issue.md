Title: [Feature]: Move Create and Replace to the shared POST /files and PUT /files routes

Labels: enhancement

## Problem / Motivation

Create and Replace are the only operations that are still not on the shared contract's
routes. The shared contract creates a file with `POST /files` and replaces it with
`PUT /files`, sending a `multipart/form-data` body with two fields: `path` and `file`.
Our service only has `POST /files/{key}` and `PUT /files/{key}`, with the key in the URL,
so `POST /files` returns 405 `method_not_allowed`.

Because of this, our routes fail the shared conformance suite. The last run against our
routes (TESTING.md, "Shared conformance suite") had 49 failed and 6 passed. 46 of the
failures were tests that create their files with `POST /files` and got 405. The suite
cannot check our other routes until Create works, and CI cannot run the suite until it
passes.

## Proposed Solution

* Add `POST /files` (Create, 201) and `PUT /files` (Replace, 200). Both take the
  `path` and `file` form fields and return the shared file info, like Metadata and Move.
* The path follows the same rules as every other `?path=` route.
* Keep `POST /files/{key}` and `PUT /files/{key}` working, marked deprecated in the
  OpenAPI schema, so no existing caller breaks. Remove them in a later release.
* Update `deploy/smoke-check.sh`, which creates its test file with the old route.

## Acceptance Criteria

- [ ] `POST /files` creates a file and returns 201 with `path`, `name`, `size`,
      `modified_at`, `etag`; a second Create at the same path returns 409 `conflict`
- [ ] `PUT /files` replaces an existing file (200) and returns 404 `not_found` for a
      missing one
- [ ] A missing or empty `path` field, a missing `file` field, or a path that breaks a
      path rule returns 400 `invalid_request` without a storage call
- [ ] The deprecated `/files/{key}` routes still work and are marked deprecated
- [ ] The smoke check and the docs (API.md, README, TESTING.md) use the new routes
- [ ] ruff, mypy and the fast tests pass

## Alternatives Considered

* Remove the `/files/{key}` routes now. That breaks any caller still using them with no
  warning, and the shared contract does not require their removal.
* Run the conformance suite against our shared adapter instead of our routes. That
  already passes 55/55, but it checks the suite's HTTP layer, not ours.

## Example Usage

```bash
curl -F "path=docs/report.pdf" -F "file=@report.pdf" $B/files          # 201
curl -X PUT -F "path=docs/report.pdf" -F "file=@new.pdf" $B/files      # 200
```
