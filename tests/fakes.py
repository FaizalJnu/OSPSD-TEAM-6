"""A controlled storage backend for application tests.

``FakeStorage`` wraps ``InMemoryStorage``. It records every call and can be told to
make a method raise one of our errors, so tests can check which storage calls a request
made and how a provider failure reaches the caller, without network or credentials.
"""

from typing import BinaryIO, Literal

from storage_service.errors import StorageError
from storage_service.models import FileDownload, FileInfo, FilePage
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage

Method = Literal["put", "get", "stat", "list_files", "delete"]


class FakeStorage:
    def __init__(self) -> None:
        # One (method, key) pair per call, in order. list_files records its prefix.
        self.calls: list[tuple[Method, str]] = []
        self._store = InMemoryStorage()
        self._failures: dict[Method, StorageError] = {}

    def fail(self, method: Method, error: StorageError) -> None:
        """Make every later call to ``method`` raise ``error`` before touching the store."""
        self._failures[method] = error

    def put(self, key: str, stream: BinaryIO, content_type: str) -> FileInfo:
        self._record("put", key)
        return self._store.put(key, stream, content_type)

    def get(self, key: str) -> FileDownload:
        self._record("get", key)
        return self._store.get(key)

    def stat(self, key: str) -> FileInfo:
        self._record("stat", key)
        return self._store.stat(key)

    def list_files(self, prefix: str, limit: int, cursor: str | None) -> FilePage:
        self._record("list_files", prefix)
        return self._store.list_files(prefix, limit, cursor)

    def delete(self, key: str) -> None:
        self._record("delete", key)
        self._store.delete(key)

    def _record(self, method: Method, key: str) -> None:
        self.calls.append((method, key))
        if method in self._failures:
            raise self._failures[method]


# Exists only so mypy proves that FakeStorage satisfies StorageClient.
_satisfies_storage_client: StorageClient = FakeStorage()
