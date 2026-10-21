"""Download: GET /files/{key}. Owner: Vikram Markali."""

import io
import os
from datetime import UTC, datetime

import pytest
from botocore.response import StreamingBody

from storage_service.errors import AccessDenied, FileNotFound, ProviderUnavailable
from storage_service.models import FileInfo
from tests.conftest import send_file


def test_download_returns_the_bytes_and_every_promised_header(client):
    data = b"%PDF-1.7 not really a pdf \x00\xff"
    send_file(client, "POST", "docs/résumé.pdf", data)
    etag = client.get("/metadata/docs/résumé.pdf").json()["etag"]

    response = client.get("/files/docs/résumé.pdf")

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


@pytest.mark.parametrize(
    ("key", "content_type"),
    [("notes.txt", "text/plain; charset=utf-8"), ("blob.unknownext", "application/octet-stream")],
)
def test_download_content_type_comes_from_the_extension(client, key, content_type):
    send_file(client, "POST", key, b"data")
    assert client.get(f"/files/{key}").headers["content-type"] == content_type


def test_download_with_an_invalid_key_is_400(client):
    response = client.get("/files/a//b.txt")
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error", "detail"}
    assert body["error"] == "InvalidInput"


def test_download_of_a_missing_file_is_404(client):
    response = client.get("/files/missing.txt")
    assert response.status_code == 404
    assert set(response.json()) == {"error", "detail"}
    assert response.json()["error"] == "FileNotFound"


def test_download_returns_503_when_the_provider_is_unavailable(fake, fake_client):
    fake.fail("get", ProviderUnavailable("could not reach the storage provider"))

    response = fake_client.get("/files/notes.txt")

    assert response.status_code == 503
    assert response.json() == {
        "error": "ProviderUnavailable",
        "detail": "could not reach the storage provider",
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


def queue_get_object(stubber, key: str, data: bytes, raw: io.BytesIO | None = None) -> io.BytesIO:
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
    etag = provider_client.get(f"/metadata/{key}").json()["etag"]

    response = provider_client.get(f"/files/{key}")

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-length"] == str(len(data))
    assert response.headers["etag"] == f'"{etag}"'
