"""The tagged interface over Team 6's service and streaming backend."""

import asyncio
import hashlib
from collections.abc import Iterable
from io import BytesIO

import pytest
from cloud_storage_api import DocumentStorage, DownloadStream
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from storage_service.errors import FileTooLarge, ProviderUnavailable
from storage_service.main import build_service, create_app
from storage_service.models import FileDownload
from storage_service.service import FileService
from storage_service.shared_storage import SharedDocumentStorage
from tests.conftest import load_provider_settings
from tests.fakes import FakeStorage


class TrackedChunks:
    def __init__(
        self, chunks: Iterable[bytes] = (b"abcdef", b"gh"), error: Exception | None = None
    ) -> None:
        self.values = iter(chunks)
        self.reads = 0
        self.closed = 0
        self.error = error

    def __iter__(self) -> "TrackedChunks":
        return self

    def __next__(self) -> bytes:
        self.reads += 1
        try:
            return next(self.values)
        except StopIteration:
            if self.error:
                raise self.error from None
            raise

    def close(self) -> None:
        self.closed += 1


def setup_download(
    monkeypatch: pytest.MonkeyPatch, chunks: TrackedChunks | None = None
) -> tuple[SharedDocumentStorage, TrackedChunks]:
    backend = FakeStorage()
    service = FileService(backend, max_upload_bytes=16)
    info = service.create("a.txt", BytesIO(b"abcdefgh"), 8)
    source = chunks if chunks is not None else TrackedChunks()
    monkeypatch.setattr(backend, "get", lambda key: FileDownload(info, source))
    return SharedDocumentStorage(service), source


def test_shared_interface_covers_existing_operations():
    backend = FakeStorage()
    shared: DocumentStorage = SharedDocumentStorage(FileService(backend, max_upload_bytes=16))
    assert shared.create("a.txt", b"hello").path == "/a.txt"
    assert shared.replace("/a.txt", b"world").size == 5
    assert shared.download("/a.txt") == b"world"
    assert shared.get_metadata("a.txt").etag
    assert shared.list_files("/")[0].type == "file"
    assert shared.move("a.txt", "docs/b.txt").path == "/docs/b.txt"
    assert shared.list_files("/")[0].type == "folder"
    shared.check_health()
    shared.delete("docs")
    assert shared.list_files("/") == []


def test_open_is_eager_but_contents_are_lazy_and_close_is_idempotent(monkeypatch):
    shared, source = setup_download(monkeypatch)
    stream = shared.open_download("a.txt")
    assert isinstance(stream, DownloadStream)
    assert stream.info.size == 8
    assert stream.info.path == "/a.txt"
    assert source.reads == 0
    stream.close()
    stream.close()
    assert source.closed == 1
    with pytest.raises(ValueError, match="closed"):
        list(stream.chunks())


def test_chunks_are_bounded_and_exhaustion_closes_the_provider(monkeypatch):
    shared, source = setup_download(monkeypatch)
    with shared.open_download("a.txt") as stream:
        assert list(stream.chunks(3)) == [b"abc", b"def", b"gh"]
    assert source.closed == 1


def test_late_failure_preserves_the_error_and_closes(monkeypatch):
    source = TrackedChunks(chunks=[b"abc"], error=ProviderUnavailable("cut off"))
    shared, source = setup_download(monkeypatch, source)
    with pytest.raises(ProviderUnavailable, match="cut off"):
        with shared.open_download("a.txt") as stream:
            list(stream.chunks())
    assert source.closed == 1


@pytest.mark.parametrize("size", [0, -1])
def test_invalid_chunk_size_does_not_consume_provider_data(monkeypatch, size):
    shared, source = setup_download(monkeypatch)
    with shared.open_download("a.txt") as stream:
        with pytest.raises(ValueError, match="positive"):
            list(stream.chunks(size))
        assert source.reads == 0
    assert source.closed == 1


@pytest.mark.parametrize("method", ["create_stream", "replace_stream"])
def test_upload_reads_from_current_position_and_never_closes_input(method, monkeypatch):
    backend = FakeStorage()
    shared = SharedDocumentStorage(FileService(backend, max_upload_bytes=16))
    shared.create("a.txt", b"old")
    original = backend.put

    def put_and_close(key, stream, content_type):
        try:
            return original(key, stream, content_type)
        finally:
            stream.close()

    monkeypatch.setattr(backend, "put", put_and_close)
    source = BytesIO(b"skipnew")
    source.seek(4)
    path = "b.txt" if method == "create_stream" else "a.txt"
    getattr(shared, method)(path, source)
    assert not source.closed
    assert shared.download(path) == b"new"


class NonSeekable(BytesIO):
    def seekable(self):
        return False

    def read(self, size=-1):
        assert 0 < size <= 65536
        return super().read(size)


def test_unknown_length_oversize_is_rejected_before_storage_writes():
    backend = FakeStorage()
    shared = SharedDocumentStorage(FileService(backend, max_upload_bytes=4))
    source = NonSeekable(b"12345")
    with pytest.raises(FileTooLarge):
        shared.create_stream("a.txt", source)
    assert backend.calls == []
    assert not source.closed


def test_bytes_compatibility_limit_checks_actual_data_and_closes(monkeypatch):
    shared, source = setup_download(monkeypatch)
    monkeypatch.setattr("storage_service.shared_storage.LEGACY_DOWNLOAD_MAX_BYTES", 4)
    with pytest.raises(FileTooLarge):
        shared.download("a.txt")
    assert source.reads == 0
    assert source.closed == 1


def test_bytes_compatibility_rechecks_growth_during_read(monkeypatch):
    source = TrackedChunks([b"abcd", b"efghi"])
    shared, source = setup_download(monkeypatch, source)
    monkeypatch.setattr("storage_service.shared_storage.LEGACY_DOWNLOAD_MAX_BYTES", 8)
    with pytest.raises(FileTooLarge):
        shared.download("a.txt")
    assert source.closed == 1


def test_http_download_uses_streaming_and_closes_on_success(monkeypatch):
    backend = FakeStorage()
    service = FileService(backend, max_upload_bytes=16)
    info = service.create("a.txt", BytesIO(b"abcdefgh"), 8)
    source = TrackedChunks()
    monkeypatch.setattr(backend, "get", lambda key: FileDownload(info, source))
    monkeypatch.setattr(
        SharedDocumentStorage,
        "download",
        lambda *args: pytest.fail("HTTP must not call the bytes compatibility method"),
    )
    with TestClient(create_app(service)) as client:
        response = client.get("/files/download", params={"path": "a.txt"})
    assert response.content == b"abcdefgh"
    assert response.headers["content-length"] == "8"
    assert source.closed == 1


@pytest.mark.parametrize("when", ["http.response.start", "http.response.body"])
@pytest.mark.parametrize("failure", [OSError, asyncio.CancelledError])
def test_http_disconnect_or_cancellation_still_closes(monkeypatch, when, failure):
    backend = FakeStorage()
    service = FileService(backend, max_upload_bytes=16)
    info = service.create("a.txt", BytesIO(b"abcdefgh"), 8)
    source = TrackedChunks()
    monkeypatch.setattr(backend, "get", lambda key: FileDownload(info, source))
    app = create_app(service)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "method": "GET",
        "path": "/files/download",
        "raw_path": b"/files/download",
        "query_string": b"path=a.txt",
        "headers": [],
        "scheme": "http",
        "http_version": "1.1",
        "server": ("test", 80),
        "client": ("test", 1),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == when:
            raise failure("client disconnected")

    # Starlette converts this send failure into ClientDisconnect on ASGI 2.4.
    expected = ClientDisconnect if failure is OSError else asyncio.CancelledError
    with pytest.raises(expected):
        asyncio.run(app(scope, receive, send))
    assert source.reads == (0 if when == "http.response.start" else 1)
    assert source.closed == 1


@pytest.mark.provider
def test_tagged_interface_streaming_round_trip_on_real_provider(provider_client, provider_prefix):
    # provider_client owns cleanup of this test's unique prefix, including failures.
    shared: DocumentStorage = SharedDocumentStorage(build_service(load_provider_settings()))
    path = "/" + provider_prefix + "streamed.bin"
    destination = "/" + provider_prefix + "moved.bin"
    data = b"s" * (9 * 1024 * 1024)  # Exercises multipart upload without owning the input.
    source = BytesIO(data)
    created = shared.create_stream(path, source)
    assert not source.closed
    assert created.path == path
    assert created.size == len(data)
    digest = hashlib.sha256()
    with shared.open_download(path) as download:
        assert download.info.size == len(data)
        for chunk in download.chunks(65536):
            assert len(chunk) <= 65536
            digest.update(chunk)
    assert digest.digest() == hashlib.sha256(data).digest()
    replacement = BytesIO(b"replacement")
    shared.replace_stream(path, replacement)
    assert not replacement.closed
    assert shared.download(path) == b"replacement"
    assert shared.get_metadata(path).size == 11
    assert any(info.path == path for info in shared.list_files("/" + provider_prefix.rstrip("/")))
    assert shared.move(path, destination).path == destination
    shared.check_health()
    shared.delete(destination)
