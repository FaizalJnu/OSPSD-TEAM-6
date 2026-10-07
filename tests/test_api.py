"""End-to-end tests of the HTTP API, backed by in-memory storage (no network)."""

import pytest
from fastapi.testclient import TestClient

from storage_service.main import create_app
from storage_service.service import FileService
from storage_service.storage.memory import InMemoryStorage

MAX_UPLOAD_BYTES = 1024


@pytest.fixture
def client() -> TestClient:
    """A client for a fresh app with empty in-memory storage, so tests never share state."""
    service = FileService(InMemoryStorage(), max_upload_bytes=MAX_UPLOAD_BYTES)
    return TestClient(create_app(service))


def send_file(client: TestClient, method: str, key: str, data: bytes):
    return client.request(method, f"/files/{key}", files={"file": ("upload", data)})


def test_upload_then_download_returns_identical_bytes(client):
    data = b"\x89PNG not really an image \x00\xff"
    created = send_file(client, "POST", "photos/cat.png", data)
    assert created.status_code == 201
    assert created.json()["size"] == len(data)

    downloaded = client.get("/files/photos/cat.png")
    assert downloaded.status_code == 200
    assert downloaded.content == data
    assert downloaded.headers["content-type"] == "image/png"


def test_create_refuses_to_overwrite(client):
    send_file(client, "POST", "notes.txt", b"first")
    second = send_file(client, "POST", "notes.txt", b"second")
    assert second.status_code == 409
    assert second.json()["error"] == "FileAlreadyExists"
    assert client.get("/files/notes.txt").content == b"first"


def test_replace_overwrites_an_existing_file(client):
    send_file(client, "POST", "notes.txt", b"first")
    assert send_file(client, "PUT", "notes.txt", b"second").status_code == 200
    assert client.get("/files/notes.txt").content == b"second"


def test_replace_of_a_missing_file_is_404(client):
    assert send_file(client, "PUT", "missing.txt", b"data").status_code == 404


def test_download_of_a_missing_file_is_404(client):
    response = client.get("/files/missing.txt")
    assert response.status_code == 404
    assert response.json()["error"] == "FileNotFound"


def test_delete_removes_the_file_and_deleting_again_is_404(client):
    send_file(client, "POST", "old.txt", b"bye")
    assert client.delete("/files/old.txt").status_code == 204
    assert client.get("/files/old.txt").status_code == 404
    assert client.delete("/files/old.txt").status_code == 404


def test_metadata_reports_size_and_a_type_picked_by_the_server(client):
    send_file(client, "POST", "docs/report.pdf", b"%PDF-1.7 fake")
    meta = client.get("/metadata/docs/report.pdf").json()
    assert meta["size"] == len(b"%PDF-1.7 fake")
    assert meta["content_type"] == "application/pdf"


def test_upload_over_the_limit_is_413(client):
    too_big = b"x" * (MAX_UPLOAD_BYTES + 1)
    assert send_file(client, "POST", "big.bin", too_big).status_code == 413
    assert client.get("/files/big.bin").status_code == 404


def test_invalid_key_is_400(client):
    response = send_file(client, "POST", "a//b.txt", b"data")
    assert response.status_code == 400
    assert response.json()["error"] == "InvalidInput"


def test_list_pages_through_files_with_a_cursor(client):
    for name in ("a.txt", "b.txt", "c.txt"):
        send_file(client, "POST", f"docs/{name}", b"x")
    send_file(client, "POST", "other/d.txt", b"x")

    first = client.get("/files", params={"prefix": "docs/", "limit": 2}).json()
    assert [f["key"] for f in first["files"]] == ["docs/a.txt", "docs/b.txt"]
    assert first["next_cursor"] is not None

    params = {"prefix": "docs/", "limit": 2, "cursor": first["next_cursor"]}
    second = client.get("/files", params=params).json()
    assert [f["key"] for f in second["files"]] == ["docs/c.txt"]
    assert second["next_cursor"] is None


def test_list_rejects_an_out_of_range_limit(client):
    assert client.get("/files", params={"limit": 0}).status_code == 422
    assert client.get("/files", params={"limit": 1001}).status_code == 422
