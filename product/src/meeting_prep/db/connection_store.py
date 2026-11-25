"""Provider connections and the one-use challenges that create them.

Tokens are sealed with ``TokenCipher`` just before they are written and opened
just after they are read, so nothing outside this module sees ciphertext and
nothing here writes a plaintext token. Every query is scoped by a user ID the
caller has already verified from a session.
"""

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Literal, cast

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from meeting_prep.db.tables.connections import ConnectionChallengeRow, ProviderConnectionRow
from meeting_prep.token_cipher import TokenCipher, TokenUnreadable

type Provider = Literal["trello", "google_calendar"]
type Status = Literal["connected", "needs_attention"]

PROVIDERS: tuple[Provider, ...] = ("trello", "google_calendar")
CHALLENGE_TTL = timedelta(minutes=10)


class ConnectionRevoked(Exception):
    """The provider no longer accepts the grant. The user has to connect again."""


@dataclass(frozen=True)
class Tokens:
    """Tokens from a provider. ``refresh_token`` None on a refresh keeps the stored one."""

    access_token: str = field(repr=False)
    expires_at: datetime | None
    refresh_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ConnectionSummary:
    """What the user may see about a connection. Holds no token."""

    provider: Provider
    account: str
    scopes: tuple[str, ...]
    status: Status
    settings: Mapping[str, str]
    connected_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class Connection:
    """A connection with its tokens. Only the API's provider resolver should hold one.

    Deliberately not a ConnectionSummary, so the type checker stops a Connection
    from being sent where a summary, which holds no token, is expected.
    """

    provider: Provider
    account: str
    scopes: tuple[str, ...]
    status: Status
    settings: Mapping[str, str]
    connected_at: datetime
    expires_at: datetime | None
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)

    def expired(self, now: datetime, margin: timedelta = timedelta(0)) -> bool:
        return self.expires_at is not None and self.expires_at <= now + margin


class ConnectionStore:
    def __init__(self, engine: Engine, cipher: TokenCipher) -> None:
        self.engine = engine
        self._cipher = cipher
        self._refresh_locks: dict[tuple[str, str], threading.Lock] = {}
        self._refresh_locks_guard = threading.Lock()

    # Challenges: the state sent through the provider, bound to who started it.

    def start_challenge(
        self, user_id: str, session_token: str, provider: Provider, secret: str, now: datetime
    ) -> str:
        """Record a started authorization and return its state. ``secret`` is sealed."""
        state = token_urlsafe(32)
        digest = _digest(state)
        with Session(self.engine) as db, db.begin():
            db.execute(
                delete(ConnectionChallengeRow).where(ConnectionChallengeRow.expires_at <= now)
            )
            db.add(
                ConnectionChallengeRow(
                    digest=digest,
                    user_id=user_id,
                    session_digest=_digest(session_token),
                    provider=provider,
                    secret=self._cipher.seal(secret, context=f"challenge:{digest}"),
                    expires_at=now + CHALLENGE_TTL,
                )
            )
        return state

    def finish_challenge(
        self, state: str, user_id: str, session_token: str, provider: Provider, now: datetime
    ) -> str | None:
        """Use a challenge once and return its secret.

        None unless the same user, in the same session, finishes the same provider's
        flow before the challenge expires. A mismatch leaves the challenge in place,
        so someone else's attempt cannot use up the real user's.
        """
        digest = _digest(state)
        with Session(self.engine) as db, db.begin():
            sealed = db.execute(
                delete(ConnectionChallengeRow)
                .where(
                    ConnectionChallengeRow.digest == digest,
                    ConnectionChallengeRow.user_id == user_id,
                    ConnectionChallengeRow.session_digest == _digest(session_token),
                    ConnectionChallengeRow.provider == provider,
                    ConnectionChallengeRow.expires_at > now,
                )
                .returning(ConnectionChallengeRow.secret)
            ).scalar_one_or_none()
        if sealed is None:
            return None
        return self._cipher.open(sealed, context=f"challenge:{digest}")

    # Connections.

    def save(
        self,
        user_id: str,
        provider: Provider,
        *,
        account: str,
        scopes: tuple[str, ...],
        tokens: Tokens,
        now: datetime,
        settings: Mapping[str, str] | None = None,
    ) -> None:
        """Store a new or renewed connection as connected, replacing any earlier tokens."""
        with Session(self.engine) as db, db.begin():
            row = db.get(ProviderConnectionRow, (user_id, provider))
            if row is None:
                row = ProviderConnectionRow(user_id=user_id, provider=provider, connected_at=now)
                db.add(row)
            else:
                row.connected_at = now
            row.account = account
            row.scopes = " ".join(scopes)
            row.access_token = self._seal(user_id, provider, "access_token", tokens.access_token)
            row.refresh_token = (
                None
                if tokens.refresh_token is None
                else self._seal(user_id, provider, "refresh_token", tokens.refresh_token)
            )
            row.expires_at = tokens.expires_at
            row.status = "connected"
            row.settings = dict(settings or {})
            row.updated_at = now

    def get(self, user_id: str, provider: Provider) -> Connection | None:
        """The connection with its tokens. Raises TokenUnreadable if they cannot be opened."""
        with Session(self.engine) as db:
            row = db.get(ProviderConnectionRow, (user_id, provider))
            return None if row is None else self._connection(row)

    def summaries(self, user_id: str) -> list[ConnectionSummary]:
        with Session(self.engine) as db:
            rows = db.scalars(
                select(ProviderConnectionRow)
                .where(ProviderConnectionRow.user_id == user_id)
                .order_by(ProviderConnectionRow.provider)
            )
            return [_summary(row) for row in rows]

    def update_settings(
        self, user_id: str, provider: Provider, settings: Mapping[str, str], now: datetime
    ) -> bool:
        """Replace a connection's settings. False if the user has no such connection."""
        with Session(self.engine) as db, db.begin():
            row = db.get(ProviderConnectionRow, (user_id, provider))
            if row is None:
                return False
            row.settings = dict(settings)
            row.updated_at = now
            return True

    def mark_needs_attention(self, user_id: str, provider: Provider, now: datetime) -> None:
        with Session(self.engine) as db, db.begin():
            row = db.get(ProviderConnectionRow, (user_id, provider))
            if row is not None:
                row.status = "needs_attention"
                row.updated_at = now

    def remove(self, user_id: str, provider: Provider) -> Connection | None:
        """Delete a connection and return it, so the caller can revoke it at the provider.

        If its tokens cannot be opened, the row is still deleted and None is returned.
        """
        with Session(self.engine) as db, db.begin():
            row = db.get(ProviderConnectionRow, (user_id, provider))
            if row is None:
                return None
            try:
                connection: Connection | None = self._connection(row)
            except TokenUnreadable:
                connection = None
            db.delete(row)
            return connection

    def refresh(
        self,
        user_id: str,
        provider: Provider,
        now: datetime,
        renew: Callable[[Connection], Tokens],
        *,
        margin: timedelta = timedelta(minutes=5),
    ) -> Connection | None:
        """Renew the access token if it expires within ``margin``, and save the result.

        One refresh runs at a time for each connection: a waiting caller rereads the
        row and finds the token another caller just saved. ``renew`` raising
        ConnectionRevoked marks the connection as needing attention; any other error
        propagates and leaves the stored tokens unchanged.
        """
        with self._refresh_lock(user_id, provider), Session(self.engine) as db, db.begin():
            row = db.get(ProviderConnectionRow, (user_id, provider), with_for_update=True)
            if row is None:
                return None
            connection = self._connection(row)
            if connection.status != "connected" or not connection.expired(now, margin):
                return connection
            try:
                tokens = renew(connection)
            except ConnectionRevoked:
                row.status = "needs_attention"
                row.updated_at = now
                return self._connection(row)
            row.access_token = self._seal(user_id, provider, "access_token", tokens.access_token)
            if tokens.refresh_token is not None:
                row.refresh_token = self._seal(
                    user_id, provider, "refresh_token", tokens.refresh_token
                )
            row.expires_at = tokens.expires_at
            row.updated_at = now
            return self._connection(row)

    def _refresh_lock(self, user_id: str, provider: str) -> threading.Lock:
        with self._refresh_locks_guard:
            return self._refresh_locks.setdefault((user_id, provider), threading.Lock())

    def _seal(self, user_id: str, provider: str, column: str, value: str) -> str:
        return self._cipher.seal(value, context=f"{user_id}:{provider}:{column}")

    def _open(self, user_id: str, provider: str, column: str, sealed: str) -> str:
        return self._cipher.open(sealed, context=f"{user_id}:{provider}:{column}")

    def _connection(self, row: ProviderConnectionRow) -> Connection:
        summary = _summary(row)
        return Connection(
            summary.provider,
            summary.account,
            summary.scopes,
            summary.status,
            summary.settings,
            summary.connected_at,
            summary.expires_at,
            access_token=self._open(row.user_id, row.provider, "access_token", row.access_token),
            refresh_token=(
                None
                if row.refresh_token is None
                else self._open(row.user_id, row.provider, "refresh_token", row.refresh_token)
            ),
        )


def _summary(row: ProviderConnectionRow) -> ConnectionSummary:
    return ConnectionSummary(
        provider=cast(Provider, row.provider),
        account=row.account,
        scopes=tuple(row.scopes.split()),
        status=cast(Status, row.status),
        settings={str(key): str(value) for key, value in row.settings.items()},
        connected_at=_utc(row.connected_at),
        expires_at=None if row.expires_at is None else _utc(row.expires_at),
    )


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _utc(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; every time we store is UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
