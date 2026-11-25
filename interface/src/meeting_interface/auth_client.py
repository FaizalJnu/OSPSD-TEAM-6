"""Who is signed in, and signing out, through the API's /v1/auth routes.

The API runs Google sign-in and sets the session cookie on our shared origin. The
interface only reads that cookie and asks the API about it, sending it as a
Bearer token. It never stores, shows or logs the token.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx2 as httpx


@dataclass(frozen=True)
class SignedInUser:
    id: str
    email: str


class AuthClient(Protocol):
    def session(self, token: str) -> SignedInUser | None:
        """The session's user, or None when it is missing, expired or revoked."""
        ...

    def sign_out(self, token: str) -> None:
        """Revoke the session on the server. Already revoked is fine."""
        ...


class HttpAuthClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def for_url(cls, base_url: str, timeout_seconds: float = 10.0) -> "HttpAuthClient":
        return cls(httpx.Client(base_url=base_url, timeout=timeout_seconds))

    def session(self, token: str) -> SignedInUser | None:
        try:
            response = self._http.get("/v1/auth/session", headers=_bearer(token))
            if response.status_code != 200:
                return None
            body = response.json()
            return SignedInUser(id=str(body["id"]), email=str(body["email"]))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # If the API cannot say who this is, the page treats them as signed out.
            return None

    def sign_out(self, token: str) -> None:
        try:
            self._http.post("/v1/auth/sign-out", headers=_bearer(token))
        except httpx.HTTPError:
            # The cookie is still cleared in the browser; the session expires on its own.
            pass


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
