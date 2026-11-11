"""Delete: DELETE /files?path=, for one file or a whole folder. Owner: Faizal Rahman."""

import io

import pytest
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, ProviderError, ProviderUnavailable, StorageError
from storage_service.main import create_app
from storage_service.models import FilePage
from storage_service.service import FileService
from tests.conftest import MAX_UPLOAD_BYTES, send_file
from tests.fakes import FakeStorage

UNAVAILABLE = "could not reach the storage provider"
UNFINISHED = "the delete of folder '/docs' did not finish; some files may remain"


def delete_path(client: TestClient, path: str):
    return client.delete("/files", params={"path": path})


def add_files(fake: FakeStorage, folder: str, count: int) -> None:
    for number in range(count):
        fake.put(f"{folder}/{number:04}.txt", io.BytesIO(b""), "text/plain")
    fake.calls.clear()


def methods_called(fake: FakeStorage) -> list[str]:
    return [method for method, _ in fake.calls]


def test_delete_removes_the_file_and_deleting_again_is_404(client):
    send_file(client, "POST", "old.txt", b"bye")
    assert delete_path(client, "old.txt").status_code == 204
    assert client.get("/files/download", params={"path": "old.txt"}).status_code == 404
    assert delete_path(client, "old.txt").status_code == 404


def test_delete_checks_the_file_exists_then_deletes_it(fake, fake_client):
    send_file(fake_client, "POST", "old.txt", b"bye")
    fake.calls.clear()

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 204
    assert response.content == b""
    assert fake.calls == [("stat", "old.txt"), ("delete", "old.txt")]


@pytest.mark.parametrize("path", ["docs/old.txt", "/docs/old.txt"])
def test_delete_finds_the_file_with_or_without_the_leading_slash(fake, fake_client, path):
    send_file(fake_client, "POST", "docs/old.txt", b"bye")
    fake.calls.clear()

    assert delete_path(fake_client, path).status_code == 204
    # Storage only ever sees the key, so a file stored before paths existed is still found.
    assert fake.calls == [("stat", "docs/old.txt"), ("delete", "docs/old.txt")]


def test_delete_of_a_missing_file_is_404_and_never_calls_delete(fake, fake_client):
    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 404
    assert response.json()["error"] == "FileNotFound"
    # A miss is followed by a look for a folder of that name.
    assert fake.calls == [("stat", "old.txt"), ("list_files", "old.txt/")]


def test_delete_of_a_missing_file_reports_the_canonical_path(client):
    response = delete_path(client, "docs/old.txt")

    assert response.json() == {
        "error": "FileNotFound",
        "detail": "no file or folder at '/docs/old.txt'",
    }


@pytest.mark.parametrize("path", ["", "/", "docs/", "a//b", "a/../b", "bad\nname", "x" * 1024])
def test_delete_of_an_invalid_path_is_400_and_never_calls_storage(fake, fake_client, path):
    response = delete_path(fake_client, path)

    assert response.status_code == 400
    assert response.json()["error"] == "InvalidInput"
    assert fake.calls == []


def test_delete_without_a_path_is_400_and_never_calls_storage(fake, fake_client):
    response = fake_client.delete("/files")

    assert response.status_code == 400
    assert response.json() == {"error": "InvalidInput", "detail": "path: Field required"}
    assert fake.calls == []


def test_delete_decodes_the_path_from_the_query_string(client):
    # In a query string "+" means a space, so a literal "+" has to arrive as %2B.
    send_file(client, "POST", "a+b c.txt", b"bye")

    assert client.delete("/files?path=a%2Bb%20c.txt").status_code == 204
    assert client.get("/metadata/a+b c.txt").status_code == 404


def test_the_old_keyed_delete_route_no_longer_deletes(client):
    send_file(client, "POST", "old.txt", b"bye")

    assert client.delete("/files/old.txt").status_code != 204
    assert client.get("/metadata/old.txt").status_code == 200


def test_delete_returns_503_and_never_deletes_when_the_check_cannot_reach_the_provider(
    fake, fake_client
):
    fake.fail("stat", ProviderUnavailable("could not reach the storage provider"))

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 503
    assert response.json() == {
        "error": "ProviderUnavailable",
        "detail": "could not reach the storage provider",
    }
    assert fake.calls == [("stat", "old.txt")]


def test_delete_returns_502_when_the_provider_rejects_the_delete(fake, fake_client):
    send_file(fake_client, "POST", "old.txt", b"bye")
    fake.calls.clear()
    fake.fail("delete", ProviderError("the storage provider rejected the request"))

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 502
    assert response.json() == {
        "error": "ProviderError",
        "detail": "the storage provider rejected the request",
    }
    assert fake.calls == [("stat", "old.txt"), ("delete", "old.txt")]


def test_delete_that_removes_the_file_then_fails_returns_503_and_a_retry_is_404(fake, fake_client):
    send_file(fake_client, "POST", "old.txt", b"bye")
    unavailable = ProviderUnavailable("could not reach the storage provider")
    fake.fail("delete", unavailable, after_applying=True)

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 503
    assert response.json() == {"error": "ProviderUnavailable", "detail": str(unavailable)}
    # The 503 did not mean nothing changed: the file is gone.
    assert fake_client.get("/metadata/old.txt").status_code == 404
    assert delete_path(fake_client, "old.txt").status_code == 404


def test_delete_of_a_folder_removes_everything_under_it_and_nothing_else(client):
    for key in ("docs/a.txt", "docs/sub/b.txt", "docs2/c.txt", "docs-backup/d.txt", "other.txt"):
        send_file(client, "POST", key, b"data")

    response = delete_path(client, "docs")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/metadata/docs/a.txt").status_code == 404
    assert client.get("/metadata/docs/sub/b.txt").status_code == 404
    for survivor in ("docs2/c.txt", "docs-backup/d.txt", "other.txt"):
        assert client.get(f"/metadata/{survivor}").status_code == 200


def test_deleting_a_folder_again_is_404(client):
    send_file(client, "POST", "docs/a.txt", b"data")

    assert delete_path(client, "docs").status_code == 204
    assert delete_path(client, "docs").status_code == 404


@pytest.mark.parametrize("path", ["docs", "/docs"])
def test_delete_of_a_folder_lists_it_then_deletes_its_keys(fake, fake_client, path):
    send_file(fake_client, "POST", "docs/a.txt", b"data")
    send_file(fake_client, "POST", "docs/sub/b.txt", b"data")
    fake.calls.clear()

    assert delete_path(fake_client, path).status_code == 204

    assert fake.calls == [
        ("stat", "docs"),
        ("list_files", "docs/"),
        ("delete_many", "docs/a.txt,docs/sub/b.txt"),
    ]


def test_delete_of_a_large_folder_reads_every_page_then_deletes_1000_keys_per_call(
    fake, fake_client
):
    add_files(fake, "docs", 2001)

    assert delete_path(fake_client, "docs").status_code == 204

    assert methods_called(fake) == ["stat"] + ["list_files"] * 3 + ["delete_many"] * 3
    batches = [value.split(",") for method, value in fake.calls if method == "delete_many"]
    assert [len(batch) for batch in batches] == [1000, 1000, 1]
    assert fake.list_files("docs/", 10, None).files == []


class _EmptyFirstPage(FakeStorage):
    """Returns an empty first page with a cursor, which the List contract allows."""

    def list_files(self, prefix: str, limit: int, cursor: str | None) -> FilePage:
        if cursor is None:
            return FilePage(files=[], next_cursor="page-2")
        return super().list_files(prefix, limit, None)


def test_delete_of_a_folder_follows_the_cursor_past_an_empty_page():
    storage = _EmptyFirstPage()
    storage.put("docs/a.txt", io.BytesIO(b"x"), "text/plain")
    client = TestClient(create_app(FileService(storage, max_upload_bytes=MAX_UPLOAD_BYTES)))

    assert delete_path(client, "docs").status_code == 204
    assert ("delete_many", "docs/a.txt") in storage.calls


def test_delete_removes_only_the_file_when_a_file_and_a_folder_share_a_path(fake, fake_client):
    send_file(fake_client, "POST", "docs", b"file")
    send_file(fake_client, "POST", "docs/a.txt", b"inside")
    fake.calls.clear()

    assert delete_path(fake_client, "docs").status_code == 204

    assert fake.calls == [("stat", "docs"), ("delete", "docs")]
    assert fake_client.get("/metadata/docs/a.txt").status_code == 200


def test_delete_does_not_treat_the_start_of_a_name_as_a_folder(client):
    send_file(client, "POST", "docs/a.txt", b"data")

    assert delete_path(client, "do").status_code == 404
    assert client.get("/metadata/docs/a.txt").status_code == 200


def test_a_folder_listing_that_fails_partway_deletes_nothing(fake, fake_client):
    add_files(fake, "docs", 1001)
    fake.fail("list_files", ProviderUnavailable(UNAVAILABLE), after_calls=1)

    response = delete_path(fake_client, "docs")

    assert response.status_code == 503
    assert methods_called(fake) == ["stat", "list_files", "list_files"]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProviderUnavailable(UNAVAILABLE), 503),
        (ProviderError("the storage provider rejected the request"), 502),
        (AccessDenied("the storage provider denied access"), 403),
    ],
)
def test_a_folder_delete_whose_first_batch_fails_reports_that_failure_unchanged(
    fake, fake_client, error: StorageError, status: int
):
    add_files(fake, "docs", 1001)
    fake.fail("delete_many", error)

    response = delete_path(fake_client, "docs")

    assert response.status_code == status
    assert response.json() == {"error": type(error).__name__, "detail": str(error)}
    assert methods_called(fake).count("delete_many") == 1


def test_a_folder_delete_that_fails_after_a_finished_batch_is_502_and_stops(fake, fake_client):
    add_files(fake, "docs", 2001)
    fake.fail("delete_many", ProviderUnavailable(UNAVAILABLE), after_calls=1)

    response = delete_path(fake_client, "docs")

    # A timeout alone would be 503, but here the caller must learn the delete is partial.
    assert response.status_code == 502
    assert response.json() == {"error": "ProviderError", "detail": UNFINISHED}
    assert methods_called(fake).count("delete_many") == 2


def test_a_folder_delete_whose_batch_reports_failed_keys_is_502_and_stops(fake, fake_client):
    add_files(fake, "docs", 1001)
    fake.refused_keys.add("docs/0000.txt")

    response = delete_path(fake_client, "docs")

    assert response.status_code == 502
    assert response.json() == {"error": "ProviderError", "detail": UNFINISHED}
    assert methods_called(fake).count("delete_many") == 1


def test_retrying_a_partly_deleted_folder_deletes_what_is_left(fake, fake_client):
    add_files(fake, "docs", 3)
    fake.refused_keys.add("docs/0001.txt")
    assert delete_path(fake_client, "docs").status_code == 502
    fake.refused_keys.clear()

    assert delete_path(fake_client, "docs").status_code == 204
    assert delete_path(fake_client, "docs").status_code == 404


def test_s3_delete_denied_by_the_provider_raises_access_denied(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "delete_object",
        service_error_code="AccessDenied",
        http_status_code=403,
        expected_params={"Bucket": "test-bucket", "Key": "old.txt"},
    )
    with pytest.raises(AccessDenied):
        storage.delete("old.txt")


def test_s3_delete_many_sends_the_keys_in_one_call_and_reports_no_failures(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_response(
        "delete_objects",
        {},
        expected_params={
            "Bucket": "test-bucket",
            "Delete": {"Objects": [{"Key": "docs/a.txt"}, {"Key": "docs/b.txt"}], "Quiet": True},
            "ChecksumAlgorithm": "SHA256",  # OCI rejects boto3's default, CRC32
        },
    )

    assert storage.delete_many(["docs/a.txt", "docs/b.txt"]) == []


def test_s3_delete_many_returns_the_keys_the_provider_could_not_delete(stubbed_s3):
    storage, stubber = stubbed_s3
    # DeleteObjects answers 200 and lists its failures in the body.
    stubber.add_response(
        "delete_objects",
        {"Errors": [{"Key": "docs/b.txt", "Code": "InternalError", "Message": "try again"}]},
    )

    assert storage.delete_many(["docs/a.txt", "docs/b.txt"]) == ["docs/b.txt"]


def test_s3_delete_many_denied_by_the_provider_raises_access_denied(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "delete_objects", service_error_code="AccessDenied", http_status_code=403
    )

    with pytest.raises(AccessDenied):
        storage.delete_many(["docs/a.txt"])


def test_s3_delete_many_rejected_by_the_provider_raises_provider_error(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "delete_objects", service_error_code="MalformedXML", http_status_code=400
    )

    with pytest.raises(ProviderError):
        storage.delete_many(["docs/a.txt"])


@pytest.mark.provider
def test_delete_removes_the_file_from_the_real_provider(provider_client, provider_prefix):
    key = provider_prefix + "old.txt"
    assert send_file(provider_client, "POST", key, b"bye").status_code == 201
    assert delete_path(provider_client, key).status_code == 204
    assert provider_client.get(f"/metadata/{key}").status_code == 404


@pytest.mark.provider
def test_delete_removes_a_nested_folder_from_the_real_provider(provider_client, provider_prefix):
    for name in ("folder/a.txt", "folder/sub/b.txt", "keep.txt"):
        response = send_file(provider_client, "POST", provider_prefix + name, b"data")
        assert response.status_code == 201

    assert delete_path(provider_client, provider_prefix + "folder").status_code == 204

    assert provider_client.get(f"/metadata/{provider_prefix}folder/a.txt").status_code == 404
    assert provider_client.get(f"/metadata/{provider_prefix}folder/sub/b.txt").status_code == 404
    assert provider_client.get(f"/metadata/{provider_prefix}keep.txt").status_code == 200
