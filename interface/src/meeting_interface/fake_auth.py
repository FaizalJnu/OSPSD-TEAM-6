"""A stand-in for the API's sign-in routes, for tests and FAKE_API=1."""

from meeting_interface.auth_client import SignedInUser


class FakeAuthClient:
    def __init__(self, users: dict[str, str] | None = None) -> None:
        self.users = dict(users or {})  # token -> email
        self.looked_up: list[str] = []
        self.revoked: list[str] = []

    def session(self, token: str) -> SignedInUser | None:
        self.looked_up.append(token)
        email = self.users.get(token)
        return None if email is None else SignedInUser(id=f"user-{email}", email=email)

    def sign_out(self, token: str) -> None:
        self.revoked.append(token)
        self.users.pop(token, None)
