"""The signed-in person, from the session cookie the API sets after Google sign-in.

The interface and the API share one origin, so the browser sends the API's
cookie here too. A middleware asks the API whom it belongs to, once per request,
and pages read ``request.state.user``. Sign-out revokes the session on the API
and clears the cookie in the browser.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from meeting_interface.auth_client import AuthClient


@dataclass(frozen=True)
class WebSettings:
    # The API's cookie name. Over HTTPS it is __Host- prefixed, so it stays on this host.
    session_cookie: str = "__Host-meeting_session"
    # The origin the browser uses; sign-out refuses a POST from any other origin.
    public_origin: str | None = None
    sign_in_url: str = "/v1/auth/sign-in"


def session_token(request: Request) -> str | None:
    token = getattr(request.state, "token", None)
    return token if isinstance(token, str) else None


def add_session(app: FastAPI, auth: AuthClient, web: WebSettings) -> None:
    @app.middleware("http")
    async def who_is_signed_in(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.user = None
        request.state.token = None
        token = request.cookies.get(web.session_cookie, "")
        if token and not request.url.path.startswith("/static/"):
            user = auth.session(token)
            if user is not None:
                request.state.user, request.state.token = user, token
        return await call_next(request)

    @app.post("/sign-out", response_model=None)
    def sign_out(request: Request) -> Response:
        # A cross-site form could otherwise sign the person out.
        if web.public_origin is None or request.headers.get("origin") != web.public_origin:
            return HTMLResponse("Sign-out must come from this site.", status_code=403)
        token = session_token(request)
        if token is not None:
            auth.sign_out(token)
        response = RedirectResponse("/", status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.delete_cookie(
            web.session_cookie,
            path="/",
            secure=web.session_cookie.startswith("__Host-"),
            httponly=True,
            samesite="lax",
        )
        return response
