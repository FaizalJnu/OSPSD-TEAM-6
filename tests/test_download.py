"""Download: GET /files/download?path=. Owner: Vikram Markali."""

import io
import os
from datetime import UTC, datetime

import pytest
from botocore.response import StreamingBody
from fastapi.testclient import TestClient
from urllib3.exceptions import ProtocolError

from storage_service.errors import AccessDenied, FileNotFound, ProviderUnavailable
from storage_service.models import FileInfo
from tests.conftest import send_file


def download_path(client: TestClient, path: str):
    return client.get("/files/download", params={"path": path})


def test_download_returns_the_bytes_and_every_promised_header(client):
    data = b"%PDF-1.7 not really a pdf \x00\xff"
    send_file(client, "POST", "docs/résumé.pdf", data)
    etag = client.get("/files/metadata?path=docs/résumé.pdf").json()["etag"]

    response = download_path(client, "/docs/résumé.pdf")

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(len(data))
    assert response.headers["etag"] == f'"{etag}"'
    assert (
        response.headers["content-disposition"]
        == "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"
    )
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["docs/notes.txt", "/docs/notes.txt"])
def test_download_finds_the_file_with_or_without_the_leading_slash(fake, fake_client, path):
    send_file(fake_client, "POST", "docs/notes.txt", b"data")
    fake.calls.clear()

    response = download_path(fake_client, path)

    assert response.content == b"data"
    # Storage only ever sees the key, so a file stored before paths existed is still found.
    assert fake.calls == [("get", "docs/notes.txt")]


@pytest.mark.parametrize(
    ("key", "content_type"),
    [("notes.txt", "text/plain; charset=utf-8"), ("blob.unknownext", "application/octet-stream")],
)
def test_download_content_type_comes_from_the_extension(client, key, content_type):
    send_file(client, "POST", key, b"data")
    assert download_path(client, key).headers["content-type"] == content_type


@pytest.mark.parametrize("path", ["", "/", "docs/", "a//b.txt", "a/../b", "bad\nname"])
def test_download_of_an_invalid_path_is_400_and_never_calls_storage(fake, fake_client, path):
    response = download_path(fake_client, path)

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "invalid_request"
    assert fake.calls == []


def test_download_without_a_path_is_400_and_never_calls_storage(fake, fake_client):
    response = fake_client.get("/files/download")

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "path: Field required"}
    }
    assert fake.calls == []


def test_download_of_a_missing_file_is_404(client):
    response = download_path(client, "missing.txt")
    assert response.status_code == 404
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "not_found"


def test_the_old_keyed_download_route_is_gone(client):
    send_file(client, "POST", "notes.txt", b"data")

    response = client.get("/files/notes.txt")

    # /files/{key} still exists for Create and Replace, so GET there is a 405, not a 404.
    assert response.status_code == 405
    assert response.json() == {
        "error": {"code": "method_not_allowed", "message": "this path does not accept GET"},
    }
    assert response.headers["allow"] == "POST, PUT"


def test_download_returns_503_when_the_provider_is_unavailable(fake, fake_client):
    fake.fail("get", ProviderUnavailable("could not reach the storage provider"))

    response = download_path(fake_client, "notes.txt")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "provider_unavailable", "message": "could not reach the storage provider"}
    }
    assert fake.calls == [("get", "notes.txt")]


class RecordingStream(io.BytesIO):
    """A provider stream that remembers the size asked for by every read."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.read_sizes: list[int | None] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


class DropsAfterFirstRead(io.RawIOBase):
    """A provider stream whose connection breaks after its first read, as in #26."""

    def __init__(self, first: bytes) -> None:
        self.first = first
        self.reads = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1, /) -> bytes:
        self.reads += 1
        if self.reads == 1:
            return self.first
        raise ProtocolError("Connection broken: IncompleteRead")


def queue_get_object(stubber, key: str, data: bytes, raw: io.IOBase | None = None) -> io.IOBase:
    """Queue a get_object answer for ``key`` and return the raw stream behind its body.

    Pass ``raw`` to use your own stream holding ``data``, for example a RecordingStream.
    """
    if raw is None:
        raw = io.BytesIO(data)
    stubber.add_response(
        "get_object",
        {
            "Body": StreamingBody(raw, len(data)),
            "ContentLength": len(data),
            "ContentType": "application/pdf",
            "ETag": '"abc123"',
            "LastModified": datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
        },
        expected_params={"Bucket": "test-bucket", "Key": key},
    )
    return raw


def test_s3_get_translates_the_response_into_file_info_and_chunks(stubbed_s3):
    storage, stubber = stubbed_s3
    data = b"x" * 10
    queue_get_object(stubber, "docs/report.pdf", data)

    download = storage.get("docs/report.pdf")

    assert download.info == FileInfo(
        key="docs/report.pdf",
        size=10,
        content_type="application/pdf",
        etag="abc123",
        last_modified=datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
    )
    assert b"".join(download.chunks) == data


def test_s3_get_of_a_missing_key_raises_file_not_found(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "get_object",
        service_error_code="NoSuchKey",
        http_status_code=404,
        expected_params={"Bucket": "test-bucket", "Key": "missing.pdf"},
    )
    with pytest.raises(FileNotFound):
        storage.get("missing.pdf")


def test_s3_get_closes_the_provider_stream(stubbed_s3):
    storage, stubber = stubbed_s3
    consumed = queue_get_object(stubber, "a.pdf", b"data")
    abandoned = queue_get_object(stubber, "b.pdf", b"data")

    b"".join(storage.get("a.pdf").chunks)
    chunks = storage.get("b.pdf").chunks
    next(chunks)
    chunks.close()  # a caller that stops reading after the first chunk

    assert consumed.closed
    assert abandoned.closed


def test_s3_get_streams_in_chunks(stubbed_s3, monkeypatch):
    storage, stubber = stubbed_s3
    monkeypatch.setattr("storage_service.storage.s3.DOWNLOAD_CHUNK_BYTES", 4)
    queue_get_object(stubber, "a.pdf", b"x" * 10)
    assert [len(chunk) for chunk in storage.get("a.pdf").chunks] == [4, 4, 2]


def test_s3_get_reads_lazily_one_chunk_at_a_time(stubbed_s3, monkeypatch):
    storage, stubber = stubbed_s3
    monkeypatch.setattr("storage_service.storage.s3.DOWNLOAD_CHUNK_BYTES", 4)
    raw = RecordingStream(b"x" * 10)
    queue_get_object(stubber, "a.pdf", b"x" * 10, raw)

    chunks = storage.get("a.pdf").chunks
    assert raw.read_sizes == []  # opening the download reads nothing

    assert next(chunks) == b"xxxx"
    assert raw.read_sizes == [4]  # one chunk read, not the whole body
    chunks.close()


def test_s3_get_closes_the_provider_stream_when_no_chunk_was_read(stubbed_s3):
    storage, stubber = stubbed_s3
    raw = queue_get_object(stubber, "a.pdf", b"data")

    storage.get("a.pdf").chunks.close()

    assert raw.closed


def test_s3_get_translates_a_connection_dropped_mid_download(stubbed_s3):
    storage, stubber = stubbed_s3
    raw = queue_get_object(stubber, "a.pdf", b"x" * 100, DropsAfterFirstRead(b"first"))

    chunks = storage.get("a.pdf").chunks
    assert next(chunks) == b"first"
    # botocore turns the broken read into ResponseStreamingError, which must not escape.
    with pytest.raises(ProviderUnavailable) as raised:
        next(chunks)

    assert raised.value.provider_code == "ResponseStreamingError"
    assert "IncompleteRead" not in str(raised.value)
    assert raw.closed  # the connection is released


def test_s3_get_denied_by_the_provider_raises_access_denied(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "get_object",
        service_error_code="AccessDenied",
        http_status_code=403,
        expected_params={"Bucket": "test-bucket", "Key": "secret.pdf"},
    )
    with pytest.raises(AccessDenied) as raised:
        storage.get("secret.pdf")
    # The provider's code is kept for the logs, not put in the message.
    assert raised.value.provider_code == "AccessDenied"
    assert "AccessDenied" not in str(raised.value)


@pytest.mark.provider
def test_download_of_a_multi_megabyte_file_from_the_real_provider(provider_client, provider_prefix):
    key = provider_prefix + "big.bin"
    data = os.urandom(5 * 1024 * 1024)  # chunking itself: test_s3_get_streams_in_chunks
    assert send_file(provider_client, "POST", key, data).status_code == 201
    etag = provider_client.get("/files/metadata", params={"path": key}).json()["etag"]

    response = download_path(provider_client, key)

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-length"] == str(len(data))
    assert response.headers["etag"] == f'"{etag}"'
