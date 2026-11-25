"""Renewing a user's Google access token with the refresh token they granted us.

Google access tokens last about an hour. The resolver renews one shortly before it
expires, through ``ConnectionStore.refresh``, which saves the replacement before
anything uses it. Errors never carry Google's response body, which can echo a
token.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx2

from meeting_prep.db.connection_store import Connection, ConnectionRevoked, Tokens

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# Google's answers that mean the grant itself is gone: revoked by the user, expired
# (refresh tokens in testing mode last 7 days), or issued to another client.
_REVOKED = {"invalid_grant", "unauthorized_client"}


class ProviderTokenError(Exception):
    """The provider could not renew the token now. The stored tokens are unchanged."""


@dataclass(frozen=True)
class GoogleRefresher:
    """Renews tokens issued to one Google OAuth client, the one users connect through."""

    client_id: str
    client_secret: str = field(repr=False)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def __call__(self, connection: Connection) -> Tokens:
        if connection.refresh_token is None:
            raise ConnectionRevoked()
        try:
            response = httpx2.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": connection.refresh_token,
                },
                timeout=10,
            )
            body = response.json()
        except httpx2.HTTPError, ValueError:
            raise ProviderTokenError() from None
        if not isinstance(body, dict):
            raise ProviderTokenError()
        if response.status_code in {400, 401} and body.get("error") in _REVOKED:
            raise ConnectionRevoked()
        access_token, lifetime = body.get("access_token"), body.get("expires_in")
        if (
            response.status_code != 200
            or not isinstance(access_token, str)
            or not access_token
            or not isinstance(lifetime, int)
            or isinstance(lifetime, bool)
        ):
            raise ProviderTokenError()
        # Google sends a new refresh token only when it rotates the old one.
        renewed = body.get("refresh_token")
        return Tokens(
            access_token=access_token,
            expires_at=self.clock() + timedelta(seconds=lifetime),
            refresh_token=renewed if isinstance(renewed, str) and renewed else None,
        )
