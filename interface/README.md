# Meeting prep interface

The web interface for the meeting prep product. A person runs the review-meeting
scenario by hand and sees each step's outcome. It calls only our API service. It
never calls Trello, Google Calendar, cloud storage, another team's service, or the
database directly. `tests/test_boundary.py` fails if any module imports one of
their libraries.

Built with FastAPI and server-rendered Jinja templates. [htmx](https://htmx.org)
2.0.4 is vendored in `static/` so the page loads no third-party scripts.

## Run it

```bash
cd interface
uv sync

# Without the backend: a built-in fake API answers.
FAKE_API=1 uv run uvicorn --factory meeting_interface.app:app_from_env --port 8080 --reload

# Against a running API service.
PRODUCT_API_KEY=... API_BASE_URL=http://127.0.0.1:8000 uv run uvicorn --factory meeting_interface.app:app_from_env --port 8080
```

Open http://127.0.0.1:8080. With `FAKE_API=1`, a word in the meeting title picks
the outcome, so each case can be seen by hand:

| Title contains | What happens |
|---|---|
| anything else | every step succeeds |
| `again` | the run was already completed (replayed) |
| `fail` | the calendar is unreachable; Try again resumes the run |
| `unsure` | the calendar may have created the event; no Try again |
| `busy` | another request holds the run; wait about 87 seconds |
| `stuck` | `outcome_unknown`: a team member must check the calendar |
| `down` | the API service cannot be reached |

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `API_BASE_URL` | `http://127.0.0.1:8000` | Where the API service runs |
| `PRODUCT_API_KEY` | none, required unless `FAKE_API=1` | The API's key, sent as a Bearer token. It stays on the server and never reaches a page |
| `API_TIMEOUT_SECONDS` | `180` | How long to wait for one run: it makes several provider calls in a row |
| `FAKE_API` | unset | `1` uses the built-in fake instead of the API |

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

CI runs the same checks in `.github/workflows/interface.yml`.

## The API it calls

`POST /v1/review-meetings`, as in design §1.4. The interface displays what the
API returns and decides nothing itself.

* The form becomes `{"title", "start", "end", "agenda"}`. The date, times and time
  zone become RFC 3339 times with that zone's offset on that day, and the agenda
  is one item per non-blank line. The API checks every rule.
* A run is `{"status", "run_id", "replayed", "steps": [{"name", "status"}], "issue",
  "event", "agenda", "record"}`. The page says the meeting is ready only when
  `status` is `completed`. A step status other than `ok`, `failed`, `unknown` or
  `pending` is shown as Not sure, never as Done.
* An error is `{"error": {"code", "message", "step", "retryable",
  "may_have_applied"}, "run"}`. Try again appears only when `retryable` is true (or
  for `run_in_progress`, after `Retry-After`), and sends the same form again, which
  resumes the same run.

`src/meeting_interface/models.py` and `api_client.py` are the only places to change
if the shapes change.

## Layout

```
src/meeting_interface/
  app.py         Routes and security headers; create_app(api) takes any ApiClient
  api_client.py  ApiClient protocol and HttpApiClient; every failure becomes ApiError
  models.py      What the API returns: RunResult, Run, Step, StepStatus
  form.py        Form fields to the API body: RFC 3339 times with the zone's offset
  messages.py    Step names and the next-step text for each error code
  fake_api.py    Scripted API for tests and FAKE_API=1
  config.py      Environment settings
  templates/     index.html (form), partials/run.html (step list), base.html
  static/        htmx.min.js (vendored), app.css
tests/           One file per behavior: pages, form, outcomes, errors, safety, boundary, API client
```
