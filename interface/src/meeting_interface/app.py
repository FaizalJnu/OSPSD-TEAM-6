"""Pages for running the review-meeting scenario by hand.

Routes only collect what the person typed, call the API service, and show what
it returned. Run them with:

    uvicorn --factory meeting_interface.app:app_from_env
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from meeting_interface.api_client import ApiClient, ApiError, HttpApiClient
from meeting_interface.config import load_settings
from meeting_interface.fake_api import FakeApiClient
from meeting_interface.messages import error_help, status_label, step_label
from meeting_interface.models import RunRequest, StepOutcome, StepStatus

HERE = Path(__file__).parent

SECURITY_HEADERS = {
    # Only our own scripts and styles run; links from providers cannot load anything.
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def safe_link(url: str | None) -> str | None:
    """Only http and https links become clickable; anything else is dropped."""
    if url is None or urlsplit(url).scheme not in ("http", "https"):
        return None
    return url


def create_app(api: ApiClient) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(
        step_label=step_label, status_label=status_label, safe_link=safe_link
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/", response_class=HTMLResponse)
    def start(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html")

    @app.post("/runs", response_class=HTMLResponse)
    def run(
        request: Request,
        project: Annotated[str, Form()],
        meeting_date: Annotated[str, Form()],
        title: Annotated[str, Form()],
    ) -> HTMLResponse:
        run_request = RunRequest(project=project, meeting_date=meeting_date, title=title)
        try:
            result = api.run_review_meeting(run_request)
        except ApiError as error:
            return templates.TemplateResponse(
                request,
                "partials/run.html",
                {
                    "steps": _with_failed_step(error),
                    "error": error,
                    "help": error_help(error.code),
                },
            )
        return templates.TemplateResponse(
            request,
            "partials/run.html",
            {"steps": result.steps, "status": result.status, "error": None},
        )

    return app


def _with_failed_step(error: ApiError) -> list[StepOutcome]:
    """Name the failed step even when the API listed only the completed ones."""
    steps = list(error.steps)
    if error.step is not None and all(s.step != error.step for s in steps):
        steps.append(StepOutcome(error.step, StepStatus.FAILED))
    return steps


def app_from_env() -> FastAPI:
    settings = load_settings()
    if settings.fake_api:
        return create_app(FakeApiClient())
    return create_app(HttpApiClient.for_url(settings.api_base_url, settings.api_timeout_seconds))
