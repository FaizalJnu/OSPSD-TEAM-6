"""In-memory ``DocumentStorage`` (cloud-storage-api 0.3.1).

It follows the same path rules and folder behavior as Team 6's storage service
(``storage_service.service``), so a test that passes here passes against the
real implementation for the same reason.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from cloud_storage_api import (
    ConflictError,
    DocumentStorage,
    FileInfo,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    ProviderUnavailableError,
)

from meeting_prep.fakes._failures import FakeBase

MAX_PATH_BYTES = 1024  # the shared contract's limit, counting the leading "/"


@dataclass(frozen=True)
class _Stored:
    content: bytes
    modified_at: str
    etag: str


class FakeStorage(FakeBase, DocumentStorage):
    """Files in a dict keyed by canonical path, such as ``/reviews/agenda.md``."""

    OPERATIONS = frozenset(
        {
            "create",
            "replace",
            "download",
            "get_metadata",
            "list_files",
            "move",
            "delete",
            "check_health",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.files: dict[str, _Stored] = {}

    def create(self, path: str, content: bytes) -> FileInfo:
        with self._lock:
            failure = self._start("create", path, content)
            canonical = normalize_path(path)
            if canonical in self.files:
                raise ConflictError(f"a file already exists at {canonical!r}")
            info = self._store(canonical, content)
            self._finish(failure)
            return info

    def replace(self, path: str, content: bytes) -> FileInfo:
        with self._lock:
            failure = self._start("replace", path, content)
            canonical = normalize_path(path)
            if canonical not in self.files:
                raise NotFoundError(f"no file at {canonical!r}")
            info = self._store(canonical, content)
            self._finish(failure)
            return info

    def download(self, path: str) -> bytes:
        with self._lock:
            failure = self._start("download", path)
            content = self._lookup(normalize_path(path)).content
            self._finish(failure)
            return content

    def get_metadata(self, path: str) -> FileInfo:
        with self._lock:
            failure = self._start("get_metadata", path)
            canonical = normalize_path(path)
            info = _file_info(canonical, self._lookup(canonical))
            self._finish(failure)
            return info

    def list_files(self, path: str) -> list[FileInfo]:
        with self._lock:
            failure = self._start("list_files", path)
            folder = "/" if path in ("", "/") else normalize_path(path)
            prefix = folder if folder == "/" else f"{folder}/"
            entries: dict[str, FileInfo] = {}
            for stored_path, stored in self.files.items():
                if not stored_path.startswith(prefix):
                    continue
                child, _, rest = stored_path.removeprefix(prefix).partition("/")
                child_path = f"{prefix}{child}"
                if rest:
                    entries.setdefault(child_path, _folder_info(child_path))
                else:
                    entries[child_path] = _file_info(child_path, stored, listed=True)
            # As on S3, a folder exists only while a file is under it; the root always does.
            if not entries and folder != "/":
                raise NotFoundError(f"no folder at {folder!r}")
            listing = [entries[key] for key in sorted(entries)]
            self._finish(failure)
            return listing

    def move(self, from_path: str, to_path: str) -> FileInfo:
        """Move one file, refusing what the storage service refuses, in the same order.

        The paths must differ, and not only in letter case; only a file can be moved,
        not a folder; and nothing, neither a file nor a folder, may be at ``to_path``.
        """
        with self._lock:
            failure = self._start("move", from_path, to_path)
            source = normalize_path(from_path)
            destination = normalize_path(to_path)
            if destination == source:
                raise InvalidOperationError(f"{destination!r} is already the file's path")
            if destination.casefold() == source.casefold():
                raise InvalidOperationError("a move cannot change only the letter case of a path")
            if source not in self.files and self._is_folder(source):
                raise InvalidOperationError(f"{source!r} is a folder; only files can be moved")
            stored = self._lookup(source)
            if destination in self.files:
                raise ConflictError(f"a file already exists at {destination!r}")
            if self._is_folder(destination):
                raise ConflictError(f"a folder already exists at {destination!r}")
            info = self._store(destination, stored.content)
            del self.files[source]
            self._finish(failure)
            return info

    def delete(self, path: str) -> None:
        """Delete the file at ``path``, or else the folder there and everything under it."""
        with self._lock:
            failure = self._start("delete", path)
            canonical = normalize_path(path)
            if canonical in self.files:
                del self.files[canonical]
            else:
                under = [key for key in self.files if key.startswith(f"{canonical}/")]
                if not under:
                    raise NotFoundError(f"no file or folder at {canonical!r}")
                for key in under:
                    del self.files[key]
            self._finish(failure)

    def check_health(self) -> None:
        with self._lock:
            self._finish(self._start("check_health"))

    def _store(self, canonical: str, content: bytes) -> FileInfo:
        stored = _Stored(
            content=content,
            modified_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            etag=hashlib.md5(content, usedforsecurity=False).hexdigest(),
        )
        self.files[canonical] = stored
        return _file_info(canonical, stored)

    def _is_folder(self, canonical: str) -> bool:
        """Whether any file is stored under ``canonical + "/"``, which makes it a folder."""
        prefix = f"{canonical}/"
        return any(key.startswith(prefix) for key in self.files)

    def _lookup(self, canonical: str) -> _Stored:
        stored = self.files.get(canonical)
        if stored is None:
            raise NotFoundError(f"no file at {canonical!r}")
        return stored


def failing_storage() -> FakeStorage:
    """Storage that is unreachable on every call (registry name ``fake-failing``)."""
    storage = FakeStorage()
    storage.failures.fail_always(ProviderUnavailableError("the storage provider is unavailable"))
    return storage


def normalize_path(path: str) -> str:
    """The canonical form of a file path, with the storage service's rules.

    "docs/a.md" and "/docs/a.md" name the same file. Every segment must be a real
    name: no empty, "." or ".." segments, no trailing "/", no control characters.
    """
    if not path:
        raise InvalidRequestError("path must not be empty")
    canonical = path if path.startswith("/") else f"/{path}"
    if canonical == "/":
        raise InvalidRequestError("path must name a file, not the root folder")
    if len(canonical.encode("utf-8")) > MAX_PATH_BYTES:
        raise InvalidRequestError(f"path is longer than {MAX_PATH_BYTES} bytes")
    if any(ord(char) < 32 or ord(char) == 127 for char in canonical):
        raise InvalidRequestError("path must not contain control characters")
    if any(segment in ("", ".", "..") for segment in canonical[1:].split("/")):
        raise InvalidRequestError("path must not end with '/', or contain '//', '.' or '..'")
    return canonical


def _file_info(canonical: str, stored: _Stored, *, listed: bool = False) -> FileInfo:
    return FileInfo(
        id=None,
        name=canonical.rsplit("/", 1)[-1],
        path=canonical,
        size=len(stored.content),
        modified_at=stored.modified_at,
        etag=stored.etag,
        type="file" if listed else None,  # the contract sets type on list entries only
    )


def _folder_info(canonical: str) -> FileInfo:
    return FileInfo(
        id=None,
        name=canonical.rsplit("/", 1)[-1],
        path=canonical,
        size=None,
        modified_at=None,
        etag=None,
        type="folder",
    )
