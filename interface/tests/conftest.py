import pytest
from fastapi.testclient import TestClient

from meeting_interface.app import create_app
from meeting_interface.fake_agent import FakeAgentClient
from meeting_interface.fake_api import FakeApiClient


@pytest.fixture
def fake_api() -> FakeApiClient:
    return FakeApiClient()


@pytest.fixture
def fake_agent() -> FakeAgentClient:
    return FakeAgentClient()


@pytest.fixture
def client(fake_api: FakeApiClient, fake_agent: FakeAgentClient) -> TestClient:
    return TestClient(create_app(fake_api, fake_agent))


FORM = {
    "title": "Sprint review",
    "day": "2026-11-27",
    "start_time": "15:00",
    "end_time": "15:30",
    "time_zone": "America/New_York",
    "agenda": "Open bugs\n\n  Release go or no-go  \n",
}
