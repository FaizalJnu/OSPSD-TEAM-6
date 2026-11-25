"""The signed-in API's session lifecycle, isolation, and write boundary over HTTP."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient

from meeting_prep.agent.app import create_app
from meeting_prep.agent.http_api import HttpApiClient
from meeting_prep.agent.model import ScriptedModel
from meeting_prep.agent.proposals import REVIEW_MEETING, Action
from meeting_prep.api.providers import UserProviders, build_user_providers
from meeting_prep.api.sign_in import GoogleIdentity, SessionAuth, agent_principal
from meeting_prep.api.user_api import build_user_app
from meeting_prep.db import create_engine_for, upgrade
from meeting_prep.db.agent_store import AgentStore
from meeting_prep.db.identity_store import IdentityStore, SignIn

NOW = datetime(2026, 11, 24, tzinfo=UTC)
ORIGIN = "https://meeting.example"
MEETING = {
    "title": "Review",
    "start": "2026-11-25T18:00:00Z",
    "end": "2026-11-25T18:30:00Z",
    "agenda": ["Open changes"],
}


class FakeIdentity:
    def authorize_url(self, challenge: SignIn) -> str:
        return "https://example.org/?state=" + challenge.state

    def identity(self, code: str, challenge: SignIn) -> tuple[str, str]:
        assert challenge.verifier and challenge.nonce
        return code, f"{code}@example.org"


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite:///{tmp_path / 'identity.sqlite'}"
    upgrade(url)
    engine = create_engine_for(url)
    store = IdentityStore(engine)
    auth = SessionAuth(store, ORIGIN, clock=lambda: NOW)
    proposals = AgentStore(engine)
    providers = build_user_providers({"USER_PROVIDERS": "fake"})
    app = build_user_app(auth, FakeIdentity(), proposals, providers)
    return url, store, auth, proposals, providers, app


def signed_in_token(store: IdentityStore, subject: str) -> tuple[str, str]:
    token = store.issue(subject, f"{subject}@example.org", NOW)
    user = store.session_user(token, NOW)
    assert user is not None
    return token, user.id


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_browser_sign_in_uses_one_time_state_and_revokes_server_side(setup):
    url, store, auth, _, _, app = setup
    client = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    assert client.get("/v1/auth/session").status_code == 401
    redirect = client.get("/v1/auth/sign-in")
    state = parse_qs(urlsplit(redirect.headers["location"]).query)["state"][0]
    assert "__Host-meeting_sign_in" in redirect.headers["set-cookie"]
    assert (
        "HttpOnly" in redirect.headers["set-cookie"] and "Secure" in redirect.headers["set-cookie"]
    )
    callback = "/v1/auth/callback?" + urlencode({"state": state, "code": "alice"})
    stranger = TestClient(app, base_url=ORIGIN, follow_redirects=False)
    assert stranger.get(callback).status_code == 400
    assert client.get(callback).status_code == 303
    token = client.cookies[auth.session_cookie]
    assert client.get("/v1/auth/session").json()["email"] == "alice@example.org"
    assert IdentityStore(create_engine_for(url)).session_user(token, NOW) is not None
    assert store.session_user(token, NOW + timedelta(hours=8)) is None
    client.cookies.set(auth.state_cookie, state)
    assert client.get(callback).status_code == 400
    assert (
        client.post(
            "/v1/auth/sign-out", headers={"Origin": "https://elsewhere.example"}
        ).status_code
        == 403
    )
    assert client.post("/v1/auth/sign-out", headers={"Origin": ORIGIN}).status_code == 204
    assert stranger.get("/v1/auth/session", headers=bearer(token)).status_code == 401


def test_google_authorization_uses_s256_and_rejects_nonce_mismatch(monkeypatch):
    from meeting_prep.api import sign_in

    identity = GoogleIdentity("client", "secret", ORIGIN + "/v1/auth/callback")
    challenge = SignIn("state-value", "nonce-value", "verifier-value")
    params = parse_qs(urlsplit(identity.authorize_url(challenge)).query)
    assert params["nonce"] == ["nonce-value"] and params["code_challenge_method"] == ["S256"]
    assert "verifier-value" not in params["code_challenge"]

    def exchange(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        assert kwargs["data"]["code_verifier"] == "verifier-value"
        return httpx2.Response(200, json={"id_token": "test"}, request=httpx2.Request("POST", url))

    claims = {
        "sub": "alice",
        "email": "alice@example.org",
        "email_verified": True,
        "nonce": "wrong",
    }
    monkeypatch.setattr(httpx2, "post", exchange)
    monkeypatch.setattr(sign_in, "verify_oauth2_token", lambda *args, **kwargs: claims)
    with pytest.raises(sign_in.AuthError):
        identity.identity("code", challenge)
    claims["nonce"] = "nonce-value"
    assert identity.identity("code", challenge) == ("alice", "alice@example.org")


def test_reads_are_scoped_and_fail_closed_without_connections(setup):
    _, store, auth, proposals, providers, app = setup
    alice, alice_id = signed_in_token(store, "alice")
    bob, _ = signed_in_token(store, "bob")
    owned = providers(alice_id)
    assert owned.storage and owned.tracker and owned.calendar
    owned.storage.for_user(alice_id).create("write_agenda", "/reviews/test.md", b"private agenda")
    owned.storage.for_user(alice_id).create("write_agenda", "/reviews/big.md", b"x" * 33000)
    owned.tracker.create_issue("alice tracker item")
    owned.calendar.create("alice event", MEETING["start"], MEETING["end"])
    client = TestClient(app, base_url=ORIGIN)
    for route, key, content in (
        ("/v1/issues/open", "issues", "alice tracker item"),
        ("/v1/calendar/upcoming", "events", "alice event"),
    ):
        assert client.get(route).status_code == 401
        assert client.get(route, headers=bearer(alice)).json()[key][0]["title"] == content
        assert client.get(route, headers=bearer(bob)).json()[key] == []
    route = "/v1/documents"
    assert (
        client.get(route, headers=bearer(alice), params={"path": "/reviews/test.md"}).json()[
            "content"
        ]
        == "private agenda"
    )
    assert (
        client.get(route, headers=bearer(alice), params={"path": "/reviews/big.md"}).status_code
        == 413
    )
    for path, status in (
        ("/reviews/test.md", 404),
        (f"/users/{alice_id}/reviews/test.md", 404),
        (f"/reviews/../../users/{alice_id}/reviews/test.md", 400),
    ):
        assert client.get(route, headers=bearer(bob), params={"path": path}).status_code == status
    disconnected = build_user_app(auth, FakeIdentity(), proposals, lambda _user: UserProviders())
    assert (
        TestClient(disconnected).get("/v1/calendar/upcoming", headers=bearer(alice)).status_code
        == 503
    )


def test_execute_requires_current_approval_and_replays_saved_outcome(setup):
    _, store, _, proposals, providers, app = setup
    alice, alice_id = signed_in_token(store, "alice")
    bob, _ = signed_in_token(store, "bob")
    conversation = proposals.create_conversation(alice_id, "UTC", NOW)
    proposal = proposals.create_proposal(
        alice_id, conversation.id, None, [Action(REVIEW_MEETING, MEETING)], NOW
    )
    client = TestClient(app, base_url=ORIGIN)
    route = f"/v1/proposals/{proposal.id}/execute"
    tracker, calendar = providers(alice_id).tracker, providers(alice_id).calendar
    assert tracker and calendar
    invalid = {"proposal_hash": proposal.hash, "approval_id": "a" * 32}
    assert client.post(route, headers=bearer(alice), json=invalid).status_code == 409
    approval = proposals.approve(alice_id, proposal, NOW)
    exact = {"proposal_hash": proposal.hash, "approval_id": approval.id}
    assert client.post(route, headers=bearer(bob), json=exact).status_code == 404
    assert (
        client.post(
            route, headers=bearer(alice), json={**exact, "proposal_hash": "a" * 64}
        ).status_code
        == 409
    )
    assert (
        client.post(route, headers=bearer(alice), json={**exact, "actions": []}).status_code == 400
    )
    assert tracker.list_issues(10) == []
    first = client.post(route, headers=bearer(alice), json=exact)
    assert first.status_code == 200
    outcome = first.json()["outcomes"][0]
    assert outcome["status"] == "succeeded"
    assert client.post(route, headers=bearer(alice), json=exact).json() == first.json()
    assert len(tracker.list_issues(10)) == 1
    assert len(calendar.upcoming(NOW, NOW + timedelta(days=2))) == 1
    store.revoke(alice)
    assert client.post(route, headers=bearer(alice), json=exact).status_code == 401


def test_agent_forwards_real_session_and_uses_the_api_for_execution(setup, monkeypatch):
    from meeting_prep.agent.service import AgentService

    _, store, auth, proposals, providers, user_app = setup
    token, alice = signed_in_token(store, "alice")
    bob_token, _ = signed_in_token(store, "bob")
    real_client = httpx2.AsyncClient

    def route_to_user_app(**kwargs):
        return real_client(transport=httpx2.ASGITransport(app=user_app), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", route_to_user_app)

    def active_session(user):
        principal = agent_principal.get()
        return principal.token if principal is not None and principal.user.id == user else None

    agent_api = HttpApiClient(ORIGIN, active_session)
    service = AgentService(proposals, ScriptedModel([]), agent_api, now=lambda: NOW)
    app = create_app(service, auth=auth)
    client = TestClient(app, base_url=ORIGIN)
    reply = client.post("/v1/conversations", headers=bearer(token), json={"time_zone": "UTC"})
    assert reply.status_code == 201
    proposal = proposals.create_proposal(
        alice, reply.json()["id"], None, [Action(REVIEW_MEETING, MEETING)], NOW
    )
    route = f"/v1/proposals/{proposal.id}/approve"
    assert (
        client.post(
            route, headers=bearer(bob_token), json={"proposal_hash": proposal.hash}
        ).status_code
        == 404
    )
    response = client.post(route, headers=bearer(token), json={"proposal_hash": proposal.hash})
    assert response.status_code == 200, response.text
    assert response.json()["outcomes"][0]["status"] == "succeeded"
    assert len(proposals.outcomes(alice, proposal.id)) == 1
    assert agent_principal.get() is None


def test_resumable_execution_rechecks_session_and_approval(setup):
    from calendar_contract import CalendarError, ErrorCode

    from meeting_prep.adapters.calendar import EventCalendarAdapter
    from meeting_prep.fakes import FakeCalendar

    _, store, auth, proposals, providers, _ = setup
    token, user = signed_in_token(store, "alice")
    owned = providers(user)
    calendar = FakeCalendar()
    calendar.failures.fail_next(
        "create", CalendarError(ErrorCode.PROVIDER_UNAVAILABLE, "temporary", retryable=True)
    )
    connected = UserProviders(owned.storage, owned.tracker, EventCalendarAdapter(calendar))
    app = build_user_app(auth, FakeIdentity(), proposals, lambda _user: connected)
    client = TestClient(app, base_url=ORIGIN)
    conversation = proposals.create_conversation(user, "UTC", NOW)
    proposal = proposals.create_proposal(
        user, conversation.id, None, [Action(REVIEW_MEETING, MEETING)], NOW
    )
    approval = proposals.approve(user, proposal, NOW)
    route = f"/v1/proposals/{proposal.id}/execute"
    body = {"approval_id": approval.id, "proposal_hash": proposal.hash}

    failure = client.post(route, headers=bearer(token), json=body)
    assert failure.status_code == 503
    assert failure.json()["outcomes"][0]["status"] == "failed"
    assert proposals.get_proposal(user, proposal.id).status == "approved"
    store.revoke(token)
    assert client.post(route, headers=bearer(token), json=body).status_code == 401

    replacement, _ = signed_in_token(store, "alice")
    assert (
        client.post(
            route, headers=bearer(replacement), json={**body, "approval_id": "b" * 32}
        ).status_code
        == 409
    )
    success = client.post(route, headers=bearer(replacement), json=body)
    assert success.status_code == 200 and success.json()["outcomes"][0]["status"] == "succeeded"
    assert len(owned.tracker.list_issues(20)) == len(calendar.events) == 1


def test_tagged_tracker_recovery_is_scoped_to_the_signed_in_user(setup):
    from issue_tracker_contract import ErrorCode, ServiceError

    from meeting_prep.adapters.tracker import IssueTrackerAdapter
    from tests.fake_adapters import FakeTaggedTracker

    _, store, auth, proposals, providers, _ = setup
    tracker = FakeTaggedTracker()
    adapter = IssueTrackerAdapter(tracker)

    def connected(user: str) -> UserProviders:
        owned = providers(user)
        return UserProviders(owned.storage, adapter, owned.calendar)

    app = build_user_app(auth, FakeIdentity(), proposals, connected)
    client = TestClient(app, base_url=ORIGIN)

    def approved_request(subject: str) -> tuple[str, dict[str, str], dict[str, str]]:
        token, user = signed_in_token(store, subject)
        conversation = proposals.create_conversation(user, "UTC", NOW)
        proposal = proposals.create_proposal(
            user, conversation.id, None, [Action(REVIEW_MEETING, MEETING)], NOW
        )
        approval = proposals.approve(user, proposal, NOW)
        return (
            f"/v1/proposals/{proposal.id}/execute",
            bearer(token),
            {"approval_id": approval.id, "proposal_hash": proposal.hash},
        )

    route, headers, body = approved_request("alice")
    alice = client.post(route, headers=headers, json=body)
    assert alice.status_code == 200
    alice_issue = alice.json()["outcomes"][0]["detail"]["issue"]["id"]

    route, headers, body = approved_request("bob")
    tracker.failures.fail_next(
        "create_tagged_issue",
        ServiceError(ErrorCode.PROVIDER_ERROR, "lost response", may_have_applied=True),
        applied=True,
    )
    assert client.post(route, headers=headers, json=body).status_code == 503
    bob = client.post(route, headers=headers, json=body)
    assert bob.status_code == 200
    bob_issue = bob.json()["outcomes"][0]["detail"]["issue"]["id"]
    assert alice_issue != bob_issue
    assert tracker.descriptions[alice_issue] != tracker.descriptions[bob_issue]
    assert len(tracker.issues) == 2
