"""Google sign-in and verification of short-lived product sessions."""

import base64
import hmac
import re
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from typing import Protocol
from urllib.parse import urlencode, urlsplit

import httpx2
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from google.auth import exceptions as google_errors
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.id_token import verify_oauth2_token

from meeting_prep.config import ConfigError
from meeting_prep.db.identity_store import SESSION_TTL, SIGN_IN_TTL, IdentityStore, SignIn, User

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class AuthError(Exception):
    def __init__(self, code: str = "unauthorized", status: int = 401) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Principal:
    user: User
    token: str = field(repr=False)


agent_principal: ContextVar[Principal | None] = ContextVar("agent_principal", default=None)


def validate_origin(origin: str, variable: str) -> str:
    try:
        parsed = urlsplit(origin)
        if (
            parsed.hostname
            and not parsed.username
            and not parsed.password
            and origin == f"{parsed.scheme}://{parsed.netloc}"
            and (parsed.port is None or 0 < parsed.port < 65536)
            and (
                parsed.scheme == "https"
                or (
                    parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                )
            )
        ):
            return origin
    except ValueError:
        pass
    raise ConfigError(f"{variable} must be an HTTPS origin or an HTTP loopback origin")


class IdentityProvider(Protocol):
    def authorize_url(self, challenge: SignIn) -> str: ...

    def identity(self, code: str, challenge: SignIn) -> tuple[str, str]: ...


class GoogleIdentity:
    def __init__(self, client_id: str, client_secret: str, callback: str) -> None:
        self.client_id, self._client_secret, self.callback = client_id, client_secret, callback

    def authorize_url(self, challenge: SignIn) -> str:
        digest = sha256(challenge.verifier.encode()).digest()
        params = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.callback,
                "response_type": "code",
                "scope": "openid email",
                "state": challenge.state,
                "nonce": challenge.nonce,
                "code_challenge": base64.urlsafe_b64encode(digest).decode().rstrip("="),
                "code_challenge_method": "S256",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    def identity(self, code: str, challenge: SignIn) -> tuple[str, str]:
        try:
            response = httpx2.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self.callback,
                    "code_verifier": challenge.verifier,
                    "code": code,
                },
                timeout=10,
            )
            response.raise_for_status()
            tokens = response.json()
            raw = tokens.get("id_token") if isinstance(tokens, dict) else None
            if not isinstance(raw, str):
                raise AuthError()
            request = partial(GoogleRequest(), timeout=10)
            claims = verify_oauth2_token(  # type: ignore[no-untyped-call]
                raw, request, audience=self.client_id
            )
        except ValueError, google_errors.GoogleAuthError, httpx2.HTTPError:
            raise AuthError() from None
        nonce, subject, email = claims.get("nonce"), claims.get("sub"), claims.get("email")
        if (
            not isinstance(nonce, str)
            or not hmac.compare_digest(nonce.encode(), challenge.nonce.encode())
            or not isinstance(subject, str)
            or not 1 <= len(subject) <= 255
            or not isinstance(email, str)
            or not 1 <= len(email) <= 320
            or claims.get("email_verified") is not True
        ):
            raise AuthError()
        return subject, email


class SessionAuth:
    def __init__(
        self, store: IdentityStore, origin: str, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.store = store
        self.origin = validate_origin(origin, "PUBLIC_ORIGIN")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.secure = self.origin.startswith("https://")
        prefix = "__Host-" if self.secure else ""
        self.session_cookie = prefix + "meeting_session"
        self.state_cookie = prefix + "meeting_sign_in"

    def require(self, request: Request) -> Principal:
        header = request.headers.get("authorization")
        if header is not None:
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer":
                raise AuthError()
        else:
            token = request.cookies.get(self.session_cookie, "")
            if token and request.method not in {"GET", "HEAD", "OPTIONS"}:
                if request.headers.get("origin") != self.origin:
                    raise AuthError("origin_mismatch", 403)
        if not _TOKEN.fullmatch(token):
            raise AuthError()
        user = self.store.session_user(token, self.clock())
        if user is None:
            raise AuthError()
        return Principal(user, token)

    def set_cookie(self, response: Response, name: str, token: str, seconds: int) -> None:
        response.set_cookie(
            name,
            token,
            max_age=seconds,
            secure=self.secure,
            httponly=True,
            samesite="lax",
            path="/",
        )

    def clear_cookie(self, response: Response, name: str) -> None:
        self.set_cookie(response, name, "", 0)

    def router(self, provider: IdentityProvider) -> APIRouter:
        router = APIRouter(prefix="/v1/auth", tags=["sign-in"])

        @router.get("/sign-in")
        def sign_in() -> RedirectResponse:
            state = self.store.start_sign_in(self.clock())
            response = RedirectResponse(provider.authorize_url(state), status_code=303)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            self.set_cookie(
                response, self.state_cookie, state.state, int(SIGN_IN_TTL.total_seconds())
            )
            return response

        @router.get("/callback")
        def callback(request: Request, state: str = "", code: str = "") -> Response:
            cookie = request.cookies.get(self.state_cookie, "")
            if not _TOKEN.fullmatch(state) or not hmac.compare_digest(
                state.encode(), cookie.encode()
            ):
                raise AuthError("invalid_sign_in", 400)
            challenge = self.store.consume_sign_in(state, self.clock())
            if challenge is None or not code or len(code) > 2048:
                raise AuthError("invalid_sign_in", 400)
            try:
                subject, email = provider.identity(code, challenge)
            except AuthError:
                raise AuthError("invalid_sign_in", 400) from None
            previous = request.cookies.get(self.session_cookie, "")
            if _TOKEN.fullmatch(previous):
                self.store.revoke(previous)
            token = self.store.issue(subject, email, self.clock())
            response = RedirectResponse(self.origin + "/", status_code=303)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            self.clear_cookie(response, self.state_cookie)
            self.set_cookie(response, self.session_cookie, token, int(SESSION_TTL.total_seconds()))
            return response

        @router.get("/session")
        def get_session(request: Request) -> JSONResponse:
            user = self.require(request).user
            return JSONResponse(
                {"id": user.id, "email": user.email}, headers={"Cache-Control": "no-store"}
            )

        @router.post("/sign-out", status_code=204)
        def sign_out(request: Request) -> Response:
            principal = self.require(request)
            self.store.revoke(principal.token)
            response = Response(status_code=204, headers={"Cache-Control": "no-store"})
            self.clear_cookie(response, self.session_cookie)
            return response

        return router
