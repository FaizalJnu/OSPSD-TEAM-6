import pytest
from fastapi.testclient import TestClient

from meeting_interface.app import create_app
from meeting_interface.fake_api import FakeApiClient


@pytest.fixture
def fake_api() -> FakeApiClient:
    return FakeApiClient()


@pytest.fixture
def client(fake_api: FakeApiClient) -> TestClient:
    return TestClient(create_app(fake_api))


FORM = {"project": "Team 6 sprint", "meeting_date": "2026-11-27", "title": "Sprint review"}
