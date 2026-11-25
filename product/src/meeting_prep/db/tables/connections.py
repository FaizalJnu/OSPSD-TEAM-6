"""Provider connections: each user's authorized access to their own provider accounts.

A connection is separate from a session. The session says who the user is; a
connection lets the API act in one of that user's provider accounts. Tokens are
stored only as ciphertext (``meeting_prep.token_cipher``), and the key lives in the
API service's environment, never in this database.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from meeting_prep.db.base import Base


class ProviderConnectionRow(Base):
    """One user's connection to one provider. Reconnecting replaces the row's tokens."""

    __tablename__ = "provider_connections"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    # The external account, shown to the user: a Google email or a Trello username.
    account: Mapped[str] = mapped_column(String(320))
    scopes: Mapped[str] = mapped_column(String(512))
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    # When the access token stops working; None if the provider gave no expiry.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    # Non-secret choices that belong to the connection, such as the Trello list.
    settings: Mapped[dict[str, Any]] = mapped_column(JSON)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConnectionChallengeRow(Base):
    """A started authorization, usable once by the same user and session, then deleted."""

    __tablename__ = "connection_challenges"

    # SHA-256 of the state sent through the provider; the state itself is never stored.
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    session_digest: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    # Ciphertext of what finishing the flow needs: a PKCE verifier, or an OAuth 1.0a
    # request token and its secret.
    secret: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
