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
API_BASE_URL=http://127.0.0.1:8000 uv run uvicorn --factory meeting_interface.app:app_from_env --port 8080
```

Open http://127.0.0.1:8080. With `FAKE_API=1`, the project name picks the
outcome, so each case can be seen by hand:

| Project name contains | What happens |
|---|---|
| anything else | every step succeeds |
| `fail` | the calendar step fails; later steps are not run |
| `unsure` | saving the agenda timed out and may have happened |
| `down` | the API service cannot be reached |

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `API_BASE_URL` | `http://127.0.0.1:8000` | Where the API service runs |
| `API_TIMEOUT_SECONDS` | `60` | How long to wait for one API call |
| `FAKE_API` | unset | `1` uses the built-in fake instead of the API |

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

CI runs the same checks in `.github/workflows/interface.yml`.

## What the API must return

The interface displays what the API returns and decides nothing itself.

* `POST /v1/review-meetings` with `{"project", "meeting_date", "title"}` returns
  `{"run_id", "status", "steps": [{"step", "status", "detail", "link"}]}`.
* An error returns `{"error": {"code", "message", "step", "steps"}}`. `step` names the
  failed step, and `steps` lists the outcome of each step that ran.
* A step status is `succeeded`, `failed`, `uncertain`, `skipped`, `pending` or
  `running`. Any other value is shown as uncertain, never as done.
* The page says the meeting is ready only when the run's `status` is `succeeded`.

These shapes are a draft until the API service publishes its OpenAPI document.
`src/meeting_interface/models.py` and `api_client.py` are the only places to
change when it does.

## Layout

```
src/meeting_interface/
  app.py         Routes and security headers; create_app(api) takes any ApiClient
  api_client.py  ApiClient protocol and HttpApiClient; every failure becomes ApiError
  models.py      What the API returns: RunResult, StepOutcome, StepStatus
  messages.py    Step names and the next-step text for each error code
  fake_api.py    Scripted API for tests and FAKE_API=1
  config.py      Environment settings
  templates/     index.html (form), partials/run.html (step list), base.html
  static/        htmx.min.js (vendored), app.css
tests/           One file per behavior: pages, outcomes, errors, safety, boundary, API client
```
