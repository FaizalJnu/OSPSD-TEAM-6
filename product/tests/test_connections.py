"""Provider connections: sealed tokens, one-use challenges, refresh, and per-user providers.

Two users, Alice and Bob, share one database. Each isolation check also makes the
valid request, so a resolver that refused everything could not pass.
"""

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from meeting_prep import factories
from meeting_prep.adapters.calendar import EventCalendarAdapter
from meeting_prep.adapters.tracker import IssueTrackerAdapter
from meeting_prep.api import providers as providers_module
from meeting_prep.api.provider_tokens import GOOGLE_TOKEN_URL, GoogleRefresher, ProviderTokenError
from meeting_prep.api.providers import ConnectionResolver, build_user_providers
from meeting_prep.api.sign_in import SessionAuth
from meeting_prep.api.user_api import build_user_app
from meeting_prep.config import ConfigError
from meeting_prep.db import create_engine_for, upgrade
from meeting_prep.db.agent_store import AgentStore
from meeting_prep.db.connection_store import (
    CHALLENGE_TTL,
    Connection,
    ConnectionRevoked,
    ConnectionStore,
    Tokens,
)
from meeting_prep.db.identity_store import IdentityStore
from meeting_prep.fakes import FakeCalendar, FakeTracker
from meeting_prep.token_cipher import TokenCipher, TokenUnreadable

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
ORIGIN = "https://meeting.example"
APP_KEY = "trello-app-key"
KEY = TokenCipher.new_key()


@dataclass(frozen=True)
class Person:
    id: str
    session: str


@dataclass(frozen=True)
class Setup:
    engine: Engine
    store: ConnectionStore
    identity: IdentityStore
    alice: Person
    bob: Person


@pytest.fixture
def setup(tmp_path) -> Setup:
    url = f"sqlite:///{tmp_path / 'connections.sqlite3'}"
    upgrade(url)
    engine = create_engine_for(url)
    identity = IdentityStore(engine)

    def person(name: str) -> Person:
        session = identity.issue(name, f"{name}@example.org", NOW)
        user = identity.session_user(session, NOW)
        assert user is not None
        return Person(user.id, session)

    store = ConnectionStore(engine, TokenCipher([KEY]))
    return Setup(engine, store, identity, person("alice"), person("bob"))


def connect_trello(store: ConnectionStore, user_id: str, token: str, list_id: str | None) -> None:
    store.save(
        user_id,
        "trello",
        account="trello-user",
        scopes=("read", "write"),
        tokens=Tokens(token, NOW + timedelta(days=30)),
        settings={} if list_id is None else {"list_id": list_id, "list_name": "To Do"},
        now=NOW,
    )


def connect_google(
    store: ConnectionStore, user_id: str, expires_at: datetime, refresh: str | None = "refresh"
) -> None:
    store.save(
        user_id,
        "google_calendar",
        account="alice@example.org",
        scopes=("https://www.googleapis.com/auth/calendar.events",),
        tokens=Tokens("google-access", expires_at, refresh),
        now=NOW,
    )


def raw(setup: Setup, sql: str, **params: object) -> list[tuple[object, ...]]:
    with setup.engine.begin() as connection:
        result = connection.execute(text(sql), params)
        return [tuple(row) for row in result] if result.returns_rows else []


# The cipher.


def test_a_sealed_token_opens_only_with_its_own_context_and_key():
    cipher = TokenCipher([KEY])
    sealed = cipher.seal("secret-token", context="alice:trello:access_token")

    assert "secret-token" not in sealed
    assert cipher.open(sealed, context="alice:trello:access_token") == "secret-token"
    with pytest.raises(TokenUnreadable):
        cipher.open(sealed, context="bob:trello:access_token")
    with pytest.raises(TokenUnreadable):
        TokenCipher([TokenCipher.new_key()]).open(sealed, context="alice:trello:access_token")
    with pytest.raises(TokenUnreadable):
        cipher.open(sealed[:-4] + "AAAA", context="alice:trello:access_token")


def test_a_new_key_comes_first_and_the_old_one_still_opens_old_tokens():
    old, new = KEY, TokenCipher.new_key()
    sealed_before = TokenCipher([old]).seal("token", context="c")
    rotated = TokenCipher.from_env({"CONNECTION_TOKEN_KEY": f"{new}, {old}"})

    assert rotated.open(sealed_before, context="c") == "token"
    assert TokenCipher([new]).open(rotated.seal("token", context="c"), context="c") == "token"


@pytest.mark.parametrize(
    ("value", "message"),
    [("", "CONNECTION_TOKEN_KEY is not set"), ("not-a-key", "must hold Fernet keys")],
)
def test_a_bad_key_stops_startup_without_echoing_it(value, message):
    with pytest.raises(ConfigError, match=message) as raised:
        TokenCipher.from_env({"CONNECTION_TOKEN_KEY": value})
    assert "not-a-key" not in str(raised.value)


# The store.


def test_tokens_are_written_sealed_and_read_back(setup):
    connect_trello(setup.store, setup.alice.id, "alice-token", "list-a")

    [(stored,)] = raw(setup, "SELECT access_token FROM provider_connections")
    assert "alice-token" not in str(stored)
    connection = setup.store.get(setup.alice.id, "trello")
    assert connection is not None
    assert connection.access_token == "alice-token"
    assert "alice-token" not in repr(connection)
    [summary] = setup.store.summaries(setup.alice.id)
    assert summary.account == "trello-user"
    assert summary.settings == {"list_id": "list-a", "list_name": "To Do"}
    assert not hasattr(summary, "access_token")


def test_each_user_reaches_only_their_own_connections(setup):
    alice, bob = setup.alice.id, setup.bob.id
    connect_trello(setup.store, alice, "alice-token", "list-a")

    assert setup.store.get(bob, "trello") is None
    assert setup.store.summaries(bob) == []
    assert setup.store.update_settings(bob, "trello", {"list_id": "list-b"}, NOW) is False
    setup.store.mark_needs_attention(bob, "trello", NOW)
    assert setup.store.remove(bob, "trello") is None

    connection = setup.store.get(alice, "trello")
    assert connection is not None
    assert (connection.status, connection.settings["list_id"]) == ("connected", "list-a")
    assert setup.store.update_settings(alice, "trello", {"list_id": "list-a2"}, NOW) is True


def test_a_token_copied_into_another_users_row_cannot_be_used(setup):
    connect_trello(setup.store, setup.alice.id, "alice-token", "list-a")
    connect_trello(setup.store, setup.bob.id, "bob-token", "list-b")
    raw(
        setup,
        "UPDATE provider_connections SET access_token = "
        "(SELECT access_token FROM provider_connections WHERE user_id = :alice) "
        "WHERE user_id = :bob",
        alice=setup.alice.id,
        bob=setup.bob.id,
    )

    with pytest.raises(TokenUnreadable):
        setup.store.get(setup.bob.id, "trello")
    connection = setup.store.get(setup.alice.id, "trello")
    assert connection is not None and connection.access_token == "alice-token"


def test_reconnecting_replaces_the_tokens_and_clears_needs_attention(setup):
    connect_google(setup.store, setup.alice.id, NOW + timedelta(hours=1), refresh="old-refresh")
    setup.store.mark_needs_attention(setup.alice.id, "google_calendar", NOW)
    connect_google(setup.store, setup.alice.id, NOW + timedelta(hours=1), refresh="new-refresh")

    connection = setup.store.get(setup.alice.id, "google_calendar")
    assert connection is not None
    assert (connection.status, connection.refresh_token) == ("connected", "new-refresh")


def test_removing_returns_the_tokens_to_revoke_and_deletes_the_row(setup):
    connect_trello(setup.store, setup.alice.id, "alice-token", "list-a")

    removed = setup.store.remove(setup.alice.id, "trello")

    assert removed is not None and removed.access_token == "alice-token"
    assert setup.store.get(setup.alice.id, "trello") is None
    assert raw(setup, "SELECT count(*) FROM provider_connections") == [(0,)]


# Challenges.


def test_a_challenge_works_once_for_the_user_and_session_that_started_it(setup):
    alice, bob = setup.alice, setup.bob
    state = setup.store.start_challenge(alice.id, alice.session, "google_calendar", "verifier", NOW)

    [(digest, secret)] = raw(setup, "SELECT digest, secret FROM connection_challenges")
    assert state not in str(digest) and "verifier" not in str(secret)
    other_session = setup.identity.issue("alice", "alice@example.org", NOW)
    assert setup.store.finish_challenge(state, bob.id, bob.session, "google_calendar", NOW) is None
    assert (
        setup.store.finish_challenge(state, alice.id, other_session, "google_calendar", NOW) is None
    )
    assert setup.store.finish_challenge(state, alice.id, alice.session, "trello", NOW) is None

    finish = setup.store.finish_challenge
    assert finish(state, alice.id, alice.session, "google_calendar", NOW) == "verifier"
    assert finish(state, alice.id, alice.session, "google_calendar", NOW) is None


def test_an_expired_challenge_is_refused(setup):
    alice = setup.alice
    state = setup.store.start_challenge(alice.id, alice.session, "trello", "request-secret", NOW)

    later = NOW + CHALLENGE_TTL
    assert setup.store.finish_challenge(state, alice.id, alice.session, "trello", later) is None


# Refresh.


def renewing(token: str = "google-new", refresh: str | None = None):
    calls: list[Connection] = []

    def renew(connection: Connection) -> Tokens:
        calls.append(connection)
        return Tokens(token, NOW + timedelta(hours=1), refresh)

    return renew, calls


def test_an_expiring_token_is_renewed_and_the_replacement_saved(setup):
    connect_google(setup.store, setup.alice.id, NOW + timedelta(minutes=1))
    renew, calls = renewing()

    renewed = setup.store.refresh(setup.alice.id, "google_calendar", NOW, renew)

    assert [call.refresh_token for call in calls] == ["refresh"]
    assert renewed is not None and renewed.access_token == "google-new"
    reread = ConnectionStore(setup.store.engine, TokenCipher([KEY])).get(
        setup.alice.id, "google_calendar"
    )
    assert reread is not None
    assert (reread.access_token, reread.refresh_token) == ("google-new", "refresh")
    assert reread.expires_at == NOW + timedelta(hours=1)


def test_a_rotated_refresh_token_replaces_the_stored_one(setup):
    connect_google(setup.store, setup.alice.id, NOW)
    renew, _ = renewing(refresh="rotated")

    setup.store.refresh(setup.alice.id, "google_calendar", NOW, renew)

    reread = setup.store.get(setup.alice.id, "google_calendar")
    assert reread is not None and reread.refresh_token == "rotated"


def test_a_token_with_time_left_is_not_renewed(setup):
    connect_google(setup.store, setup.alice.id, NOW + timedelta(hours=1))
    renew, calls = renewing()

    current = setup.store.refresh(setup.alice.id, "google_calendar", NOW, renew)

    assert calls == []
    assert current is not None and current.access_token == "google-access"


def test_a_revoked_grant_marks_the_connection_as_needing_attention(setup):
    connect_google(setup.store, setup.alice.id, NOW)

    def revoked(_connection: Connection) -> Tokens:
        raise ConnectionRevoked()

    result = setup.store.refresh(setup.alice.id, "google_calendar", NOW, revoked)

    assert result is not None and result.status == "needs_attention"
    [summary] = setup.store.summaries(setup.alice.id)
    assert summary.status == "needs_attention"


def test_a_failed_renewal_leaves_the_stored_tokens_unchanged(setup):
    connect_google(setup.store, setup.alice.id, NOW)

    def unavailable(_connection: Connection) -> Tokens:
        raise ProviderTokenError()

    with pytest.raises(ProviderTokenError):
        setup.store.refresh(setup.alice.id, "google_calendar", NOW, unavailable)
    stored = setup.store.get(setup.alice.id, "google_calendar")
    assert stored is not None
    assert (stored.access_token, stored.status) == ("google-access", "connected")


def test_two_requests_that_find_an_expired_token_renew_it_once(setup):
    connect_google(setup.store, setup.alice.id, NOW)
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def slow_renew(_connection: Connection) -> Tokens:
        calls.append("renew")
        started.set()
        release.wait(5)
        return Tokens("google-new", NOW + timedelta(hours=1))

    results: list[Connection | None] = []

    def request() -> None:
        results.append(setup.store.refresh(setup.alice.id, "google_calendar", NOW, slow_renew))

    first = threading.Thread(target=request)
    first.start()
    assert started.wait(5)
    second = threading.Thread(target=request)
    second.start()
    # Without the lock, the second request reaches Google in this time.
    second.join(0.3)
    release.set()
    first.join(5)
    second.join(5)

    assert calls == ["renew"]
    assert [result.access_token for result in results if result is not None] == [
        "google-new",
        "google-new",
    ]


# Google's token endpoint.


def google_answers(monkeypatch, status: int, body: object, seen: list[dict[str, str]]) -> None:
    def post(url: str, **kwargs: object) -> httpx2.Response:
        assert url == GOOGLE_TOKEN_URL
        seen.append(kwargs["data"])  # type: ignore[arg-type]
        return httpx2.Response(status, json=body, request=httpx2.Request("POST", url))

    monkeypatch.setattr(httpx2, "post", post)


def stored_google(refresh: str | None = "refresh-1") -> Connection:
    return Connection(
        "google_calendar", "a@example.org", (), "connected", {}, NOW, NOW, "old", refresh
    )


def test_google_renews_with_the_stored_refresh_token(monkeypatch):
    seen: list[dict[str, str]] = []
    google_answers(monkeypatch, 200, {"access_token": "new", "expires_in": 3599}, seen)

    tokens = GoogleRefresher("client", "client-secret", clock=lambda: NOW)(stored_google())

    assert seen[0]["grant_type"] == "refresh_token"
    assert seen[0]["refresh_token"] == "refresh-1"
    assert tokens == Tokens("new", NOW + timedelta(seconds=3599), None)


@pytest.mark.parametrize("error", ["invalid_grant", "unauthorized_client"])
def test_google_refusing_the_grant_means_reconnect(monkeypatch, error):
    google_answers(monkeypatch, 400, {"error": error}, [])

    with pytest.raises(ConnectionRevoked):
        GoogleRefresher("client", "secret")(stored_google())


def test_a_connection_without_a_refresh_token_means_reconnect():
    with pytest.raises(ConnectionRevoked):
        GoogleRefresher("client", "secret")(stored_google(refresh=None))


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (500, {"error": "internal"}),
        (200, {"access_token": "new"}),
        (200, {"access_token": "", "expires_in": 3599}),
        (200, ["not", "an", "object"]),
    ],
)
def test_other_google_answers_are_temporary_failures(monkeypatch, status, body):
    google_answers(monkeypatch, status, body, [])

    with pytest.raises(ProviderTokenError) as raised:
        GoogleRefresher("client", "secret")(stored_google())
    assert str(raised.value) == ""


def test_an_unreachable_google_is_a_temporary_failure(monkeypatch):
    def post(url: str, **_kwargs: object) -> httpx2.Response:
        raise httpx2.ConnectError("refresh-1 unreachable")

    monkeypatch.setattr(httpx2, "post", post)

    with pytest.raises(ProviderTokenError) as raised:
        GoogleRefresher("client", "secret")(stored_google())
    assert "refresh-1" not in str(raised.value)


# The resolver.


@dataclass
class Built:
    trackers: list[tuple[str, str, str]]
    calendars: list[str]


def resolver(setup: Setup, renew=None) -> tuple[ConnectionResolver, Built]:
    built = Built([], [])

    def tracker_for(key: str, token: str, list_id: str) -> IssueTrackerAdapter:
        built.trackers.append((key, token, list_id))
        return IssueTrackerAdapter(FakeTracker())

    def calendar_for(connection: Connection) -> EventCalendarAdapter:
        built.calendars.append(connection.access_token)
        return EventCalendarAdapter(FakeCalendar())

    return (
        ConnectionResolver(
            setup.store,
            None,
            trello_app_key=APP_KEY,
            tracker_for=tracker_for,
            calendar_for=calendar_for,
            renew_google=renew,
            clock=lambda: NOW,
        ),
        built,
    )


def test_each_user_gets_a_tracker_built_from_their_own_connection(setup):
    connect_trello(setup.store, setup.alice.id, "alice-token", "list-a")
    resolve, built = resolver(setup)

    assert resolve.for_user(setup.alice.id).tracker is not None
    assert resolve.for_user(setup.bob.id).tracker is None
    assert built.trackers == [(APP_KEY, "alice-token", "list-a")]


def test_a_trello_connection_without_a_list_builds_no_tracker(setup):
    connect_trello(setup.store, setup.alice.id, "alice-token", None)
    resolve, built = resolver(setup)

    assert resolve.for_user(setup.alice.id).tracker is None
    assert built.trackers == []


def test_an_expired_trello_token_needs_attention(setup):
    setup.store.save(
        setup.alice.id,
        "trello",
        account="alice",
        scopes=("read", "write"),
        tokens=Tokens("alice-token", NOW),
        settings={"list_id": "list-a"},
        now=NOW - timedelta(days=30),
    )
    resolve, built = resolver(setup)

    assert resolve.for_user(setup.alice.id).tracker is None
    assert built.trackers == []
    [summary] = setup.store.summaries(setup.alice.id)
    assert summary.status == "needs_attention"


def test_the_calendar_gets_a_renewed_token_before_use(setup):
    connect_google(setup.store, setup.alice.id, NOW + timedelta(minutes=2))
    renew, calls = renewing("google-new")
    resolve, built = resolver(setup, renew)

    assert resolve.for_user(setup.alice.id).calendar is not None
    assert resolve.for_user(setup.bob.id).calendar is None
    assert len(calls) == 1
    assert built.calendars == ["google-new"]


def test_a_revoked_calendar_is_not_used(setup):
    connect_google(setup.store, setup.alice.id, NOW)

    def revoked(_connection: Connection) -> Tokens:
        raise ConnectionRevoked()

    resolve, built = resolver(setup, revoked)

    assert resolve.for_user(setup.alice.id).calendar is None
    assert built.calendars == []
    assert resolve.for_user(setup.alice.id).calendar is None


def test_an_unreachable_google_keeps_the_stored_token_for_this_request(setup):
    connect_google(setup.store, setup.alice.id, NOW)

    def unavailable(_connection: Connection) -> Tokens:
        raise ProviderTokenError()

    resolve, built = resolver(setup, unavailable)

    assert resolve.for_user(setup.alice.id).calendar is not None
    assert built.calendars == ["google-access"]


def test_unreadable_tokens_count_as_not_connected_and_are_not_marked(setup):
    connect_trello(setup.store, setup.alice.id, "alice-token", "list-a")
    wrong_key = ConnectionStore(setup.store.engine, TokenCipher([TokenCipher.new_key()]))
    resolve = ConnectionResolver(wrong_key, None, trello_app_key=APP_KEY, clock=lambda: NOW)

    assert resolve.for_user(setup.alice.id).tracker is None
    [summary] = setup.store.summaries(setup.alice.id)
    assert summary.status == "connected"


# Configuration.

TEAM_ACCOUNT = {
    "TRELLO_API_KEY": "team-key",
    "TRELLO_TOKEN": "team-token",
    "TRELLO_LIST_ID": "team-list",
}


def test_connections_mode_builds_trello_from_the_users_token_never_the_team_account(
    setup, monkeypatch
):
    built: list[tuple[str, str, str]] = []

    def build(key: str, token: str, list_id: str) -> FakeTracker:
        built.append((key, token, list_id))
        return FakeTracker()

    monkeypatch.setattr(providers_module, "build_user_tracker", build)
    env = {"USER_PROVIDERS": "connections", "TRELLO_APP_KEY": APP_KEY, **TEAM_ACCOUNT}
    connect_trello(setup.store, setup.alice.id, "alice-token", "list-a")
    for_user = build_user_providers(env, setup.store)

    assert for_user(setup.bob.id).tracker is None
    assert for_user(setup.alice.id).tracker is not None
    assert built == [(APP_KEY, "alice-token", "list-a")]


@pytest.mark.parametrize(
    ("env", "with_store", "message"),
    [
        ({"USER_PROVIDERS": "connections"}, True, "TRELLO_APP_KEY is not set"),
        ({"USER_PROVIDERS": "connections", "TRELLO_APP_KEY": APP_KEY}, False, "needs"),
        ({"USER_PROVIDERS": "shared"}, True, "USER_PROVIDERS must be one of"),
    ],
)
def test_connections_mode_needs_its_settings(setup, env, with_store, message):
    with pytest.raises(ConfigError, match=message):
        build_user_providers(env, setup.store if with_store else None)


def test_the_user_tracker_builder_passes_the_account_to_team_4(monkeypatch):
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(factories, "TrelloIssueProvider", lambda **kwargs: seen.append(kwargs))

    factories.build_user_tracker("key", "token", "list")
    factories.TRACKER_BUILDERS["team4-trello"](TEAM_ACCOUNT)

    assert seen == [
        {"api_key": "key", "token": "token", "list_id": "list"},
        {"api_key": "team-key", "token": "team-token", "list_id": "team-list"},
    ]


# Over HTTP.


def test_the_api_reads_each_users_own_tracker_and_asks_others_to_connect(setup):
    trackers = {"alice-token": FakeTracker()}
    trackers["alice-token"].create_issue("Alice's issue")
    resolve = ConnectionResolver(
        setup.store,
        None,
        trello_app_key=APP_KEY,
        tracker_for=lambda _key, token, _list: IssueTrackerAdapter(trackers[token]),
        clock=lambda: NOW,
    )
    connect_trello(setup.store, setup.alice.id, "alice-token", "list-a")
    auth = SessionAuth(setup.identity, ORIGIN, clock=lambda: NOW)
    app = build_user_app(auth, object(), AgentStore(setup.store.engine), resolve.for_user)  # type: ignore[arg-type]
    client = TestClient(app, base_url=ORIGIN)

    alice = client.get(
        "/v1/issues/open", headers={"Authorization": f"Bearer {setup.alice.session}"}
    )
    bob = client.get("/v1/issues/open", headers={"Authorization": f"Bearer {setup.bob.session}"})

    assert alice.status_code == 200
    assert [issue["title"] for issue in alice.json()["issues"]] == ["Alice's issue"]
    assert bob.status_code == 503
    assert bob.json()["error"]["message"] == "Connect your issue tracker first."
