"""Application tests that supply a controlled storage backend (Level 4).

Each test uses the ``fake_client`` fixture from ``tests/conftest.py``, an app over a
``FakeStorage``, to check which storage calls a request made and how a provider
failure reaches the caller. See ``tests/fakes.py``.
"""

from storage_service.errors import ProviderError, ProviderUnavailable
from tests.conftest import send_file


def test_invalid_key_is_rejected_before_storage_is_called(fake, fake_client):
    response = send_file(fake_client, "POST", "a//b.txt", b"data")

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error", "detail"}
    assert body["error"] == "InvalidInput"
    assert fake.calls == []


def test_metadata_returns_503_when_the_provider_is_unavailable(fake, fake_client):
    fake.fail("stat", ProviderUnavailable("could not reach the storage provider"))

    response = fake_client.get("/metadata/notes.txt")

    assert response.status_code == 503
    assert response.json() == {
        "error": "ProviderUnavailable",
        "detail": "could not reach the storage provider",
    }
    assert fake.calls == [("stat", "notes.txt")]


def test_create_returns_502_when_the_provider_rejects_the_write(fake, fake_client):
    fake.fail("put", ProviderError("storage provider rejected the request (AccessDenied)"))

    response = send_file(fake_client, "POST", "notes.txt", b"data")

    assert response.status_code == 502
    assert response.json() == {
        "error": "ProviderError",
        "detail": "storage provider rejected the request (AccessDenied)",
    }
    assert fake.calls == [("stat", "notes.txt"), ("put", "notes.txt")]
