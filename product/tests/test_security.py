"""Credential lifecycle and secret handling across the user API and the agent service.

Complements tests/test_user_api.py (one-time OAuth state, PKCE and nonce, scoped
reads, approvals at execute) and the agent tests (isolation, run records). Every
test sends a valid request as a control, so refusing everything cannot pass.
TESTING.md maps each security requirement to its tests.
"""

import json
import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meeting_prep.agent.app import create_app
from meeting_prep.agent.http_api import HttpApiClient
from meeting_prep.agent.model import ScriptedModel, ScriptStep
from meeting_prep.agent.proposals import REVIEW_MEETING, Action
from meeting_prep.agent.service import AgentService
from meeting_prep.api.providers import build_user_providers
from meeting_prep.api.sign_in import AuthError, SessionAuth, agent_principal
from meeting_prep.api.user_api import build_user_app
from meeting_prep.db import create_engine_for, upgrade
from meeting_prep.db.agent_store import AgentStore
from meeting_prep.db.identity_store import IdentityStore, SignIn
from meeting_prep.db.tables.identity import SessionRow
from tests.test_user_api import MEETING, NOW, ORIGIN, FakeIdentity, bearer, signed_in_token

answer, call = ScriptedModel.answer, ScriptedModel.call


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class World:
    """Both services on one SQLite database, as deployed: the user API and the agent."""

    def __init__(self, url: str, clock: Clock, script: Sequence[ScriptStep] = ()) -> None:
        self.url = url
        self.engine = create_engine_for(url)
        self.store = IdentityStore(self.engine)
        self.auth = SessionAuth(self.store, ORIGIN, clock=clock)
        self.proposals = AgentStore(self.engine)
        self.providers = build_user_providers({"USER_PROVIDERS": "fake"})
        self.identity = RecordingIdentity()
        self.user_app = build_user_app(self.auth, self.identity, self.proposals, self.providers)
        self.model = ScriptedModel(script)
        api = HttpApiClient(ORIGIN, _session_for)
        self.service = AgentService(self.proposals, self.model, api, now=clock)
        self.agent_app = create_app(self.service, auth=self.auth)

    def api(self) -> TestClient:
        return TestClient(self.user_app, base_url=ORIGIN, follow_redirects=False)

    def agent(self) -> TestClient:
        return TestClient(self.agent_app, base_url=ORIGIN)

    def session_count(self) -> int:
        with Session(self.engine) as db:
            return int(db.scalar(select(func.count()).select_from(SessionRow)) or 0)


class RecordingIdentity(FakeIdentity):
    """The fake Google identity, recording each code exchange it is asked for."""

    def __init__(self) -> None:
        self.exchanged: list[str] = []
        self.fail = False

    def identity(self, code: str, challenge: SignIn) -> tuple[str, str]:
        self.exchanged.append(code)
        if self.fail:
            raise AuthError()
        return super().identity(code, challenge)


def _session_for(user: str) -> str | None:
    principal = agent_principal.get()
    return principal.token if principal is not None and principal.user.id == user else None


@pytest.fixture
def url(tmp_path) -> str:
    database = f"sqlite:///{tmp_path / 'security.sqlite'}"
    upgrade(database)
    return database


@pytest.fixture
def clock() -> Clock:
    return Clock(NOW)


@pytest.fixture
def world(url, clock) -> World:
    return World(url, clock)


def reads_ok(world: World, headers: dict[str, str]) -> bool:
    return world.api().get("/v1/issues/open", headers=headers).status_code == 200


def agent_ok(world: World, headers: dict[str, str]) -> bool:
    response = world.agent().post("/v1/conversations", headers=headers, json={"time_zone": "UTC"})
    return response.status_code == 201


def statuses(world: World, headers: dict[str, str]) -> tuple[int, int]:
    api = world.api().get("/v1/issues/open", headers=headers).status_code
    agent = world.agent().post("/v1/conversations", headers=headers, json={"time_zone": "UTC"})
    return api, agent.status_code


# --- Missing and invalid credentials ---------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic YWxpY2U6c2VjcmV0"},
        {"Authorization": "Bearer short"},
        {"Authorization": "Bearer " + "a" * 43},  # well formed, never issued
        {"Authorization": "Bearer"},
    ],
    ids=["missing", "basic-scheme", "malformed", "never-issued", "empty-bearer"],
)
def test_invalid_credentials_are_401_on_both_services(world, headers):
    token, _ = signed_in_token(world.store, "alice")

    assert statuses(world, headers) == (401, 401)
    assert reads_ok(world, bearer(token)) and agent_ok(world, bearer(token))  # control


def test_a_garbage_session_cookie_is_401_on_both_services(world):
    token, _ = signed_in_token(world.store, "alice")
    api, agent = world.api(), world.agent()
    api.cookies.set(world.auth.session_cookie, "not-a-session")
    agent.cookies.set(world.auth.session_cookie, "b" * 43)

    assert api.get("/v1/auth/session").status_code == 401
    assert agent.get("/v1/conversations/x").status_code == 401
    assert reads_ok(world, bearer(token))  # control


# --- Expiry and revocation --------------------------------------------------------


def test_an_expired_session_is_401_on_both_services(world, clock):
    token, _ = signed_in_token(world.store, "alice")

    clock.now = NOW + timedelta(hours=7, minutes=59)
    assert reads_ok(world, bearer(token)) and agent_ok(world, bearer(token))

    clock.now = NOW + timedelta(hours=8, seconds=1)
    assert statuses(world, bearer(token)) == (401, 401)

    fresh, _ = signed_in_token(world.store, "alice")
    assert world.store.session_user(fresh, NOW) is not None  # control: a new sign-in works


def test_a_signed_out_session_cannot_be_replayed_anywhere(world):
    token, alice = signed_in_token(world.store, "alice")
    bob, _ = signed_in_token(world.store, "bob")
    conversation = world.proposals.create_conversation(alice, "UTC", NOW)
    proposal = world.proposals.create_proposal(
        alice, conversation.id, None, [Action(REVIEW_MEETING, MEETING)], NOW
    )

    signed_out = world.api().post("/v1/auth/sign-out", headers=bearer(token))

    assert signed_out.status_code == 204
    assert statuses(world, bearer(token)) == (401, 401)
    approve = world.agent().post(
        f"/v1/proposals/{proposal.id}/approve",
        headers=bearer(token),
        json={"proposal_hash": proposal.hash},
    )
    assert approve.status_code == 401
    assert world.proposals.get_proposal(alice, proposal.id).status == "pending"
    tracker = world.providers(alice).tracker
    assert tracker is not None and tracker.list_issues(10) == []
    assert reads_ok(world, bearer(bob))  # control: another user's session is untouched


# --- Sign-in integrity ------------------------------------------------------------


def start_sign_in(client: TestClient) -> str:
    redirect = client.get("/v1/auth/sign-in")
    return parse_qs(urlsplit(redirect.headers["location"]).query)["state"][0]


def callback(client: TestClient, state: str, code: str):
    return client.get("/v1/auth/callback?" + urlencode({"state": state, "code": code}))


def test_a_failed_sign_in_creates_no_session(world):
    browser = world.api()
    state = start_sign_in(browser)
    other = world.api()
    other_state = start_sign_in(other)

    attempts = [
        callback(browser, other_state, "alice"),  # another browser's state
        callback(world.api(), state, "alice"),  # no state cookie at all
    ]
    world.identity.fail = True
    attempts.append(callback(browser, state, "alice"))  # Google rejects the code

    for response in attempts:
        assert response.status_code == 400
        assert world.auth.session_cookie not in response.headers.get("set-cookie", "")
    assert world.identity.exchanged == ["alice"]  # only the matching state reached Google
    assert world.session_count() == 0

    world.identity.fail = False  # control: a clean sign-in still works
    fresh = world.api()
    assert callback(fresh, start_sign_in(fresh), "alice").status_code == 303
    assert world.session_count() == 1


def test_a_used_sign_in_state_cannot_start_a_second_session(world):
    browser = world.api()
    state = start_sign_in(browser)

    assert callback(browser, state, "alice").status_code == 303
    browser.cookies.set(world.auth.state_cookie, state)
    assert callback(browser, state, "mallory").status_code == 400
    assert world.session_count() == 1


# --- Restart ------------------------------------------------------------------------


def test_sessions_survive_a_restart_of_both_services(url, clock):
    before = World(url, clock)
    token, alice = signed_in_token(before.store, "alice")
    revoked, _ = signed_in_token(before.store, "carol")
    before.store.revoke(revoked)
    conversation = before.agent().post(
        "/v1/conversations", headers=bearer(token), json={"time_zone": "UTC"}
    )

    after = World(url, clock)  # new engines, stores and apps on the same database

    assert reads_ok(after, bearer(token))
    fetched = after.agent().get(
        f"/v1/conversations/{conversation.json()['id']}", headers=bearer(token)
    )
    assert fetched.status_code == 200
    assert after.api().get("/v1/auth/session", headers=bearer(token)).json()["id"] == alice
    assert statuses(after, bearer(revoked)) == (401, 401)  # control: revocation persists


# --- Secrets in logs and prompts ------------------------------------------------------


def test_no_session_token_or_oauth_code_in_logs_or_model_prompts(url, clock, caplog, monkeypatch):
    code = "oauth-code-DO-NOT-LOG-91c2"
    script = [call("list_open_issues", "{}"), answer("You have no open issues.")]
    world = World(url, clock, script)
    route_to(world.user_app, monkeypatch)
    caplog.set_level(logging.DEBUG)

    browser = world.api()
    assert callback(browser, start_sign_in(browser), code).status_code == 303
    token = browser.cookies[world.auth.session_cookie]
    created = world.agent().post(
        "/v1/conversations", headers=bearer(token), json={"time_zone": "UTC"}
    )
    reply = world.agent().post(
        f"/v1/conversations/{created.json()['id']}/messages",
        headers=bearer(token),
        json={"text": "What is open?"},
    )
    assert reply.status_code == 200 and reply.json()["reply"] == "You have no open issues."

    user = world.store.session_user(token, NOW)
    assert user is not None
    record = world.proposals.get_run(user.id, reply.json()["run_id"])
    prompts = [str(m.content) for c in world.model.calls for m in c.messages]
    # The test's own browser (TestClient, on httpx2) logs the callback URL it requests;
    # that line is the test harness, not the service, so it is left out.
    service_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not (record.name == "httpx2" and "/v1/auth/callback" in record.getMessage())
    )
    for secret in (token, code):
        assert secret not in service_logs
        assert all(secret not in text for text in prompts)
        assert secret not in json.dumps(record, default=str)
    assert any(m.role == "tool" for c in world.model.calls for m in c.messages)  # control


def route_to(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """Send the agent's API calls to the in-process user API instead of the network."""
    real: Callable[..., httpx2.AsyncClient] = httpx2.AsyncClient

    def in_process(**kwargs: object) -> httpx2.AsyncClient:
        return real(transport=httpx2.ASGITransport(app=app), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", in_process)
