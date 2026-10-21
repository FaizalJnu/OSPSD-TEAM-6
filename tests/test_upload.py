"""Create and replace: POST and PUT /files/{key}. Owner: Debasmith Mandal."""

import io
import os
from datetime import UTC, datetime, timedelta

import pytest

from storage_service.errors import ProviderError
from tests.conftest import MAX_UPLOAD_BYTES, send_file


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


def test_upload_over_the_limit_is_413(client):
    too_big = b"x" * (MAX_UPLOAD_BYTES + 1)
    assert send_file(client, "POST", "big.bin", too_big).status_code == 413
    assert client.get("/files/big.bin").status_code == 404


def test_invalid_key_is_400(client):
    response = send_file(client, "POST", "a//b.txt", b"data")
    assert response.status_code == 400
    assert response.json()["error"] == "InvalidInput"
    assert client.get("/files").json()["files"] == []  # nothing was stored


# --- Level 1: the full contract over HTTP (in-memory storage) ---


def test_create_returns_every_field_and_metadata_agrees(client):
    data = b"hello, storage"
    created = send_file(client, "POST", "photos/2026/cat.png", data)

    assert created.status_code == 201
    info = created.json()
    assert set(info) == {"key", "size", "content_type", "etag", "last_modified"}
    assert info["key"] == "photos/2026/cat.png"
    assert isinstance(info["size"], int)
    assert info["size"] == len(data)
    assert info["content_type"] == "image/png"
    assert info["etag"]
    assert '"' not in info["etag"]
    assert info["last_modified"].endswith("Z")
    assert datetime.fromisoformat(info["last_modified"]).utcoffset() == timedelta(0)
    # A follow-up read sees exactly what the write reported.
    assert client.get("/metadata/photos/2026/cat.png").json() == info


def test_upload_of_exactly_the_limit_is_accepted(client):
    response = send_file(client, "POST", "edge.bin", b"x" * MAX_UPLOAD_BYTES)
    assert response.status_code == 201
    assert response.json()["size"] == MAX_UPLOAD_BYTES


def test_empty_file_is_allowed(client):
    created = send_file(client, "POST", "empty.txt", b"")
    assert created.status_code == 201
    assert created.json()["size"] == 0
    assert client.get("/files/empty.txt").content == b""


def test_replace_over_the_limit_keeps_the_old_contents(client):
    send_file(client, "POST", "notes.txt", b"first")
    before = client.get("/metadata/notes.txt").json()

    too_big = send_file(client, "PUT", "notes.txt", b"x" * (MAX_UPLOAD_BYTES + 1))

    assert too_big.status_code == 413
    assert client.get("/files/notes.txt").content == b"first"
    assert client.get("/metadata/notes.txt").json() == before


def test_client_content_type_is_ignored(client):
    response = client.post(
        "/files/a.png", files={"file": ("a.png", b"not really a png", "text/html")}
    )
    assert response.status_code == 201
    assert response.json()["content_type"] == "image/png"
    assert client.get("/files/a.png").headers["content-type"] == "image/png"


def test_replace_changes_etag_and_size(client):
    first = send_file(client, "POST", "notes.txt", b"first").json()

    replaced = send_file(client, "PUT", "notes.txt", b"second, longer")

    assert replaced.status_code == 200
    info = replaced.json()
    assert info["size"] == len(b"second, longer")
    assert info["etag"] != first["etag"]
    assert client.get("/metadata/notes.txt").json() == info


# --- Level 3: how S3Storage.put translates provider replies (no network) ---


def test_s3_put_returns_the_info_from_its_follow_up_stat(stubbed_s3):
    storage, stubber = stubbed_s3
    # put_object's parameters are not pinned: boto3 adds a checksum parameter that FIX-1 changes.
    stubber.add_response("put_object", {"ETag": '"5d41402abc4b2a76b9719d911017c592"'})
    stubber.add_response(
        "head_object",
        {
            "ContentLength": 5,
            "ContentType": "text/plain",
            "ETag": '"5d41402abc4b2a76b9719d911017c592"',
            "LastModified": datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
        },
        {"Bucket": "test-bucket", "Key": "notes.txt"},
    )

    info = storage.put("notes.txt", io.BytesIO(b"hello"), "text/plain")

    assert info.key == "notes.txt"
    assert info.size == 5
    assert info.content_type == "text/plain"
    assert info.etag == "5d41402abc4b2a76b9719d911017c592"  # quotes stripped
    assert info.last_modified == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_s3_put_turns_a_provider_rejection_into_provider_error(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)

    with pytest.raises(ProviderError):
        storage.put("notes.txt", io.BytesIO(b"hello"), "text/plain")


# --- Level 2: against the real bucket (opt-in: uv run --env-file .env pytest -m provider) ---


@pytest.mark.provider
def test_create_and_replace_against_the_real_provider(provider_client, provider_prefix):
    key = f"{provider_prefix}notes.txt"

    created = send_file(provider_client, "POST", key, b"first")
    assert created.status_code == 201
    assert created.json()["size"] == 5

    replaced = send_file(provider_client, "PUT", key, b"second, longer")
    assert replaced.status_code == 200
    assert replaced.json()["size"] == len(b"second, longer")
    assert replaced.json()["etag"] != created.json()["etag"]

    assert provider_client.get(f"/files/{key}").content == b"second, longer"
    assert provider_client.get(f"/metadata/{key}").json() == replaced.json()


@pytest.mark.provider
def test_multipart_upload_round_trips_against_the_real_provider(provider_client, provider_prefix):
    key = f"{provider_prefix}big.bin"
    data = os.urandom(9 * 1024 * 1024)  # over boto3's 8 MB threshold: takes the multipart path

    created = send_file(provider_client, "POST", key, data)

    assert created.status_code == 201
    assert created.json()["size"] == len(data)
    assert provider_client.get(f"/files/{key}").content == data
