"""Application tests that supply a controlled storage backend (Level 4).

Most tests use the ``fake_client`` fixture from ``tests/conftest.py``, an app over a
``FakeStorage``, to check which storage calls a request made and how a provider
failure reaches the caller. See ``tests/fakes.py``. The last tests build their own
apps to check how the app is built: an injected service is used as is, apps do not
share storage, and without one the backend and the upload limit come from the
environment. The last test pins the routes the app serves.
"""

from fastapi.testclient import TestClient

from storage_service.errors import ProviderError, ProviderUnavailable
from storage_service.main import create_app
from storage_service.service import FileService
from tests.conftest import MAX_UPLOAD_BYTES, send_file
from tests.fakes import FakeStorage


def test_invalid_key_is_rejected_before_storage_is_called(fake, fake_client):
    response = send_file(fake_client, "POST", "a//b.txt", b"data")

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "invalid_request"
    assert fake.calls == []


def test_metadata_returns_503_when_the_provider_is_unavailable(fake, fake_client):
    fake.fail("stat", ProviderUnavailable("could not reach the storage provider"))

    response = fake_client.get("/files/metadata?path=notes.txt")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "provider_unavailable", "message": "could not reach the storage provider"}
    }
    assert fake.calls == [("stat", "notes.txt")]


def test_create_returns_502_when_the_provider_rejects_the_write(fake, fake_client):
    fake.fail("put", ProviderError("the storage provider rejected the request"))

    response = send_file(fake_client, "POST", "notes.txt", b"data")

    assert response.status_code == 502
    assert response.json() == {
        "error": {"code": "provider_error", "message": "the storage provider rejected the request"}
    }
    assert fake.calls == [("stat", "notes.txt"), ("put", "notes.txt")]


def test_create_app_with_a_service_never_reads_settings_or_builds_storage(monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("create_app built its own storage despite an injected service")

    monkeypatch.setattr("storage_service.main.load_settings", must_not_run)
    monkeypatch.setattr("storage_service.main.build_storage", must_not_run)
    fake = FakeStorage()
    client = TestClient(create_app(FileService(fake, max_upload_bytes=MAX_UPLOAD_BYTES)))

    response = client.get("/files")

    assert response.status_code == 200
    assert response.json() == {"files": [], "next_cursor": None}
    assert fake.calls == [("list_files", "")]


def test_each_app_keeps_its_own_storage():
    first, second = FakeStorage(), FakeStorage()
    first_client = TestClient(create_app(FileService(first, max_upload_bytes=MAX_UPLOAD_BYTES)))
    second_client = TestClient(create_app(FileService(second, max_upload_bytes=MAX_UPLOAD_BYTES)))

    assert send_file(first_client, "POST", "notes.txt", b"data").status_code == 201

    assert second.calls == []
    assert second_client.get("/files").json()["files"] == []
    assert [f["key"] for f in first_client.get("/files").json()["files"]] == ["notes.txt"]


def test_create_app_without_a_service_builds_storage_from_the_environment(monkeypatch):
    for name in ("S3_ENDPOINT", "S3_REGION", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "8")
    client = TestClient(create_app())

    assert send_file(client, "POST", "at-limit.bin", b"x" * 8).status_code == 201
    too_big = send_file(client, "POST", "too-big.bin", b"x" * 9)
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "file_too_large"
    assert client.get("/files/metadata?path=too-big.bin").status_code == 404


def test_the_app_serves_the_six_operations_and_nothing_else(client):
    paths = client.get("/openapi.json").json()["paths"]
    routes = {(method.upper(), path) for path, methods in paths.items() for method in methods}
    assert routes == {
        ("GET", "/files"),
        ("POST", "/files/{key}"),
        ("PUT", "/files/{key}"),
        ("GET", "/files/download"),
        ("DELETE", "/files"),
        ("GET", "/files/metadata"),
    }

    # The schema shows {key} whether or not it may contain "/", so check that a key with
    # folders reaches every keyed route instead of 404 RouteNotFound.
    key = "a/b/notes.txt"
    assert send_file(client, "POST", key, b"data").status_code == 201
    assert send_file(client, "PUT", key, b"more").status_code == 200
    assert client.get("/files/download", params={"path": key}).content == b"more"
    assert client.get("/files/metadata", params={"path": key}).json()["path"] == "/" + key
    assert client.delete("/files", params={"path": key}).status_code == 204
