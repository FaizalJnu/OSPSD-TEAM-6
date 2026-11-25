import pytest
from fastapi.testclient import TestClient

from meeting_interface.app import WebSettings, create_app
from meeting_interface.fake_agent import FakeAgentClient
from meeting_interface.fake_api import FakeApiClient
from meeting_interface.fake_auth import FakeAuthClient

ORIGIN = "http://testserver"
# Tests run over plain HTTP, where browsers refuse __Host- cookies, so they use
# the API's local-development name.
SESSION_COOKIE = "meeting_session"
TOKEN = "a" * 43


@pytest.fixture
def fake_api() -> FakeApiClient:
    return FakeApiClient()


@pytest.fixture
def fake_agent() -> FakeAgentClient:
    return FakeAgentClient()


@pytest.fixture
def fake_auth() -> FakeAuthClient:
    return FakeAuthClient({TOKEN: "a@example.com"})


@pytest.fixture
def app(fake_api: FakeApiClient, fake_agent: FakeAgentClient, fake_auth: FakeAuthClient):
    web = WebSettings(session_cookie=SESSION_COOKIE, public_origin=ORIGIN)
    return create_app(fake_api, fake_agent, fake_auth, web)


@pytest.fixture
def client(app) -> TestClient:
    """A browser signed in as a@example.com."""
    browser = TestClient(app)
    browser.cookies.set(SESSION_COOKIE, TOKEN)
    return browser


@pytest.fixture
def anon(app) -> TestClient:
    """A browser with no session."""
    return TestClient(app)


FORM = {
    "title": "Sprint review",
    "day": "2026-11-27",
    "start_time": "15:00",
    "end_time": "15:30",
    "time_zone": "America/New_York",
    "agenda": "Open bugs\n\n  Release go or no-go  \n",
}
