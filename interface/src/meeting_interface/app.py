"""Pages for running the review-meeting scenario by hand.

Routes only collect what the person typed, call the API service, and show what
it returned. Run them with:

    uvicorn --factory meeting_interface.app:app_from_env
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from meeting_interface.agent_client import AgentClient, HttpAgentClient
from meeting_interface.api_client import ApiClient, ApiError, HttpApiClient
from meeting_interface.chat import add_chat_routes
from meeting_interface.config import load_settings
from meeting_interface.fake_agent import FakeAgentClient
from meeting_interface.fake_api import FakeApiClient
from meeting_interface.form import DEFAULT_TIME_ZONE, TIME_ZONES, FormProblem, MeetingForm
from meeting_interface.messages import error_help, status_label, step_label
from meeting_interface.models import Step, StepStatus

HERE = Path(__file__).parent

SECURITY_HEADERS = {
    # Only our own scripts and styles run; links from providers cannot load anything.
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def create_app(api: ApiClient, agent: AgentClient) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(step_label=step_label, status_label=status_label)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    add_chat_routes(app, templates, agent)

    @app.get("/", response_class=HTMLResponse)
    def start(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "index.html", {"time_zones": TIME_ZONES, "default_zone": DEFAULT_TIME_ZONE}
        )

    @app.post("/runs", response_class=HTMLResponse)
    def run(
        request: Request,
        title: Annotated[str, Form()],
        day: Annotated[str, Form()],
        start_time: Annotated[str, Form()],
        end_time: Annotated[str, Form()],
        time_zone: Annotated[str, Form()],
        agenda: Annotated[str, Form()] = "",
    ) -> HTMLResponse:
        form = MeetingForm(title, day, start_time, end_time, time_zone, agenda)
        try:
            run_request = form.to_request()
        except FormProblem as problem:
            return _render(templates, request, form_problem=str(problem))
        try:
            result = api.run_review_meeting(run_request)
        except ApiError as error:
            return _render(
                templates,
                request,
                steps=_steps_after(error),
                run=error.run,
                error=error,
                help=error_help(error.code),
            )
        return _render(
            templates, request, steps=result.run.steps, run=result.run, replayed=result.replayed
        )

    return app


def _render(templates: Jinja2Templates, request: Request, **context: object) -> HTMLResponse:
    defaults: dict[str, object] = {
        "steps": [],
        "run": None,
        "replayed": False,
        "error": None,
        "help": None,
        "form_problem": None,
    }
    return templates.TemplateResponse(request, "partials/run.html", {**defaults, **context})


def _steps_after(error: ApiError) -> list[Step]:
    """The run's steps, or just the failed step when the API sent no run."""
    if error.run is not None:
        return error.run.steps
    if error.step is not None:
        return [Step(error.step, StepStatus.FAILED)]
    return []


def app_from_env() -> FastAPI:
    settings = load_settings()
    if settings.fake_api:
        return create_app(FakeApiClient(), FakeAgentClient())
    return create_app(
        HttpApiClient.for_url(
            settings.api_base_url, settings.api_key, settings.api_timeout_seconds
        ),
        HttpAgentClient.for_url(settings.agent_base_url, settings.api_timeout_seconds),
    )
