"""HttpAuthClient asks the API's /v1/auth routes about the session, as a Bearer token."""

import httpx2 as httpx

from meeting_interface.agent_client import HttpAgentClient
from meeting_interface.auth_client import HttpAuthClient

TOKEN = "t" * 43


def recording(status: int, body: object | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return seen, httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))


def test_session_sends_the_token_as_bearer_and_reads_the_user():
    seen, http = recording(200, {"id": "u-1", "email": "a@example.com"})

    user = HttpAuthClient(http).session(TOKEN)

    assert seen[0].url.path == "/v1/auth/session"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert user is not None and user.email == "a@example.com"


def test_expired_session_is_none():
    _, http = recording(401, {"error": {"code": "unauthorized"}})

    assert HttpAuthClient(http).session(TOKEN) is None


def test_unreachable_api_is_treated_as_signed_out():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(down))

    assert HttpAuthClient(http).session(TOKEN) is None
    HttpAuthClient(http).sign_out(TOKEN)  # does not raise


def test_sign_out_posts_with_the_token():
    seen, http = recording(204)

    HttpAuthClient(http).sign_out(TOKEN)

    assert (seen[0].method, seen[0].url.path) == ("POST", "/v1/auth/sign-out")
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_agent_client_forwards_the_session_only_when_acting_for_a_user():
    seen, http = recording(
        200, {"id": "p", "status": "rejected", "proposal_hash": "h", "actions": [], "outcomes": []}
    )
    agent = HttpAgentClient(http)

    agent.as_user(TOKEN).reject("p")
    agent.reject("p")

    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert "authorization" not in seen[1].headers
