Title: Bump the version to 0.2.0

## Which issue does this PR close?
Closes #<release issue>

## Problem and resulting behavior
The `v0.2.0` tag is on `main` at 97533b9, but `pyproject.toml` there still says
`0.1.0`, so the running API reports the wrong version.

Before: `GET /openapi.json` returns `"info": {"title": "Storage Service", "version": "0.1.0"}`.
After: it returns `"version": "0.2.0"`. The installed package metadata
(`importlib.metadata.version("storage-service")`) also says 0.2.0.

## Approach and why
`uv version --bump minor`, the command CONTRIBUTING.md prescribes. It updates
`pyproject.toml` and `uv.lock` together. MINOR, not PATCH, because this release
contains breaking API changes (listed in the release issue).

Once this reaches `main`, the existing `v0.2.0` tag is deleted and recreated on the
new `main` commit. The release issue explains why moving this tag is acceptable once.

## What changed
- `pyproject.toml`: `version` 0.1.0 to 0.2.0.
- `uv.lock`: the `storage-service` package entry, 0.1.0 to 0.2.0.

## How it was verified
- `uv run pytest`: 325 passed, 29 deselected.
- `create_app().version` returns `0.2.0` (FastAPI reads the version from package
  metadata, see `main.py`).
- No tests added: no behavior changed.
- Real-provider check: not needed for the bump. The full provider suite runs on the
  `main` commit before tagging (release step 4).

## Status
- What works: the version is 0.2.0 everywhere it is reported.
- What remains: `dev` to `main` PR, provider tests, re-tag, GitHub release.
- Who owns the next steps: Faizal (release manager).
- Blocked on: review of this PR.

## AI assistance
Claude Code ran `uv version --bump minor`, ran the tests, and drafted this
description. I reviewed every line and can explain it.

## Checklist
- [x] Linked to an issue, one purpose
- [x] ruff check, ruff format --check, mypy, and pytest pass locally; CI is green
- [x] Tests cover the new behavior; a bug fix starts with a failing test
- [x] docs/API.md, TESTING.md, and README updated where behavior or setup changed
- [x] No .env, keys, or other secrets committed
- [ ] I reviewed my own diff
