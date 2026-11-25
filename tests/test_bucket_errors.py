"""FIX-2: distinguish ambiguous HEAD misses from an unavailable bucket. Owner: Darsh."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, FileNotFound, ProviderError, ProviderUnavailable
from storage_service.main import create_app
from storage_service.service import FileService
from storage_service.wiring import build_service
from tests.conftest import load_provider_settings


def queue_head_miss(stubber: Stubber, code: str = "404") -> None:
    stubber.add_client_error(
        "head_object",
        service_error_code=code,
        http_status_code=404,
        expected_params={"Bucket": "test-bucket", "Key": "missing.txt"},
    )


@pytest.mark.parametrize("code", ["404", "NotFound"])
@pytest.mark.parametrize("bucket_code", ["404", "NotFound", "NoSuchBucket"])
def test_ambiguous_head_miss_with_missing_bucket_is_provider_error(stubbed_s3, code, bucket_code):
    storage, stubber = stubbed_s3
    queue_head_miss(stubber, code)
    stubber.add_client_error(
        "head_bucket",
        service_error_code=bucket_code,
        http_status_code=404,
        expected_params={"Bucket": "test-bucket"},
    )
    with pytest.raises(ProviderError) as caught:
        storage.stat("missing.txt")
    assert str(caught.value) == "the configured bucket does not exist or is not accessible"


@pytest.mark.parametrize("code", ["404", "NotFound"])
def test_ambiguous_head_miss_in_accessible_bucket_is_file_not_found(stubbed_s3, code):
    storage, stubber = stubbed_s3
    queue_head_miss(stubber, code)
    stubber.add_response("head_bucket", {}, {"Bucket": "test-bucket"})
    with pytest.raises(FileNotFound, match="no file named 'missing.txt'"):
        storage.stat("missing.txt")


def test_bucket_permission_denial_is_not_reported_as_missing_file(stubbed_s3):
    storage, stubber = stubbed_s3
    queue_head_miss(stubber)
    stubber.add_client_error(
        "head_bucket",
        service_error_code="403",
        http_status_code=403,
        expected_params={"Bucket": "test-bucket"},
    )
    with pytest.raises(AccessDenied) as caught:
        storage.stat("missing.txt")
    assert str(caught.value) == "the storage provider denied access to the configured bucket"
    assert caught.value.provider_code == "403"


def test_bucket_probe_connection_failure_is_provider_unavailable(stubbed_s3, monkeypatch):
    storage, stubber = stubbed_s3
    queue_head_miss(stubber)

    def unreachable(**kwargs):
        raise EndpointConnectionError(endpoint_url="https://s3.example.invalid")

    monkeypatch.setattr(storage._client, "head_bucket", unreachable)
    with pytest.raises(ProviderUnavailable, match="could not reach the storage provider") as raised:
        storage.stat("missing.txt")
    # An unstubbed call also ends as ProviderUnavailable (the Stubber's error is a
    # BotoCoreError), so check the cause to be sure this is the connection failure.
    assert isinstance(raised.value.__cause__, EndpointConnectionError)


def test_unambiguous_missing_key_does_not_probe_the_bucket(stubbed_s3):
    storage, stubber = stubbed_s3
    queue_head_miss(stubber, "NoSuchKey")
    with pytest.raises(FileNotFound):
        storage.stat("missing.txt")


def test_successful_metadata_does_not_probe_the_bucket(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_response(
        "head_object",
        {
            "ContentLength": 5,
            "ContentType": "text/plain",
            "ETag": '"opaque"',
            "LastModified": datetime(2026, 10, 14, tzinfo=UTC),
        },
        {"Bucket": "test-bucket", "Key": "hello.txt"},
    )
    assert storage.stat("hello.txt").etag == "opaque"


def test_object_permission_denial_does_not_probe_the_bucket(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "head_object",
        service_error_code="AccessDenied",
        http_status_code=403,
        expected_params={"Bucket": "test-bucket", "Key": "hello.txt"},
    )
    with pytest.raises(AccessDenied):
        storage.stat("hello.txt")


# Create and Replace name their file in the form, not in the query string.
UPLOAD_OF_MISSING: dict[str, Any] = {
    "data": {"path": "missing.txt"},
    "files": {"file": ("upload", b"hello")},
}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/files/metadata?path=missing.txt"),
        ("DELETE", "/files?path=missing.txt"),
        ("PUT", "/files"),
        ("POST", "/files"),
    ],
)
def test_missing_bucket_returns_502_before_any_write(stubbed_s3, method, path):
    storage, stubber = stubbed_s3
    queue_head_miss(stubber)
    stubber.add_client_error(
        "head_bucket",
        service_error_code="404",
        http_status_code=404,
        expected_params={"Bucket": "test-bucket"},
    )
    # Only HEAD calls are queued. An attempted put/delete would fail the test.
    upload = UPLOAD_OF_MISSING if method in ("PUT", "POST") else {}
    with TestClient(create_app(FileService(storage, max_upload_bytes=1024))) as client:
        response = client.request(method, path, **upload)
    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "provider_error",
            "message": "the configured bucket does not exist or is not accessible",
        }
    }


@pytest.mark.provider
def test_nonexistent_real_bucket_is_a_provider_error():
    settings = load_provider_settings()
    assert settings.s3 is not None
    # This name is never created. No test operation can write to the real bucket.
    missing_bucket = "ospsd-missing-" + uuid.uuid4().hex
    bad_settings = replace(settings, s3=replace(settings.s3, bucket=missing_bucket))
    with TestClient(create_app(build_service(bad_settings))) as client:
        for method, path in (
            ("GET", "/files/metadata?path=missing.txt"),
            ("DELETE", "/files?path=missing.txt"),
            ("PUT", "/files"),
        ):
            upload = UPLOAD_OF_MISSING if method == "PUT" else {}
            response = client.request(method, path, **upload)
            assert response.status_code == 502
            assert response.json() == {
                "error": {
                    "code": "provider_error",
                    "message": "the configured bucket does not exist or is not accessible",
                }
            }


@pytest.mark.provider
def test_missing_file_in_real_bucket_remains_404(provider_client, provider_prefix):
    key = provider_prefix + "missing.txt"
    response = provider_client.get("/files/metadata", params={"path": key})
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": f"no file named {key!r}"}}
