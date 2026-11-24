# Meeting prep product

Team 6's HW3 product: a meeting prep agent for student project leads, built on
three shared contracts (document storage, issue tracker, calendar).

This directory is its own uv project, separate from the storage service at the
repository root: Python 3.14 (Team 5's calendar package needs it), its own
`uv.lock`, and its own CI workflow (`.github/workflows/product.yml`). It
installs the storage service from this same commit, by path.

## Set up and check

```bash
cd product
uv sync                                  # install exactly what uv.lock says
uv run pytest                            # fast tests: fakes and SQLite, no network
uv run ruff check --fix . && uv run ruff format .
uv run mypy                              # strict on src/
```

CI also runs the Postgres migration tests (see Tests).

## Code map

| Path | What it does | Owner |
|---|---|---|
| `src/meeting_prep/config.py` | Reads the shared settings once at startup. `ConfigError` names a bad variable, never its value | Faizal |
| `src/meeting_prep/factories.py` | The implementation registry: builds the storage, tracker and calendar that `*_PROVIDER` name. The only module that imports an implementation package | Faizal |
| `src/meeting_prep/fakes/` | In-memory storage, tracker and calendar that follow their contracts, record calls and fail on request | Faizal |
| `src/meeting_prep/db/` | Database engine, the table base, Alembic migrations. The only package that imports SQLAlchemy | Faizal (setup); each table's owner |
| `src/meeting_prep/orchestrator.py` | `POST /v1/review-meetings` without the web: step 0 validation, claim, the lease and the 20 s guard, the steps in order, resume, and the response built from the run record. Raises `ReviewMeetingError` with the operation's codes | Vikram |
| `src/meeting_prep/run_record.py` | Pure: the request's run ID, the run record's JSON (design §1.6), the step states, and the lease and resume rules | Vikram |
| `src/meeting_prep/agenda.py` | Pure: the agenda's path and Markdown bytes. The same inputs always give the same bytes | Vikram |
| `src/meeting_prep/adapters/base.py` | `StepError` and the storage, tracker and calendar protocols the orchestrator calls. The adapters implement them | Vikram (interface); Darsh (adapters) |
| `scripts/resolve_run.py` | Records an operator's answer for a run stopped at `outcome_unknown`: `--event-id <id>` or `--no-event` | Vikram |
| `tests/test_import_boundary.py` | Who may import what. Read it before adding a package | |

Packages the import rules already expect:

- `adapters/`: one adapter per contract, the only code that sees a contract's
  types and exceptions
- `orchestrator.py`: runs the workflow's fixed steps through the adapters
- `run_record.py` and `agenda.py`: the run record's shape and rules, and the
  agenda document
- `api/`: the API service
- `agent/`: the agent service, which may not import the registry, adapters,
  orchestrator or fakes

If you choose a different name, change the rules in the same pull request.

## Choosing implementations

Startup reads the settings, then builds each vertical once:

```python
from meeting_prep.config import load_settings
from meeting_prep.factories import build_implementations

implementations = build_implementations(load_settings())
```

`implementations.storage` is a `cloud_storage_api.DocumentStorage`,
`implementations.tracker` an `issue_tracker_contract.IssueProvider`, and
`implementations.calendar` a `calendar_contract.CalendarService`.

| Variable | Names | The real one reads |
|---|---|---|
| `STORAGE_PROVIDER` | `team6-s3`, `fake`, `fake-failing` | `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| `TRACKER_PROVIDER` | `team4-trello`, `fake`, `fake-failing` | `TRELLO_API_KEY`, `TRELLO_TOKEN`, `TRELLO_LIST_ID` |
| `CALENDAR_PROVIDER` | `team5-google`, `fake`, `fake-failing` | `CALENDAR_TOKEN_FILE` |

`.env.example` explains each one. An unknown name, a missing setting, or an
implementation that fails to build stops startup with a message that names the
variable. Nothing falls back to another implementation or to a fake.

`build_implementations` also sets Python's default socket timeout to 30 seconds,
because Team 5's Calendar call has none of its own.

Partner packages are pinned to release tags in `pyproject.toml`: Team 4's Trello
provider (`team-4-issue-tracker-trello-v1.0.0`) and Team 5's Google Calendar
(`team5-calendar-v0.1.0`). Adding an implementation means a pinned dependency
(`uv add`, commit `uv.lock`) and a builder in `factories.py`.

## Fakes

Each fake keeps its data in a public dict (`files`, `issues`, `events`), records
every call in `calls`, and takes planned failures through `failures`:

```python
from calendar_contract import CalendarError, ErrorCode
from meeting_prep.fakes import FakeCalendar

calendar = FakeCalendar()
timeout = CalendarError(ErrorCode.PROVIDER_ERROR, "timed out", retryable=False)

# The next create is refused: nothing is written.
calendar.failures.fail_next("create", timeout)
# Lost response: the next create writes the event, then raises.
calendar.failures.fail_next("create", timeout, applied=True)
# Every call raises, until fail_always(None).
calendar.failures.fail_always(timeout)

calendar.operations_called()  # ["create", ...]
```

The calendar fake passes the calendar contract's conformance suite
(`tests/test_fake_calendar.py`). The storage fake follows the storage
service's path rules.

## Database

`DATABASE_URL` is `sqlite:///dev.sqlite3` locally and the Neon connection string
when deployed (`postgresql://...` and `postgres://...` both work; the driver is
psycopg 3). Create one engine per process with
`meeting_prep.db.create_engine_for(url)`.

To add a table:

1. Define it on `meeting_prep.db.Base` in a module of your own under
   `src/meeting_prep/db/tables/` (for example `conversations.py`). Put the
   queries for it in `meeting_prep/db/` too.
2. Bring a local database to the latest migration, then generate the next one.
   Use the next free number as the revision ID:

   ```bash
   export DATABASE_URL=sqlite:///dev.sqlite3
   uv run python -m meeting_prep.db upgrade
   uv run alembic revision --autogenerate -m "add conversations" --rev-id 0002
   ```

3. Read the generated file in `src/meeting_prep/db/migrations/versions/` and fix
   what autogenerate cannot know, such as renames and data changes.
4. Run `uv run pytest`. `test_the_migrated_schema_matches_the_tables_in_code`
   fails if the tables in code and the migrations disagree.

Two pull requests that each add a migration after the same parent leave two
heads, and `test_there_is_exactly_one_head` fails. The second one to merge
renumbers its revision and points its `down_revision` at the first.

Migrations must run on both SQLite and Postgres. Autogenerate writes batch
operations, which handle SQLite's limited `ALTER TABLE`. A deploy runs
`python -m meeting_prep.db upgrade` before it starts the new release. On Neon,
run it with the direct connection string, not the pooled one.

## Tests

| Command | What runs |
|---|---|
| `uv run pytest` | Fast suite: fakes, registry, import rules, migrations on SQLite. No network, no credentials |
| `TEST_DATABASE_URL=... uv run pytest -m postgres` | The migration tests on Postgres. Each test creates its own schema and drops it |
| `uv run --env-file .env pytest -m provider` | Tests against the real providers (none yet) |

A disposable Postgres for the second command:

```bash
podman run -d --rm --name meeting-prep-pg -e POSTGRES_PASSWORD=postgres \
  -p 127.0.0.1:55432:5432 docker.io/library/postgres:17
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/postgres uv run pytest -m postgres
podman stop meeting-prep-pg
```

(`docker` takes the same arguments.)
