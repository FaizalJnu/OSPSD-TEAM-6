"""Metadata: GET /files/metadata?path={key}. Owner: Darsh Shani."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.parse import quote

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, FileNotFound, ProviderError, ProviderUnavailable
from storage_service.main import create_app
from storage_service.models import FileInfo
from storage_service.service import FileService
from tests.conftest import send_file
from tests.fakes import FakeStorage


def test_metadata_reports_size_and_a_type_picked_by_the_server(client):
    key = "docs/report.pdf"
    data = b"%PDF-1.7 fake"
    created = send_file(client, "POST", key, data)
    assert created.status_code == 201

    response = client.get("/files/metadata", params={"path": key})
    assert response.status_code == 200
    meta = response.json()
    assert set(meta) == {
        "id",
        "name",
        "path",
        "size",
        "content_type",
        "etag",
        "modified_at",
        "type",
    }
    assert meta["path"] == "/" + key
    assert meta["id"] is None
    assert meta["name"] == key.rsplit("/", 1)[-1]
    assert type(meta["size"]) is int
    assert meta["size"] == len(data)
    assert meta["content_type"] == "application/pdf"
    assert isinstance(meta["etag"], str) and meta["etag"]
    assert '"' not in meta["etag"]
    assert datetime.fromisoformat(meta["modified_at"]).utcoffset() == timedelta(0)
    assert meta["etag"] == created.json()["etag"]
    assert meta["size"] == created.json()["size"]

    # Reading metadata changes neither the content nor the metadata.
    assert client.get("/files/download", params={"path": key}).content == data
    assert client.get("/files/metadata", params={"path": key}).json() == meta


def test_metadata_and_listing_report_the_same_file(client):
    key = "docs/report.pdf"
    assert send_file(client, "POST", key, b"report").status_code == 201
    metadata = client.get("/files/metadata", params={"path": key})
    listing = client.get("/files", params={"prefix": "docs/"})
    assert metadata.status_code == listing.status_code == 200
    listed = listing.json()["files"]
    assert len(listed) == 1
    assert metadata.json()["path"] == "/" + listed[0]["key"]
    assert metadata.json()["modified_at"] == listed[0]["last_modified"]
    for field in ("size", "etag"):
        assert listed[0][field] == metadata.json()[field]
    assert listed[0]["content_type"] is None


def test_metadata_missing_file_returns_the_public_error(client):
    response = client.get("/files/metadata?path=missing.txt")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "no file named 'missing.txt'"}
    }


def test_metadata_accepts_a_unicode_key_at_the_utf8_byte_limit(client):
    key = "é" * 510 + ".tx"  # 1024 bytes including the canonical leading slash.
    path = quote(key, safe="/")
    assert send_file(client, "POST", path, b"hello").status_code == 201
    response = client.get(f"/files/metadata?path={path}")
    assert response.status_code == 200
    assert response.json()["path"] == "/" + key


@pytest.mark.parametrize(
    "key", ["", "docs//report.txt", "docs/report.txt/", "docs/\x00report.txt", "é" * 513]
)
def test_metadata_rejects_invalid_keys_before_calling_storage(key):
    storage = FakeStorage()
    with TestClient(create_app(FileService(storage, max_upload_bytes=1024))) as client:
        response = client.get(f"/files/metadata?path={quote(key, safe='/')}")
    assert response.status_code == 400
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["error"]["message"]
    assert storage.calls == []


def test_metadata_uses_the_injected_storage_contract():
    storage = FakeStorage()
    info = storage.put("docs/report.pdf", BytesIO(b"%PDF-1.7 pdf"), "application/pdf")
    storage.calls.clear()  # Only the HTTP request's calls are checked below.
    with TestClient(create_app(FileService(storage, max_upload_bytes=1024))) as client:
        response = client.get("/files/metadata?path=docs/report.pdf")
    assert response.status_code == 200
    assert response.json() == {
        "id": None,
        "name": "report.pdf",
        "path": "/docs/report.pdf",
        "type": None,
        "size": 12,
        "content_type": "application/pdf",
        "etag": info.etag,
        "modified_at": info.last_modified.isoformat().replace("+00:00", "Z"),
    }
    assert storage.calls == [("stat", "docs/report.pdf")]


def test_metadata_translates_injected_provider_rejection_to_public_error():
    storage = FakeStorage()
    error = ProviderError("storage provider rejected the request")
    storage.fail("stat", error)
    with TestClient(create_app(FileService(storage, max_upload_bytes=1024))) as client:
        response = client.get("/files/metadata?path=report.pdf")
    assert response.status_code == 502
    assert response.json() == {"error": {"code": error.code, "message": str(error)}}
    assert storage.calls == [("stat", "report.pdf")]


@pytest.mark.parametrize("content_type", ["application/pdf", None])
def test_s3_metadata_translates_head_response_to_file_info(stubbed_s3, content_type):
    storage, stubber = stubbed_s3
    modified = datetime(2026, 10, 14, 12, 0, 0, 123456, tzinfo=UTC)
    response = {"ContentLength": 12, "ETag": '"opaque-provider-tag-2"', "LastModified": modified}
    if content_type is not None:
        response["ContentType"] = content_type
    stubber.add_response(
        "head_object", response, {"Bucket": "test-bucket", "Key": "docs/report.pdf"}
    )
    assert storage.stat("docs/report.pdf") == FileInfo(
        key="docs/report.pdf",
        size=12,
        content_type=content_type,
        etag="opaque-provider-tag-2",
        last_modified=modified,
    )


def test_s3_metadata_translates_missing_file(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "head_object",
        service_error_code="NoSuchKey",
        http_status_code=404,
        expected_params={"Bucket": "test-bucket", "Key": "missing.txt"},
    )
    with pytest.raises(FileNotFound, match="no file named 'missing.txt'"):
        storage.stat("missing.txt")


@pytest.mark.parametrize(
    ("code", "status", "error"),
    [("AccessDenied", 403, AccessDenied), ("NoSuchBucket", 404, ProviderError)],
)
def test_s3_metadata_translates_provider_rejection(stubbed_s3, code, status, error):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "head_object",
        service_error_code=code,
        http_status_code=status,
        expected_params={"Bucket": "test-bucket", "Key": "report.pdf"},
    )
    with pytest.raises(error):
        storage.stat("report.pdf")


def test_s3_metadata_translates_connection_failure(stubbed_s3, monkeypatch):
    storage, _stubber = stubbed_s3

    def unreachable(**kwargs):
        raise EndpointConnectionError(endpoint_url="https://s3.example.invalid")

    monkeypatch.setattr(storage._client, "head_object", unreachable)
    with pytest.raises(ProviderUnavailable, match="could not reach the storage provider") as raised:
        storage.stat("report.pdf")
    # An unstubbed call also ends as ProviderUnavailable (the Stubber's error is a
    # BotoCoreError), so check the cause to be sure this is the connection failure.
    assert isinstance(raised.value.__cause__, EndpointConnectionError)


def test_metadata_openapi_documents_the_response_and_expected_errors(client):
    schema = client.get("/openapi.json").json()
    responses = schema["paths"]["/files/metadata"]["get"]["responses"]
    assert {"200", "400", "404", "502", "503"} <= responses.keys()
    model = schema["components"]["schemas"]["CommonFileInfo"]
    assert set(model["required"]) == {"id", "name", "path", "size", "etag", "modified_at", "type"}


@pytest.mark.provider
def test_metadata_reports_real_provider_values_and_matches_listing(
    provider_client, provider_prefix
):
    key = provider_prefix + "report.pdf"
    data = b"%PDF-1.7 metadata provider verification"
    created = send_file(provider_client, "POST", key, data)
    assert created.status_code == 201
    response = provider_client.get("/files/metadata", params={"path": key})
    assert response.status_code == 200
    meta = response.json()
    assert set(meta) == {
        "id",
        "name",
        "path",
        "size",
        "content_type",
        "etag",
        "modified_at",
        "type",
    }
    assert meta["path"] == "/" + key
    assert meta["id"] is None
    assert meta["name"] == key.rsplit("/", 1)[-1]
    assert type(meta["size"]) is int and meta["size"] == len(data)
    assert meta["content_type"] == "application/pdf"
    assert isinstance(meta["etag"], str) and meta["etag"] and '"' not in meta["etag"]
    modified = datetime.fromisoformat(meta["modified_at"])
    assert modified.utcoffset() == timedelta(0)
    assert meta["etag"] == created.json()["etag"]
    assert meta["size"] == created.json()["size"]
    assert provider_client.get("/files/download", params={"path": key}).content == data

    listing = provider_client.get("/files", params={"prefix": provider_prefix})
    assert listing.status_code == 200
    files = listing.json()["files"]
    assert len(files) == 1
    assert meta["path"] == "/" + files[0]["key"]
    for field in ("size", "etag"):
        assert files[0][field] == meta[field]
    listed_modified = datetime.fromisoformat(files[0]["last_modified"])
    assert listed_modified.utcoffset() == timedelta(0)
    # HEAD and LIST may encode fractional seconds with different precision.
    assert abs((listed_modified - modified).total_seconds()) < 1
    assert files[0]["content_type"] is None
