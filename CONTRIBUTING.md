# Development workflow

How Team 6 plans, reviews, merges, and releases work on this project. For setup,
see `README.md`. For the code map, architecture rules, and check commands, see
`AGENTS.md`.

## How the first version was built

The team met twice to choose the vertical and the features to build, and to
plan the code structure, hosting, and testing. Once the plan was roughly
sketched out, the work was split up:

* **Darsh Shani, Vikram Markali, and Prateek Saxena** compared GCP, Oracle Cloud,
  and AWS to find the easiest option to work with, and set up the Oracle Cloud
  (OCI) accounts the project uses.
* **Debasmith Mandal** built the base setup: the service, the storage backends,
  the tests, and CI.
* **Faizal Rahman** reviewed that work and added the finishing touches needed to
  meet the course requirements.
* The rest of the team reviewed the code.

From here on, all work follows the process below.

## Task ownership

* Every piece of work is a GitHub issue, opened with the bug report or feature
  request template.
* Each issue has exactly one owner: its assignee. To take an issue, assign
  yourself. Ask the owner before working on an issue someone else has taken.
* The owner is responsible for the issue until it is closed. That includes
  writing the code and tests, answering review comments, and keeping CI green.
* If you cannot finish an issue, say so in a comment and unassign yourself so
  someone else can pick it up.
* Larger decisions, such as a new provider or a change to the HTTP API, are
  agreed in the issue or at a team meeting before anyone writes code.

## Branches and pull requests

* `main` always passes CI, and releases are made from it. Nobody pushes to
  `main` directly. Every change goes through a pull request.
* Work on a short-lived branch created from the latest `main`. Name it after the
  issue, for example `12-garage-backend`.
* Each pull request has one purpose, links its issue with `Closes #12`, and
  completes the pull request template.
* If any of the code was written with an AI assistant, say so in the pull
  request. The author must be able to explain every line.

## Review and merge requirements

A pull request can be merged only when all of these are true:

1. At least one teammate other than the author has approved it.
2. Every CI check passes on the pull request's latest commit: lint, format,
   type check, and tests.
3. Every review comment is resolved.
4. The branch is up to date with `main`. If it is behind, update it and let CI
   run again.

Reviewers check that the change does what the issue asks, that new behavior has
tests, that the architecture rules in `AGENTS.md` still hold, that the docs are
updated, and that no secrets were added.

When a pull request is approved and green, its author merges it with **Squash
and merge**, so each pull request becomes a single commit on `main` that is
easy to revert. Then the author deletes the branch.

Failures are reported honestly. We never skip, disable, or loosen a test or a
check just to get a green result. If a check fails for a reason that has nothing
to do with the pull request, open an issue for it and mention that issue in the
pull request.

The repository owner keeps a branch protection rule on `main` (Settings >
Branches) that enforces these rules. It requires a pull request with one
approval, requires the `checks` status check to pass, and requires branches to
be up to date before merging.

## Versioning

We use [semantic versioning](https://semver.org/): `MAJOR.MINOR.PATCH`. The
version is set in one place, `pyproject.toml`. The running API reports it in
`/docs` and `/openapi.json`.

While the version is below 1.0.0:

* Bump **MINOR** (0.1.0 to 0.2.0) for a new feature or for any breaking change
  to the HTTP API or the configuration. Label breaking changes `breaking change`
  and describe them in the release notes.
* Bump **PATCH** (0.1.0 to 0.1.1) for bug fixes that do not change the API.

When the API is stable, we release 1.0.0. After that, a breaking change bumps
MAJOR.

Bump the version with `uv version --bump minor` or `uv version --bump patch`.
This updates `pyproject.toml` and `uv.lock` together. Every release is a git
tag named `vX.Y.Z` on a commit in `main`.

## Releases

Each release has one release manager, who is the assignee of the release
issue. The release manager:

1. Opens an issue named "Release vX.Y.Z", assigns themselves, and lists the
   pull requests going into the release.
2. Opens a pull request that bumps the version. It goes through normal review.
3. After it merges, confirms that CI passed on that exact commit on `main`.
4. Runs the full test suite against the real provider:
   `uv run --env-file .env pytest`. CI has no provider credentials, so this is
   the only check against real storage. Nothing should be skipped. Note the
   result for the release notes.
5. Tags that commit and pushes the tag. CI runs again on the tag.

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

6. Creates a GitHub release from the tag (Releases > Draft a new release, then
   **Generate release notes**). Adds any breaking changes, new known
   limitations, and the result of the real-provider tests.
7. Tells the team and closes the release issue.

We submit graded work from a release tag whose CI checks have all passed.

## Fixing a defective release

A release is defective if people should stop running it. Examples include lost
or corrupted files, the wrong file being returned, a crash at startup, or a
security problem. The release manager for that release coordinates the
recovery.

1. **Report it.** Open a bug issue that names the bad version, and assign an
   owner. Add a warning at the top of that version's GitHub release notes that
   says what is wrong and which version to use instead.
2. **Go back to the last good version.** Anyone running the service checks out
   the previous tag, syncs, and restarts:

   ```bash
   git checkout vX.Y.Z    # the last good tag
   uv sync --locked
   ```

   The service keeps no data of its own, because files and their metadata live
   in the bucket. Switching versions therefore needs no data migration. If the
   bad release wrote wrong files to the bucket, find them by key or
   modification time and delete or re-upload them.
3. **Fix it on `main`.** Either revert the pull request that caused the problem
   (`git revert <commit>` in a new pull request, which is a single commit
   because we squash-merge), or write a fix. Either way, start with a test that
   fails because of the bug.
4. **Release the fix** as a new PATCH version, following the steps above. Never
   delete, move, or reuse a published tag. The bad version stays in the history
   with its warning.
5. **Write it up.** In the bug issue, explain what broke, why CI did not catch
   it, and which test catches it now.
