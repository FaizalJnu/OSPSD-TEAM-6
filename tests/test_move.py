"""Move: PATCH /files?path= with {"new_path": ...}. Owner: Vikram Markali."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, FileNotFound, ProviderError, ProviderUnavailable
from storage_service.main import create_app
from storage_service.models import FileInfo
from storage_service.service import FileService
from tests.conftest import MAX_UPLOAD_BYTES, send_file

UNCONFIRMED = (
    "the file was copied to '/archive/a.txt', but deleting the original at "
    "'/docs/a.txt' could not be confirmed"
)


def move(client: TestClient, path: str, new_path: str):
    return client.patch("/files", params={"path": path}, json={"new_path": new_path})


def metadata_status(client: TestClient, path: str) -> int:
    return client.get("/files/metadata", params={"path": path}).status_code


# --- HTTP behavior over FakeStorage ---


def test_move_copies_then_deletes_and_returns_the_file_at_its_new_path(fake, fake_client):
    created = send_file(fake_client, "POST", "docs/a.txt", b"hello").json()
    fake.calls.clear()

    response = move(fake_client, "docs/a.txt", "/archive/a.txt")

    assert response.status_code == 200
    moved = response.json()
    assert moved["id"] is None
    assert moved["name"] == "a.txt"
    assert moved["path"] == "/archive/a.txt"
    assert moved["size"] == 5
    assert moved["etag"] == created["etag"]  # the same contents
    assert moved["content_type"] == "text/plain"
    assert metadata_status(fake_client, "docs/a.txt") == 404
    assert metadata_status(fake_client, "archive/a.txt") == 200
    assert fake.calls[:5] == [
        ("stat", "docs/a.txt"),  # the source exists
        ("stat", "archive/a.txt"),  # no file at the destination
        ("list_files", "archive/a.txt/"),  # and no folder there
        ("copy", "docs/a.txt"),
        ("delete", "docs/a.txt"),
    ]


def test_move_of_a_missing_file_is_404_and_copies_nothing(fake, fake_client):
    response = move(fake_client, "docs/a.txt", "archive/a.txt")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "no file at '/docs/a.txt'"}
    }
    assert ("copy", "docs/a.txt") not in fake.calls


@pytest.mark.parametrize(
    ("existing", "message"),
    [
        ("archive/a.txt", "a file already exists at '/archive/a.txt'"),
        ("archive/a.txt/inside.txt", "a folder already exists at '/archive/a.txt'"),
    ],
    ids=["file", "folder"],
)
def test_move_onto_something_that_exists_is_409_and_changes_nothing(
    fake, fake_client, existing, message
):
    send_file(fake_client, "POST", "docs/a.txt", b"hello")
    send_file(fake_client, "POST", existing, b"keep me")
    fake.calls.clear()

    response = move(fake_client, "docs/a.txt", "archive/a.txt")

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "conflict", "message": message}}
    assert [method for method, _ in fake.calls if method in ("copy", "delete")] == []
    assert metadata_status(fake_client, "docs/a.txt") == 200
    assert metadata_status(fake_client, existing) == 200


@pytest.mark.parametrize(
    ("new_path", "message"),
    [
        ("/docs/a.txt", "'/docs/a.txt' is already the file's path"),
        ("docs/A.txt", "a move cannot change only the letter case of a path"),
    ],
    ids=["same path", "case only"],
)
def test_move_that_changes_nothing_real_is_422_and_never_calls_storage(
    fake, fake_client, new_path, message
):
    response = move(fake_client, "docs/a.txt", new_path)

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_operation", "message": message}}
    assert fake.calls == []


def test_move_of_a_folder_is_422_and_copies_nothing(fake, fake_client):
    send_file(fake_client, "POST", "docs/inside.txt", b"x")
    fake.calls.clear()

    response = move(fake_client, "docs", "archive")

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_operation",
            "message": "'/docs' is a folder; only files can be moved",
        }
    }
    assert fake.calls == [("stat", "docs"), ("list_files", "docs/")]


@pytest.mark.parametrize(
    ("request_kwargs", "message"),
    [
        ({}, "body: Field required"),
        (
            {"content": b"{not json", "headers": {"content-type": "application/json"}},
            "body: JSON decode error",
        ),
        ({"json": {}}, "new_path: Field required"),
        ({"json": {"new_path": "a//b.txt"}}, None),
        ({"json": {"new_path": "a.txt"}, "params": {}}, "path: Field required"),
        ({"json": {"new_path": "a.txt"}, "params": {"path": "a/../b"}}, None),
    ],
    ids=["no body", "not json", "no new_path", "bad new_path", "no path", "bad path"],
)
def test_move_with_a_bad_request_is_400_and_never_calls_storage(
    fake, fake_client, request_kwargs, message
):
    kwargs = {"params": {"path": "docs/a.txt"}, **request_kwargs}

    response = fake_client.patch("/files", **kwargs)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    if message is not None:
        assert response.json()["error"]["message"] == message
    assert fake.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        ProviderError("the storage provider rejected the request"),
        AccessDenied("the storage provider denied this service access"),
        ProviderUnavailable("could not reach the storage provider"),
    ],
    ids=["502", "403", "503"],
)
def test_move_whose_delete_fails_after_the_copy_is_502_whatever_the_cause(
    fake, fake_client, failure
):
    send_file(fake_client, "POST", "docs/a.txt", b"hello")
    fake.fail("delete", failure)

    response = move(fake_client, "docs/a.txt", "archive/a.txt")

    assert response.status_code == 502
    assert response.json() == {"error": {"code": "provider_error", "message": UNCONFIRMED}}
    # The copy was made, and the original was not deleted: the file is at both paths.
    assert metadata_status(fake_client, "archive/a.txt") == 200
    assert metadata_status(fake_client, "docs/a.txt") == 200


def test_move_whose_copy_fails_leaves_the_original_alone(fake, fake_client):
    send_file(fake_client, "POST", "docs/a.txt", b"hello")
    fake.fail("copy", ProviderError("the storage provider rejected the request"))

    response = move(fake_client, "docs/a.txt", "archive/a.txt")

    assert response.status_code == 502
    assert ("delete", "docs/a.txt") not in fake.calls
    assert metadata_status(fake_client, "docs/a.txt") == 200


def test_move_returns_503_when_the_source_check_cannot_reach_the_provider(fake, fake_client):
    fake.fail("stat", ProviderUnavailable("could not reach the storage provider"))

    response = move(fake_client, "docs/a.txt", "archive/a.txt")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "provider_unavailable", "message": "could not reach the storage provider"}
    }
    assert fake.calls == [("stat", "docs/a.txt")]


# --- Level 3: how S3Storage.copy translates provider replies (no network) ---

HEAD_RESPONSE = {
    "ContentLength": 5,
    "ContentType": "text/plain",
    "ETag": '"abc123"',
    "LastModified": datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
}


def test_s3_copy_sends_copy_object_and_returns_the_copys_info(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_response(
        "copy_object",
        {"CopyObjectResult": {"ETag": '"abc123"'}},
        expected_params={
            "Bucket": "test-bucket",
            "Key": "archive/a.txt",
            "CopySource": {"Bucket": "test-bucket", "Key": "docs/a.txt"},
        },
    )
    stubber.add_response(
        "head_object",
        HEAD_RESPONSE,
        expected_params={"Bucket": "test-bucket", "Key": "archive/a.txt"},
    )

    info = storage.copy("docs/a.txt", "archive/a.txt")

    assert info == FileInfo(
        key="archive/a.txt",
        size=5,
        content_type="text/plain",
        etag="abc123",
        last_modified=datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
    )


def test_s3_copy_of_a_missing_source_raises_file_not_found(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error("copy_object", service_error_code="NoSuchKey", http_status_code=404)

    with pytest.raises(FileNotFound, match="no file named 'docs/a.txt'"):
        storage.copy("docs/a.txt", "archive/a.txt")


def test_move_over_s3_is_502_when_delete_object_fails_after_copy_object(stubbed_s3):
    storage, stubber = stubbed_s3
    bucket = {"Bucket": "test-bucket"}
    stubber.add_response("head_object", HEAD_RESPONSE, {**bucket, "Key": "docs/a.txt"})
    # Nothing at the destination: HEAD's 404 is checked against the bucket (FIX-2).
    stubber.add_client_error("head_object", "404", http_status_code=404)
    stubber.add_response("head_bucket", {}, bucket)
    stubber.add_response(
        "list_objects_v2", {"KeyCount": 0}, {**bucket, "Prefix": "archive/a.txt/", "MaxKeys": 1}
    )
    stubber.add_response(
        "copy_object",
        {"CopyObjectResult": {"ETag": '"abc123"'}},
        {**bucket, "Key": "archive/a.txt", "CopySource": {**bucket, "Key": "docs/a.txt"}},
    )
    stubber.add_response("head_object", HEAD_RESPONSE, {**bucket, "Key": "archive/a.txt"})
    stubber.add_client_error(
        "delete_object",
        service_error_code="AccessDenied",
        http_status_code=403,
        expected_params={**bucket, "Key": "docs/a.txt"},
    )
    client = TestClient(create_app(FileService(storage, max_upload_bytes=MAX_UPLOAD_BYTES)))

    response = move(client, "docs/a.txt", "archive/a.txt")

    # A refused delete would be 403 on its own; after a successful copy it is a partial move.
    assert response.status_code == 502
    assert response.json() == {"error": {"code": "provider_error", "message": UNCONFIRMED}}


# --- Level 2: against a real bucket ---


@pytest.mark.provider
def test_move_against_the_real_provider(provider_client, provider_prefix):
    source = provider_prefix + "docs/a.txt"
    dest = provider_prefix + "archive/a.txt"
    created = send_file(provider_client, "POST", source, b"moved on a real bucket").json()

    response = move(provider_client, source, dest)

    assert response.status_code == 200
    moved = response.json()
    assert moved["path"] == "/" + dest
    assert moved["id"] is None
    assert moved["size"] == created["size"]
    assert moved["etag"] == created["etag"]  # CopyObject keeps a single-part ETag
    assert moved["content_type"] == "text/plain"
    assert metadata_status(provider_client, source) == 404
    assert metadata_status(provider_client, dest) == 200
