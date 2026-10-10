"""The service layer: the rules of the storage service.

Every operation validates its input, applies the rules below, and hands the
actual storage work to a StorageClient. This module knows nothing about HTTP
and nothing about any particular provider.

Rules:

* Create refuses to overwrite: it fails with FileAlreadyExists.
* Replace only works on a file that exists: otherwise FileNotFound.
* Delete of a missing file fails with FileNotFound, so typos are visible.
* The server picks the content type from the key's extension. Whatever type
  the client claims is ignored.

Known limitation: the existence check and the write are two separate provider
calls, so two clients racing on the same key can both pass the check. The last
write wins.
"""

import mimetypes
from typing import BinaryIO

from storage_service.errors import FileAlreadyExists, FileNotFound, FileTooLarge, InvalidInput
from storage_service.models import FileDownload, FileInfo, FilePage
from storage_service.storage.base import StorageClient

MAX_KEY_BYTES = 1024  # S3's limit on key length
MAX_PAGE_SIZE = 1000  # S3 returns at most 1000 keys per list call
FALLBACK_CONTENT_TYPE = "application/octet-stream"


class FileService:
    def __init__(self, storage: StorageClient, *, max_upload_bytes: int) -> None:
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes

    def create(self, key: str, stream: BinaryIO, size: int) -> FileInfo:
        """Store a new file. Fails if the key is already taken."""
        validate_key(key)
        self._check_size(size)
        if self._exists(key):
            raise FileAlreadyExists(f"a file named {key!r} already exists")
        return self._storage.put(key, stream, guess_content_type(key))

    def replace(self, key: str, stream: BinaryIO, size: int) -> FileInfo:
        """Overwrite an existing file with new contents."""
        validate_key(key)
        self._check_size(size)
        if not self._exists(key):
            raise FileNotFound(f"no file named {key!r}")
        return self._storage.put(key, stream, guess_content_type(key))

    def download(self, key: str) -> FileDownload:
        validate_key(key)
        return self._storage.get(key)

    def stat(self, key: str) -> FileInfo:
        validate_key(key)
        return self._storage.stat(key)

    def list_files(self, prefix: str = "", limit: int = 100, cursor: str | None = None) -> FilePage:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidInput(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if len(prefix.encode("utf-8")) > MAX_KEY_BYTES:
            raise InvalidInput(f"prefix is longer than {MAX_KEY_BYTES} bytes")
        return self._storage.list_files(prefix, limit, cursor)

    def delete(self, key: str) -> None:
        validate_key(key)
        if not self._exists(key):
            raise FileNotFound(f"no file named {key!r}")
        self._storage.delete(key)

    def _exists(self, key: str) -> bool:
        try:
            self._storage.stat(key)
        except FileNotFound:
            return False
        return True

    def _check_size(self, size: int) -> None:
        if size > self._max_upload_bytes:
            raise FileTooLarge(f"file is {size} bytes; the limit is {self._max_upload_bytes}")


def validate_key(key: str) -> None:
    """Reject keys that are empty, too long, or could be mistaken for tricky paths.

    Keys may contain "/" to group files like folders ("photos/cat.jpg"), but every
    segment between slashes must be a real name: no empty segments, no "." and no
    "..". That keeps keys safe if a backend ever maps them onto a real filesystem.
    """
    if not key:
        raise InvalidInput("key must not be empty")
    if len(key.encode("utf-8")) > MAX_KEY_BYTES:
        raise InvalidInput(f"key is longer than {MAX_KEY_BYTES} bytes")
    if any(ord(char) < 32 or ord(char) == 127 for char in key):
        raise InvalidInput("key must not contain control characters")
    if any(segment in ("", ".", "..") for segment in key.split("/")):
        raise InvalidInput(
            "key must not start or end with '/', or contain '//', '.' or '..' segments"
        )


def guess_content_type(key: str) -> str:
    """Pick a MIME type from the key's extension: "cat.jpg" gives "image/jpeg"."""
    guessed, _encoding = mimetypes.guess_type(key)
    return guessed or FALLBACK_CONTENT_TYPE
