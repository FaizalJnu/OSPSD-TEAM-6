"""List: GET /files. Owner: Prateek Saxena.

The traversal tests follow the collection example in docs/testing.txt. Expected keys
are written out by hand, never computed with the code under test.
"""

import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from storage_service.errors import (
    AccessDenied,
    FileNotFound,
    InvalidInput,
    ProviderError,
    ProviderUnavailable,
)
from storage_service.main import create_app
from storage_service.models import FileInfo, FilePage, FolderEntry
from storage_service.service import FileService
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage
from tests.conftest import MAX_UPLOAD_BYTES, send_file
from tests.fakes import FakeStorage


def list_folder(client: TestClient, path: str | None = None) -> Any:
    """GET /files, with ``?path=`` only when a path is given."""
    params = {} if path is None else {"path": path}
    return client.get("/files", params=params)


def paths(response: Any) -> list[str]:
    assert response.status_code == 200
    return [entry["path"] for entry in response.json()]


def test_list_returns_direct_files_and_folders_sorted_by_path(client):
    for key in ("docs/b.txt", "docs/sub/x.txt", "docs/sub/deep/y.txt", "docs/a.txt", "top.txt"):
        send_file(client, "POST", key, b"x")
    send_file(client, "POST", "docs2/c.txt", b"x")

    assert paths(list_folder(client, "/docs")) == [
        "/docs/a.txt",
        "/docs/b.txt",
        "/docs/sub",
    ]


def test_list_file_entry_is_the_shared_file_info_metadata_returns(client):
    send_file(client, "POST", "docs/report.pdf", b"report")
    metadata = client.get("/files/metadata", params={"path": "/docs/report.pdf"}).json()

    [entry] = list_folder(client, "/docs").json()

    # Listings cannot know the content type: the S3 list call does not return it.
    assert entry == {**metadata, "type": "file", "content_type": None}


def test_list_folder_entry_has_only_a_name_path_and_type(client):
    send_file(client, "POST", "docs/sub/x.txt", b"x")

    assert list_folder(client, "/docs").json() == [
        {
            "id": None,
            "name": "sub",
            "path": "/docs/sub",
            "size": None,
            "modified_at": None,
            "etag": None,
            "type": "folder",
            "content_type": None,
        }
    ]


@pytest.mark.parametrize("path", [None, "/", ""])
def test_list_without_a_folder_lists_the_root(client, path):
    for key in ("top.txt", "docs/a.txt"):
        send_file(client, "POST", key, b"x")

    assert paths(list_folder(client, path)) == ["/docs", "/top.txt"]


def test_list_of_the_empty_root_is_an_empty_array(client):
    response = list_folder(client)

    assert response.status_code == 200
    assert response.json() == []


def test_list_accepts_a_folder_path_without_the_leading_slash(client):
    send_file(client, "POST", "docs/a.txt", b"x")

    assert paths(list_folder(client, "docs")) == ["/docs/a.txt"]


def test_list_of_a_missing_folder_is_404(client):
    send_file(client, "POST", "docs/a.txt", b"x")

    response = list_folder(client, "/other")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_of_a_file_path_is_404(client):
    # A file is not a folder: nothing is under "docs/a.txt/".
    send_file(client, "POST", "docs/a.txt", b"x")

    assert list_folder(client, "/docs/a.txt").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/docs/",
        "/docs//a",
        "/docs/../a",
        "/a/./b",
        pytest.param("/" + "a" * 1024, id="1025-bytes"),
    ],
)
def test_list_with_a_bad_path_is_400_without_calling_storage(fake, fake_client, path):
    response = list_folder(fake_client, path)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert fake.calls == []


def test_list_returns_a_folder_of_more_than_one_storage_page_in_one_array():
    service = FileService(InMemoryStorage(), max_upload_bytes=MAX_UPLOAD_BYTES)
    for i in range(1001):
        service.create(f"many/{i:04}.txt", io.BytesIO(b""), 0)
    client = TestClient(create_app(service))

    listed = paths(list_folder(client, "/many"))

    assert listed == [f"/many/{i:04}.txt" for i in range(1001)]


# Controlled storage (Level 4): the app as tests build it, over a StorageClient whose
# answers each test sets. No network and no credentials.

MODIFIED = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def controlled_storage():
    """A stand-in with StorageClient's methods and signatures, and no behavior of its own."""
    return create_autospec(StorageClient, instance=True, spec_set=True)


@pytest.fixture
def controlled_client(controlled_storage):
    service = FileService(controlled_storage, max_upload_bytes=MAX_UPLOAD_BYTES)
    return TestClient(create_app(service))


def test_list_turns_the_storage_page_into_shared_entries(controlled_storage, controlled_client):
    controlled_storage.list_files.return_value = FilePage(
        files=[
            FileInfo(
                key="docs/a.txt",
                size=5,
                content_type=None,
                etag="opaque-tag-1",
                last_modified=MODIFIED,
            )
        ],
        next_cursor=None,
        folders=["docs/sub/"],
    )

    response = list_folder(controlled_client, "/docs")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": None,
            "name": "a.txt",
            "path": "/docs/a.txt",
            "size": 5,
            "modified_at": "2026-10-14T12:00:00Z",
            "etag": "opaque-tag-1",
            "type": "file",
            "content_type": None,
        },
        {
            "id": None,
            "name": "sub",
            "path": "/docs/sub",
            "size": None,
            "modified_at": None,
            "etag": None,
            "type": "folder",
            "content_type": None,
        },
    ]
    # One page from storage: the folder's prefix, the largest page, and "/" as delimiter.
    assert controlled_storage.mock_calls == [call.list_files("docs/", 1000, None, delimiter="/")]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (AccessDenied("the storage provider denied access"), 403),
        (ProviderError("the storage provider rejected the request"), 502),
        (ProviderUnavailable("could not reach the storage provider"), 503),
    ],
)
def test_list_reports_storage_failures_in_our_error_format(
    controlled_storage, controlled_client, error, status
):
    controlled_storage.list_files.side_effect = error

    response = list_folder(controlled_client, "/docs")

    assert response.status_code == status
    assert response.json() == {"error": {"code": error.code, "message": str(error)}}


# Translation (Level 3): S3Storage over a stubbed boto3 client. No network.

LIST_PARAMS = {"Bucket": "test-bucket", "Prefix": "docs/", "MaxKeys": 2}


def test_s3_list_translates_a_provider_page_into_a_file_page(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_response(
        "list_objects_v2",
        {
            "Name": "test-bucket",
            "Prefix": "docs/",
            "KeyCount": 2,
            "MaxKeys": 2,
            "IsTruncated": True,
            "NextContinuationToken": "token-2",
            "Contents": [
                {
                    "Key": "docs/a.txt",
                    "Size": 5,
                    "ETag": '"0cc175b9c0f1b6a831c399e269772661"',
                    "LastModified": MODIFIED,
                    "StorageClass": "STANDARD",
                },
                {
                    "Key": "docs/b.bin",
                    "Size": 0,
                    "ETag": '"d41d8cd98f00b204e9800998ecf8427e-2"',
                    "LastModified": MODIFIED,
                    "StorageClass": "STANDARD",
                },
            ],
        },
        LIST_PARAMS,
    )

    page = storage.list_files("docs/", 2, None)

    # The cursor is our own string wrapping the provider's token; the next test
    # shows the token goes back to the provider unchanged.
    assert page.next_cursor is not None
    assert page.next_cursor != "token-2"
    # Quotes stripped, no content type, and the provider-only fields (bucket name,
    # counts, storage class) left behind.
    assert replace(page, next_cursor=None) == FilePage(
        files=[
            FileInfo(
                key="docs/a.txt",
                size=5,
                content_type=None,
                etag="0cc175b9c0f1b6a831c399e269772661",
                last_modified=MODIFIED,
            ),
            FileInfo(
                key="docs/b.bin",
                size=0,
                content_type=None,
                etag="d41d8cd98f00b204e9800998ecf8427e-2",
                last_modified=MODIFIED,
            ),
        ],
        next_cursor=None,
    )


def first_page_cursor(stubbed_s3, token: str = "token-2") -> str:
    """The cursor S3Storage returns for a first page whose provider token is ``token``."""
    storage, stubber = stubbed_s3
    stubber.add_response(
        "list_objects_v2",
        {"IsTruncated": True, "NextContinuationToken": token, "Contents": []},
        LIST_PARAMS,
    )
    cursor: str | None = storage.list_files("docs/", 2, None).next_cursor
    assert cursor is not None
    return cursor


def test_s3_list_sends_the_cursor_as_the_continuation_token(stubbed_s3):
    storage, stubber = stubbed_s3
    cursor = first_page_cursor(stubbed_s3)
    stubber.add_response(
        "list_objects_v2",
        {
            "IsTruncated": False,
            "Contents": [
                {"Key": "docs/c.txt", "Size": 1, "ETag": '"etag-c"', "LastModified": MODIFIED}
            ],
        },
        {**LIST_PARAMS, "ContinuationToken": "token-2"},
    )

    page = storage.list_files("docs/", 2, cursor)

    assert [info.key for info in page.files] == ["docs/c.txt"]
    assert page.next_cursor is None


def test_s3_list_with_no_matches_is_an_empty_page(stubbed_s3):
    storage, stubber = stubbed_s3
    # S3 leaves Contents out entirely when nothing matches.
    stubber.add_response("list_objects_v2", {"IsTruncated": False, "KeyCount": 0}, LIST_PARAMS)

    assert storage.list_files("docs/", 2, None) == FilePage(files=[], next_cursor=None)


def test_s3_list_returns_keys_decoded_when_the_provider_sends_them_url_encoded(stubbed_s3):
    storage, stubber = stubbed_s3
    # boto3 asks for EncodingType=url and decodes the keys itself, so S3Storage
    # and its callers only ever see real keys.
    stubber.add_response(
        "list_objects_v2",
        {
            "EncodingType": "url",
            "IsTruncated": False,
            "Contents": [
                {
                    "Key": "docs/r%C3%A9sum%C3%A9.pdf",
                    "Size": 1,
                    "ETag": '"etag"',
                    "LastModified": MODIFIED,
                }
            ],
        },
        LIST_PARAMS,
    )

    assert [info.key for info in storage.list_files("docs/", 2, None).files] == ["docs/résumé.pdf"]


@pytest.mark.parametrize(
    ("code", "status", "error"),
    [("AccessDenied", 403, AccessDenied), ("NoSuchBucket", 404, ProviderError)],
)
def test_s3_list_rejected_by_the_provider_raises_our_error(stubbed_s3, code, status, error):
    storage, stubber = stubbed_s3
    # List names no file, so even a 404 is a provider problem, never FileNotFound.
    stubber.add_client_error(
        "list_objects_v2",
        service_error_code=code,
        http_status_code=status,
        expected_params=LIST_PARAMS,
    )

    with pytest.raises(error) as raised:
        storage.list_files("docs/", 2, None)
    # The provider's code is kept for the logs, not put in the message.
    assert raised.value.provider_code == code
    assert code not in str(raised.value)


@pytest.mark.parametrize("cursor", ["garbage", "token-2", "s3v1.", "s3v1.bm90IGpzb24="])
def test_s3_list_rejects_a_cursor_it_did_not_produce_without_calling_the_provider(
    stubbed_s3, cursor
):
    storage, _ = stubbed_s3
    # Nothing is queued: a call to the provider would fail the test. "token-2" is a
    # bare provider token, which is not one of our cursors.
    with pytest.raises(InvalidInput):
        storage.list_files("docs/", 2, cursor)


def test_s3_list_rejects_a_cursor_from_another_prefix_without_calling_the_provider(
    stubbed_s3,
):
    storage, _ = stubbed_s3
    cursor = first_page_cursor(stubbed_s3)

    # OCI continues from the token's position instead of rejecting it, so a caller
    # who mixed prefixes would silently get the wrong page.
    with pytest.raises(InvalidInput):
        storage.list_files("other/", 2, cursor)


def test_s3_list_turns_a_rejected_cursor_into_invalid_input(stubbed_s3):
    storage, stubber = stubbed_s3
    cursor = first_page_cursor(stubbed_s3)
    # The provider can still reject a token it issued, for example once it expires.
    # OCI answers a token it cannot decode with InvalidArgument; so does AWS S3.
    stubber.add_client_error(
        "list_objects_v2",
        service_error_code="InvalidArgument",
        service_message="Illegal argument: unable to decode the token",
        http_status_code=400,
        expected_params={**LIST_PARAMS, "ContinuationToken": "token-2"},
    )

    with pytest.raises(InvalidInput) as raised:
        storage.list_files("docs/", 2, cursor)
    # The provider's code stays inside s3.py.
    assert "InvalidArgument" not in str(raised.value)


def test_s3_list_invalid_argument_without_a_cursor_is_still_a_provider_error(stubbed_s3):
    storage, stubber = stubbed_s3
    # Without a cursor the caller sent nothing the provider could reject, so this is
    # a provider or configuration problem.
    stubber.add_client_error(
        "list_objects_v2",
        service_error_code="InvalidArgument",
        http_status_code=400,
        expected_params=LIST_PARAMS,
    )

    with pytest.raises(ProviderError):
        storage.list_files("docs/", 2, None)


def test_s3_list_that_cannot_reach_the_provider_raises_provider_unavailable(
    stubbed_s3, monkeypatch
):
    storage, _ = stubbed_s3

    def unreachable(**kwargs):
        raise EndpointConnectionError(endpoint_url="https://s3.example.invalid")

    # The Stubber cannot simulate a connection failure, so replace the call itself.
    monkeypatch.setattr(storage._client, "list_objects_v2", unreachable)

    with pytest.raises(ProviderUnavailable) as raised:
        storage.list_files("docs/", 2, None)
    # An unstubbed call also ends as ProviderUnavailable (the Stubber's error is a
    # BotoCoreError), so check the cause to be sure this is the connection failure.
    assert isinstance(raised.value.__cause__, EndpointConnectionError)


@pytest.mark.provider
def test_list_folder_on_the_real_provider(provider_client, provider_prefix):
    names = ("g.txt", "C.txt", "e.txt", "a/x.txt", "a/deep/y.txt", "é.txt", "b.txt", "a.txt")
    created = {}
    for name in names:
        response = send_file(provider_client, "POST", provider_prefix + name, name.encode())
        assert response.status_code == 201
        created["/" + response.json()["key"]] = response.json()
    folder = "/" + provider_prefix.removesuffix("/")

    entries = list_folder(provider_client, folder).json()

    # Sorted by UTF-8 bytes: capitals first, "a" before "a.txt", "é" last.
    expected = ("C.txt", "a", "a.txt", "b.txt", "e.txt", "g.txt", "é.txt")
    assert [entry["path"] for entry in entries] == [f"{folder}/{name}" for name in expected]
    for entry in entries:
        if entry["name"] == "a":
            assert entry["type"] == "folder"
            assert entry["size"] is entry["modified_at"] is entry["etag"] is None
            continue
        assert entry["type"] == "file"
        assert entry["id"] is None
        assert entry["size"] == created[entry["path"]]["size"]
        assert entry["etag"] == created[entry["path"]]["etag"]
        assert entry["content_type"] is None
        assert datetime.fromisoformat(entry["modified_at"]).utcoffset() == timedelta(0)

    assert list_folder(provider_client, folder + "/missing").status_code == 404


# Folder listing (shared contract, #86): FileService.list_folder over each backend.


def folder_service(storage: StorageClient | None = None) -> FileService:
    return FileService(storage or InMemoryStorage(), max_upload_bytes=MAX_UPLOAD_BYTES)


def put(service: FileService, key: str) -> None:
    service.create(key, io.BytesIO(b"x"), 1)


def entries(listing: list[FolderEntry]) -> list[tuple[str, str]]:
    return [(entry.key, "file" if entry.info else "folder") for entry in listing]


def test_list_folder_returns_direct_files_and_folders_sorted_by_key():
    service = folder_service()
    for key in ("docs/b.txt", "docs/sub/x.txt", "docs/sub/deep/y.txt", "docs/a.txt"):
        put(service, key)
    put(service, "docs2/c.txt")

    assert entries(service.list_folder("/docs")) == [
        ("docs/a.txt", "file"),
        ("docs/b.txt", "file"),
        ("docs/sub", "folder"),
    ]


def test_list_folder_accepts_a_path_without_the_leading_slash():
    service = folder_service()
    put(service, "docs/a.txt")

    assert entries(service.list_folder("docs")) == [("docs/a.txt", "file")]


@pytest.mark.parametrize("root", ["/", ""])
def test_list_folder_of_the_root_lists_the_top_level(root):
    service = folder_service()
    for key in ("top.txt", "docs/a.txt"):
        put(service, key)

    assert entries(service.list_folder(root)) == [("docs", "folder"), ("top.txt", "file")]


def test_list_folder_of_a_missing_folder_is_file_not_found():
    service = folder_service()
    put(service, "docs/a.txt")

    with pytest.raises(FileNotFound):
        service.list_folder("/other")


def test_list_folder_of_the_empty_root_is_an_empty_list():
    assert folder_service().list_folder("/") == []


@pytest.mark.parametrize("path", ["/docs/", "/docs//a", "/docs/../a", "/a/./b"])
def test_list_folder_rejects_a_bad_path_without_calling_storage(path):
    fake = FakeStorage()

    with pytest.raises(InvalidInput):
        folder_service(fake).list_folder(path)
    assert fake.calls == []


def test_s3_list_folder_follows_every_page_and_merges_files_and_folders(stubbed_s3):
    storage, stubber = stubbed_s3
    params = {"Bucket": "test-bucket", "Prefix": "docs/", "MaxKeys": 1000, "Delimiter": "/"}

    def item(key: str) -> dict[str, Any]:
        return {"Key": key, "Size": 1, "ETag": '"etag"', "LastModified": MODIFIED}

    # Within a page S3 lists files and folders separately, so the service merges them.
    stubber.add_response(
        "list_objects_v2",
        {
            "IsTruncated": True,
            "NextContinuationToken": "token-2",
            "Contents": [item("docs/a.txt"), item("docs/n.txt")],
            "CommonPrefixes": [{"Prefix": "docs/m/"}],
        },
        params,
    )
    # A page can be empty and still have a next token.
    stubber.add_response(
        "list_objects_v2",
        {"IsTruncated": True, "NextContinuationToken": "token-3"},
        {**params, "ContinuationToken": "token-2"},
    )
    stubber.add_response(
        "list_objects_v2",
        {
            "IsTruncated": False,
            "Contents": [item("docs/q.txt")],
            "CommonPrefixes": [{"Prefix": "docs/z/"}],
        },
        {**params, "ContinuationToken": "token-3"},
    )

    assert entries(folder_service(storage).list_folder("/docs")) == [
        ("docs/a.txt", "file"),
        ("docs/m", "folder"),
        ("docs/n.txt", "file"),
        ("docs/q.txt", "file"),
        ("docs/z", "folder"),
    ]
