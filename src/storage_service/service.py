"""The service layer: the rules of the storage service.

Every operation validates its input, applies the rules below, and hands the
actual storage work to a StorageClient. This module knows nothing about HTTP
and nothing about any particular provider.

Rules:

* Create refuses to overwrite: it fails with FileAlreadyExists.
* Replace only works on a file that exists: otherwise FileNotFound.
* Delete of a path with no file or folder fails with FileNotFound, so typos are
  visible. Delete of a folder removes everything under it, and is not all-or-nothing.
* The server picks the content type from the key's extension. Whatever type
  the client claims is ignored.
* A client names a file by its path, with or without a leading "/". The storage
  layer only ever sees the key: the canonical path without its leading "/".

Known limitation: the existence check and the write are two separate provider
calls, so two clients racing on the same key can both pass the check. The last
write wins.

Every error records which storage call it came from (``StorageError.storage_call``),
so a failure log can say whether the provider was involved and whether a write was
attempted.
"""

import mimetypes
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import batched
from typing import BinaryIO

from storage_service.errors import (
    FileAlreadyExists,
    FileNotFound,
    FileTooLarge,
    InvalidInput,
    ProviderError,
    StorageError,
)
from storage_service.models import FileDownload, FileInfo, FilePage
from storage_service.storage.base import StorageClient

MAX_KEY_BYTES = 1024  # S3's limit on key length
MAX_PATH_BYTES = 1024  # the shared contract's limit, which counts the leading "/"
MAX_PAGE_SIZE = 1000  # S3 returns at most 1000 keys per list call
MAX_DELETE_BATCH = 1000  # S3 accepts at most 1000 keys per DeleteObjects call
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
            raise FileAlreadyExists(f"a file named {key!r} already exists", storage_call="stat")
        with _storage_call("put"):
            return self._storage.put(key, stream, guess_content_type(key))

    def replace(self, key: str, stream: BinaryIO, size: int) -> FileInfo:
        """Overwrite an existing file with new contents."""
        validate_key(key)
        self._check_size(size)
        if not self._exists(key):
            raise FileNotFound(f"no file named {key!r}", storage_call="stat")
        with _storage_call("put"):
            return self._storage.put(key, stream, guess_content_type(key))

    def download(self, key: str) -> FileDownload:
        validate_key(key)
        with _storage_call("get"):
            return self._storage.get(key)

    def stat(self, key: str) -> FileInfo:
        validate_key(key)
        with _storage_call("stat"):
            return self._storage.stat(key)

    def list_files(self, prefix: str = "", limit: int = 100, cursor: str | None = None) -> FilePage:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidInput(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if len(prefix.encode("utf-8")) > MAX_KEY_BYTES:
            raise InvalidInput(f"prefix is longer than {MAX_KEY_BYTES} bytes")
        with _storage_call("list_files"):
            return self._storage.list_files(prefix, limit, cursor)

    def delete(self, path: str) -> None:
        """Delete the file at ``path``, or else the folder there and everything under it.

        S3 lets a file and a folder share a path. Then only the file is deleted.
        """
        canonical = normalize_path(path)
        key = path_to_key(canonical)
        if self._exists(key):
            with _storage_call("delete"):
                self._storage.delete(key)
            return
        # The "/" keeps a folder named "docs" from matching "docs2/a.txt".
        keys = self._keys_under(f"{key}/")
        if not keys:
            raise FileNotFound(f"no file or folder at {canonical!r}", storage_call="list_files")
        self._delete_folder_keys(keys, canonical)

    def _keys_under(self, prefix: str) -> list[str]:
        """Every key under ``prefix``, following every page.

        A page can be short, or even empty, and still have a cursor, so stop only when
        there is no cursor. Folder Delete lists everything before deleting anything: a
        failed listing then changes nothing, and deleting cannot disturb the cursor.
        """
        keys: list[str] = []
        cursor: str | None = None
        while True:
            with _storage_call("list_files"):
                page = self._storage.list_files(prefix, MAX_PAGE_SIZE, cursor)
            keys += [info.key for info in page.files]
            cursor = page.next_cursor
            if cursor is None:
                return keys

    def _delete_folder_keys(self, keys: list[str], folder: str) -> None:
        """Delete ``keys`` in batches, stopping at the first batch that does not finish.

        Once a batch has finished, or when a batch reports keys it could not delete, the
        failure becomes a ``ProviderError`` whatever went wrong: the caller needs to know
        the folder may be partly deleted more than why. A retry deletes whatever is left.
        """
        unfinished = f"the delete of folder {folder!r} did not finish; some files may remain"
        for number, batch in enumerate(batched(keys, MAX_DELETE_BATCH, strict=False)):
            try:
                with _storage_call("delete_many"):
                    failed = self._storage.delete_many(batch)
            except StorageError as err:
                if number == 0:
                    raise  # no batch has finished, so report the failure as it is
                raise ProviderError(
                    unfinished, storage_call="delete_many", provider_code=err.provider_code
                ) from err
            if failed:
                raise ProviderError(unfinished, storage_call="delete_many")

    def _exists(self, key: str) -> bool:
        try:
            with _storage_call("stat"):
                self._storage.stat(key)
        except FileNotFound:
            return False
        return True

    def _check_size(self, size: int) -> None:
        if size > self._max_upload_bytes:
            raise FileTooLarge(f"file is {size} bytes; the limit is {self._max_upload_bytes}")


@contextmanager
def _storage_call(name: str) -> Iterator[None]:
    """Record on any error raised inside the block that storage call ``name`` raised it."""
    try:
        yield
    except StorageError as err:
        if err.storage_call is None:
            err.storage_call = name
        raise


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
    if _has_control_character(key):
        raise InvalidInput("key must not contain control characters")
    if _has_bad_segment(key):
        raise InvalidInput(
            "key must not start or end with '/', or contain '//', '.' or '..' segments"
        )


def normalize_path(path: str) -> str:
    """Return a client's path in its canonical form, or reject it.

    "docs/a.pdf" and "/docs/a.pdf" name the same file, and both give "/docs/a.pdf".
    Only that one leading "/" is optional: every segment after it must be a real
    name, as in ``validate_key``. The root "/" names no file, so it is rejected here.
    """
    if not path:
        raise InvalidInput("path must not be empty")
    canonical = path if path.startswith("/") else f"/{path}"
    if canonical == "/":
        raise InvalidInput("path must name a file, not the root folder")
    if len(canonical.encode("utf-8")) > MAX_PATH_BYTES:
        raise InvalidInput(f"path is longer than {MAX_PATH_BYTES} bytes")
    if _has_control_character(canonical):
        raise InvalidInput("path must not contain control characters")
    if _has_bad_segment(path_to_key(canonical)):
        raise InvalidInput("path must not end with '/', or contain '//', '.' or '..' segments")
    return canonical


def path_to_key(canonical_path: str) -> str:
    """The storage key for a canonical path: the same string without its leading "/"."""
    return canonical_path.removeprefix("/")


def _has_control_character(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def _has_bad_segment(name: str) -> bool:
    return any(segment in ("", ".", "..") for segment in name.split("/"))


def guess_content_type(key: str) -> str:
    """Pick a MIME type from the key's extension: "cat.jpg" gives "image/jpeg"."""
    guessed, _encoding = mimetypes.guess_type(key)
    return guessed or FALLBACK_CONTENT_TYPE
