Title: Bring the v0.2.0 version bump to main

## Which issue does this PR close?
Part of #104 (Release v0.2.0). The issue stays open until the tag and the GitHub
release are done.

## Problem and resulting behavior
`main` already has all of the v0.2.0 work from #102, and the `v0.2.0` tag points
at that commit (97533b9). But `pyproject.toml` there still says `0.1.0`, so the
running API reports the wrong version.

Before: `GET /openapi.json` returns `"info": {"title": "Storage Service", "version": "0.1.0"}`.
After: it returns `"version": "0.2.0"`.

The only change this PR brings to `main` is #105, the version bump.

## Approach and why
#102 was squash-merged, so `main` does not contain `dev`'s commits, only their
content. GitHub therefore lists about 80 commits on this PR, but **Files changed
shows only two one-line changes**. A local test merge of `dev` into `main` is clean
and changes only `pyproject.toml` and `uv.lock`.

**Merge with "Create a merge commit", not squash.** A merge commit makes `dev` an
ancestor of `main`. Next week's `dev` to `main` PR then lists only new commits and
cannot conflict with this one.

After this merges, the release manager:
1. Confirms CI passed on the new `main` commit.
2. Runs the real-provider tests (`uv run --env-file .env pytest -m provider`).
3. Deletes the existing `v0.2.0` tag and recreates it as an annotated tag on the new
   `main` commit. Nobody has installed the old tag and it has no GitHub release.
   #104 explains why moving the tag is acceptable this once.
4. Publishes the GitHub release with the breaking changes listed in #104.

## What changed
- `pyproject.toml`: `version` 0.1.0 to 0.2.0 (#105).
- `uv.lock`: the `storage-service` package entry, 0.1.0 to 0.2.0 (#105).

## How it was verified
- `uv run pytest`: 325 passed, 29 deselected. ruff check, ruff format --check, and
  mypy pass.
- `create_app().openapi()["info"]` returns `{'title': 'Storage Service', 'version': '0.2.0'}`.
- `git merge-tree` of `dev` into `main`: clean, two files changed.
- Real-provider check: runs on the merged `main` commit before tagging (step 2
  above). The result goes in the release notes.

## Status
- What works: the version is 0.2.0 on `dev`; merging this makes `main` match.
- What remains: provider tests on `main`, re-tag, GitHub release.
- Who owns the next steps: Faizal (release manager, #104).
- Blocked on: review of this PR.

## AI assistance
Claude Code checked the merge and drafted this description. I reviewed every line
and can explain it.

## Checklist
- [x] Linked to an issue, one purpose
- [x] ruff check, ruff format --check, mypy, and pytest pass locally; CI is green
- [x] Tests cover the new behavior; a bug fix starts with a failing test
- [x] docs/API.md, TESTING.md, and README updated where behavior or setup changed
- [x] No .env, keys, or other secrets committed
- [ ] I reviewed my own diff
