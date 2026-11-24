"""Session and sign-in queries. Raw session and state tokens stay out of the database."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from meeting_prep.db.tables.identity import SessionRow, SignInRow, UserRow

SESSION_TTL = timedelta(hours=8)
SIGN_IN_TTL = timedelta(minutes=10)


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class User:
    id: str
    email: str


@dataclass(frozen=True)
class SignIn:
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)


class IdentityStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def start_sign_in(self, now: datetime) -> SignIn:
        challenge = SignIn(token_urlsafe(32), token_urlsafe(32), token_urlsafe(32))
        with Session(self.engine) as db, db.begin():
            db.execute(delete(SignInRow).where(SignInRow.expires_at <= now))
            db.add(
                SignInRow(
                    digest=_digest(challenge.state),
                    nonce=challenge.nonce,
                    verifier=challenge.verifier,
                    expires_at=now + SIGN_IN_TTL,
                )
            )
        return challenge

    def consume_sign_in(self, state: str, now: datetime) -> SignIn | None:
        with Session(self.engine) as db, db.begin():
            row = db.execute(
                delete(SignInRow)
                .where(SignInRow.digest == _digest(state), SignInRow.expires_at > now)
                .returning(SignInRow.nonce, SignInRow.verifier)
            ).one_or_none()
            return None if row is None else SignIn(state, row.nonce, row.verifier)

    def issue(self, subject: str, email: str, now: datetime) -> str:
        token = token_urlsafe(32)
        with Session(self.engine) as db, db.begin():
            row = db.scalar(select(UserRow).where(UserRow.google_subject == subject))
            if row is None:
                try:
                    with db.begin_nested():
                        row = UserRow(id=uuid4().hex, google_subject=subject, email=email)
                        db.add(row)
                        db.flush()
                except IntegrityError:
                    row = db.scalar(select(UserRow).where(UserRow.google_subject == subject))
                    if row is None:
                        raise
            row.email = email
            db.execute(delete(SessionRow).where(SessionRow.expires_at <= now))
            db.add(SessionRow(digest=_digest(token), user_id=row.id, expires_at=now + SESSION_TTL))
        return token

    def session_user(self, token: str, now: datetime) -> User | None:
        with Session(self.engine) as db:
            row = db.scalar(
                select(UserRow)
                .join(SessionRow, SessionRow.user_id == UserRow.id)
                .where(SessionRow.digest == _digest(token), SessionRow.expires_at > now)
            )
            return None if row is None else User(row.id, row.email)

    def revoke(self, token: str) -> None:
        with Session(self.engine) as db, db.begin():
            db.execute(delete(SessionRow).where(SessionRow.digest == _digest(token)))
