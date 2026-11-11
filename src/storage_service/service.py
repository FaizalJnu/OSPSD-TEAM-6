"""The service layer: the rules of the storage service.

Every operation validates its input, applies the rules below, and hands the
actual storage work to a StorageClient. This module knows nothing about HTTP
and nothing about any particular provider.

Rules:

* Create refuses to overwrite: it fails with FileAlreadyExists.
* Replace only works on a file that exists: otherwise FileNotFound.
* Delete of a path with no file or folder fails with FileNotFound, so typos are
  visible. Delete of a folder removes everything under it, and is not all-or-nothing.
* Move never overwrites: a file or folder at the new path fails with
  FileAlreadyExists. It copies, then deletes the original, so a failed delete
  after a successful copy is a ProviderError: the file may now be at both paths.
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

from cloud_storage_api.errors import NotFoundError as SharedNotFoundError
from cloud_storage_api.errors import StorageError as SharedStorageError

from storage_service.errors import (
    FileAlreadyExists,
    FileNotFound,
    FileTooLarge,
    InvalidInput,
    InvalidOperation,
    ProviderError,
)
from storage_service.models import (
    CommonFileInfo,
    FileDownload,
    FileInfo,
    FolderEntry,
    common_entry,
    common_file_info,
)
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

    @property
    def upload_limit(self) -> int:
        """The configured limit, also used to validate unknown-length streams."""
        return self._max_upload_bytes

    def check_health(self) -> None:
        """Make one lightweight read against the configured storage."""
        with _storage_call("list_files"):
            self._storage.list_files("", 1, None)

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

    def download(self, path: str) -> FileDownload:
        key = path_to_key(normalize_path(path))
        with _storage_call("get"):
            return self._storage.get(key)

    def stat(self, key: str) -> FileInfo:
        validate_key(key)
        with _storage_call("stat"):
            return self._storage.stat(key)

    def get_metadata(self, path: str) -> CommonFileInfo:
        """Read canonical shared metadata without reading any file contents."""
        key = path_to_key(normalize_path(path))
        return common_file_info(self.stat(key))

    def list_entries(self, path: str) -> list[CommonFileInfo]:
        """The folder at ``path`` as the shared contract lists it, in common form."""
        return [common_entry(entry) for entry in self.list_folder(path)]

    def list_folder(self, path: str) -> list[FolderEntry]:
        """The files and folders directly inside the folder at ``path``, sorted by key.

        Every page is fetched, so the caller gets the whole folder in one result. "/"
        (or "") is the root. A folder exists only while a file is under it, as on S3,
        so a path with nothing under it is ``FileNotFound``, except the root, which is
        just empty.
        """
        canonical = normalize_folder(path)
        key = path_to_key(canonical)
        prefix = f"{key}/" if key else ""
        listing: list[FolderEntry] = []
        cursor: str | None = None
        while True:
            with _storage_call("list_files"):
                page = self._storage.list_files(prefix, MAX_PAGE_SIZE, cursor, delimiter="/")
            listing += [FolderEntry(key=info.key, info=info) for info in page.files]
            listing += [
                FolderEntry(key=folder.removesuffix("/"), info=None) for folder in page.folders
            ]
            cursor = page.next_cursor
            if cursor is None:
                break
        if not listing and key:
            raise FileNotFound(f"no folder at {canonical!r}", storage_call="list_files")
        # S3 sorts files and folders separately within a page, so sort them together.
        return sorted(listing, key=lambda entry: entry.key)

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
            except SharedStorageError as err:
                if number == 0:
                    raise  # no batch has finished, so report the failure as it is
                raise ProviderError(
                    unfinished,
                    storage_call="delete_many",
                    provider_code=getattr(err, "provider_code", None),
                ) from err
            if failed:
                raise ProviderError(unfinished, storage_call="delete_many")

    def move(self, path: str, new_path: str) -> CommonFileInfo:
        """Move a file from ``path`` to ``new_path`` and return its info at the new path.

        Checked in this order, so nothing is copied unless every check passes:

        1. Both paths follow the path rules: otherwise InvalidInput.
        2. The paths differ, and not only in letter case: otherwise InvalidOperation,
           without calling storage. Some providers treat "A.pdf" and "a.pdf" as one
           file and S3 treats them as two, so a case-only rename is refused.
        3. A file exists at ``path``: otherwise InvalidOperation if ``path`` is a
           folder (files are stored under it), else FileNotFound.
        4. Nothing exists at ``new_path``, neither a file nor a folder: otherwise
           FileAlreadyExists.
        5. Copy, then delete the original. If the delete fails for any reason, the copy
           exists and the original may or may not, so the error is ProviderError.
        """
        source = normalize_path(path)
        dest = normalize_path(new_path)
        if dest == source:
            raise InvalidOperation(f"{dest!r} is already the file's path")
        if dest.casefold() == source.casefold():
            raise InvalidOperation("a move cannot change only the letter case of a path")
        source_key, dest_key = path_to_key(source), path_to_key(dest)
        if not self._exists(source_key):
            if self._is_folder(source_key):
                raise InvalidOperation(
                    f"{source!r} is a folder; only files can be moved", storage_call="list_files"
                )
            raise FileNotFound(f"no file at {source!r}", storage_call="stat")
        if self._exists(dest_key):
            raise FileAlreadyExists(f"a file already exists at {dest!r}", storage_call="stat")
        if self._is_folder(dest_key):
            raise FileAlreadyExists(
                f"a folder already exists at {dest!r}", storage_call="list_files"
            )
        with _storage_call("copy"):
            info = self._storage.copy(source_key, dest_key)
        try:
            with _storage_call("delete"):
                self._storage.delete(source_key)
        except SharedStorageError as err:
            raise ProviderError(
                f"the file was copied to {dest!r}, but deleting the original at {source!r} "
                "could not be confirmed",
                storage_call="delete",
                provider_code=getattr(err, "provider_code", None),
            ) from err
        return common_file_info(info)

    def _exists(self, key: str) -> bool:
        try:
            with _storage_call("stat"):
                self._storage.stat(key)
        except SharedNotFoundError:
            return False
        return True

    def _is_folder(self, key: str) -> bool:
        """Whether any file is stored under ``key + "/"``, which makes ``key`` a folder."""
        with _storage_call("list_files"):
            return bool(self._storage.list_files(key + "/", 1, None).files)

    def _check_size(self, size: int) -> None:
        if size > self._max_upload_bytes:
            raise FileTooLarge(f"file is {size} bytes; the limit is {self._max_upload_bytes}")


@contextmanager
def _storage_call(name: str) -> Iterator[None]:
    """Record on any error raised inside the block that storage call ``name`` raised it."""
    try:
        yield
    except SharedStorageError as err:
        if getattr(err, "storage_call", None) is None:
            # Tagged exceptions have no private diagnostic fields of their own.
            err.__dict__["storage_call"] = name
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


def normalize_folder(path: str) -> str:
    """Like ``normalize_path``, but "" and "/" name the root folder instead of failing."""
    if path in ("", "/"):
        return "/"
    return normalize_path(path)


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
