"""The tagged DocumentStorage interface over Team 6's domain service.

HTTP callers use open_download. The explicit legacy bytes API has a separate
150 MiB cap; it is the only compatibility path that assembles a whole download.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from io import BufferedIOBase, BytesIO
from tempfile import TemporaryFile
from typing import BinaryIO, cast

from cloud_storage_api import DocumentStorage, DownloadStream
from cloud_storage_api import FileInfo as SharedFileInfo
from cloud_storage_api.errors import StorageError as SharedStorageError

from storage_service.errors import FileTooLarge, ProviderUnavailable
from storage_service.models import CommonFileInfo, FileDownload, common_file_info
from storage_service.service import FileService, normalize_path, path_to_key

LEGACY_DOWNLOAD_MAX_BYTES = 150 * 1024 * 1024
STREAM_CHUNK_BYTES = 65536


class SharedDocumentStorage(DocumentStorage):
    """Adapt all shared operations while retaining the domain/provider boundary."""

    def __init__(self, service: FileService) -> None:
        self._service = service

    def create(self, path: str, content: bytes) -> CommonFileInfo:
        return self.create_stream(path, BytesIO(content))

    def replace(self, path: str, content: bytes) -> CommonFileInfo:
        return self.replace_stream(path, BytesIO(content))

    def create_stream(self, path: str, stream: BinaryIO) -> CommonFileInfo:
        key = path_to_key(normalize_path(path))
        with self._upload(stream) as (source, size):
            return common_file_info(self._service.create(key, source, size))

    def replace_stream(self, path: str, stream: BinaryIO) -> CommonFileInfo:
        key = path_to_key(normalize_path(path))
        with self._upload(stream) as (source, size):
            return common_file_info(self._service.replace(key, source, size))

    @contextmanager
    def _upload(self, stream: BinaryIO) -> Iterator[tuple[BinaryIO, int]]:
        if stream.seekable():
            start = stream.tell()
            stream.seek(0, 2)
            size = stream.tell() - start
            stream.seek(start)
            self._check_size(size, self._service.upload_limit)
            # Some transfer implementations close their input; they only borrow it.
            with _BorrowedInput(stream) as borrowed:
                yield cast(BinaryIO, borrowed), size
        else:
            # Validate unknown-length input before any provider mutation, using disk.
            with TemporaryFile(mode="w+b") as spool:
                size = 0
                while chunk := stream.read(STREAM_CHUNK_BYTES):
                    size += len(chunk)
                    self._check_size(size, self._service.upload_limit)
                    spool.write(chunk)
                spool.seek(0)
                yield spool, size

    def download(self, path: str) -> bytes:
        """Explicit, bounded bytes compatibility. HTTP must use open_download."""
        with self.open_download(path) as download:
            assert download.info.size is not None
            self._check_size(download.info.size, LEGACY_DOWNLOAD_MAX_BYTES)
            pieces: list[bytes] = []
            size = 0
            for chunk in download.chunks():
                size += len(chunk)
                self._check_size(size, LEGACY_DOWNLOAD_MAX_BYTES)
                pieces.append(chunk)
            return b"".join(pieces)

    @staticmethod
    def _check_size(size: int, limit: int) -> None:
        if size > limit:
            raise FileTooLarge(f"file exceeds the {limit}-byte limit for this operation")

    def open_download(self, path: str) -> DownloadStream:
        # Eager provider open; the wrapper does not advance the body iterator.
        return _SharedDownload(self._service.download(path))

    def get_metadata(self, path: str) -> CommonFileInfo:
        return self._service.get_metadata(path)

    def list_files(self, path: str) -> list[SharedFileInfo]:
        return [*self._service.list_entries(path)]

    def move(self, from_path: str, to_path: str) -> CommonFileInfo:
        return self._service.move(from_path, to_path)

    def delete(self, path: str) -> None:
        self._service.delete(path)

    def check_health(self) -> None:
        try:
            self._service.check_health()
        except SharedStorageError as error:
            raise ProviderUnavailable(
                "the storage provider health check failed",
                storage_call=getattr(error, "storage_call", None),
                provider_code=getattr(error, "provider_code", None),
            ) from error


class _BorrowedInput(BufferedIOBase):
    """Closing this wrapper never closes the caller's stream."""

    def __init__(self, stream: BinaryIO) -> None:
        super().__init__()
        self._stream = stream

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return self._stream.seekable()

    def read(self, size: int | None = -1) -> bytes:
        if self.closed:
            raise ValueError("the borrowed stream is closed")
        return self._stream.read(-1 if size is None else size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._stream.seek(offset, whence)

    def tell(self) -> int:
        return self._stream.tell()


class _SharedDownload(DownloadStream):
    def __init__(self, download: FileDownload) -> None:
        self._info = common_file_info(download.info)
        self._source = download.chunks
        self._closed = False

    @property
    def info(self) -> CommonFileInfo:
        return self._info

    def chunks(self, size: int = STREAM_CHUNK_BYTES) -> Iterator[bytes]:
        if size <= 0:
            raise ValueError("chunk size must be positive")
        if self._closed:
            raise ValueError("the download is closed")
        try:
            for chunk in self._source:
                for start in range(0, len(chunk), size):
                    if self._closed:
                        raise ValueError("the download is closed")
                    yield chunk[start : start + size]
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            close = getattr(self._source, "close", None)
            if close is not None:
                close()
