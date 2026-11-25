# Issue

**Title:** Set up product/: config, implementation registry, fakes, database migrations

**Body:**

Due Mon Nov 23 at noon, because the rest of the product builds on it.

The meeting prep product needs a home before anyone writes routes, adapters or tables. Set up
`product/` as its own uv project with:

- configuration read from environment variables at startup
- the implementation registry, which picks the storage, tracker and calendar by name, fakes
  included
- in-memory fakes of the three contracts for tests
- a database layer with migrations, so each area adds its tables through a migration

Done when:

- [ ] `uv sync --locked` passes in `product/`
- [ ] the config and import-boundary tests pass in CI
- [ ] an empty migration runs on SQLite and on Postgres

Out of scope: routes, adapters, the orchestrator, tables, the Dockerfile.

---

# Pull request

**Title:** Add the product/ project: config, implementation registry, fakes, database migrations

**Body:**

Closes #<issue number>

Sets up `product/`, the base the rest of the HW3 product builds on. There are no routes, adapters,
orchestrator or tables yet. Start with `product/README.md`.

## What's in it

- **Its own uv project** on Python 3.14, which Team 5's calendar package needs, with its own
  `uv.lock`. It installs our storage service from this same commit, by path. Partner packages
  are pinned to release tags: Team 4's Trello provider `team-4-issue-tracker-trello-v1.0.0`,
  Team 5's calendar `team5-calendar-v0.1.0`, and the three contract tags.
- **`config.py`** reads `STORAGE_PROVIDER`, `TRACKER_PROVIDER`, `CALENDAR_PROVIDER` and
  `DATABASE_URL` once at startup. A bad setting raises `ConfigError`, which names the variable
  and never its value.
- **`factories.py`** is the implementation registry. It knows `team6-s3`, `team4-trello` and
  `team5-google`, plus `fake` and `fake-failing` for each vertical.
  `build_implementations(load_settings())` returns all three.
  - It is the only module that imports an implementation package.
  - An unknown name or a failed build stops startup. Nothing falls back to a fake.
  - It sets a 30 s default socket timeout, because Team 5's calendar call has none of its own.
- **`fakes/`** holds in-memory storage, tracker and calendar. Each one records its calls and
  can fail on request in three ways:
  - refuse the next call;
  - do the write, then raise as if the response was lost;
  - fail every call.

  The calendar fake passes the calendar contract's own conformance suite.
- **`db/`** has:
  - a SQLAlchemy engine for SQLite locally and Postgres (Neon) when deployed;
  - a shared `Base` for tables;
  - Alembic migrations shipped inside the package, starting with an empty baseline `0001`;
  - `python -m meeting_prep.db upgrade` for deploys.
- **CI** is a new workflow, `.github/workflows/product.yml`. It runs `uv sync --locked`, ruff,
  the format check, strict mypy and the fast tests, then the migration tests against a
  Postgres 17 service container. The storage service's `ci.yml` is unchanged.
- **Root files:** `AGENTS.md` gets one line pointing to `product/README.md`, and `.gitignore`
  now ignores `docs/hw*`.

## If you're building on this

- **Import rules.** `tests/test_import_boundary.py` already has rules for packages that don't
  exist yet: `adapters/`, `orchestrator`, `api/` and `agent/`. For example, the agent service
  may not import the registry, adapters or fakes, and only `meeting_prep.db` may import
  SQLAlchemy. If you use a different package name, change its rule in your PR.
- **Tables.** Define yours in your own module under `src/meeting_prep/db/tables/` and add the
  next migration (`0002`, `0003`, ...). The Database section of the README has the steps.
  - One test fails if the tables in code and the migrations disagree.
  - Another fails if two PRs each add a migration after the same parent. Whichever of the two
    merges second renumbers its migration.
- **Fakes.** Use them in tests instead of mocks. The Fakes section of the README shows how to
  plan each kind of failure.

## New dependencies

- `sqlalchemy`, `alembic` and `psycopg[binary]` for the database: Postgres on Neon when
  deployed (managed, free, with point-in-time restore), SQLite locally and in tests.
- The partner packages listed above.

All of them have Python 3.14 ARM64 wheels, so they install on the OCI VM.

## Not in this PR

- **Calendar timeout vs. run lease:** a test that the 30 s timeout stays under the 120 s run
  lease, so a hung calendar call can't outlive it. It needs the lease constant, which comes with
  the orchestrator.
- **Providers per user:** Team 4's Trello provider and Team 5's calendar each read one set of
  credentials, so they can't act for more than one user yet. We're sending both teams a pull
  request that adds credential arguments. Until then the registry builds one shared instance
  of each.
- **Dockerfile and deploy:** the image should install with `uv sync --locked --no-editable`.

## How to check

```bash
cd product
uv sync --locked
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
# Postgres: the Tests section of the README has a podman command for a throwaway database
TEST_DATABASE_URL=postgresql://... uv run pytest -m postgres
```

On Python 3.14, 132 fast tests and 3 Postgres tests pass (Postgres 17 in podman). They also pass
on a clean checkout. The storage service's own checks still pass (325 tests).

To try the add-a-table steps, I generated a migration for two throwaway tables. It covered a
foreign key, a unique constraint, an index, and JSON and timestamp columns. It ran on both
databases, and I removed it before committing.

Code written with an AI assistant (AGENTS.md).
