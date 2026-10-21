"""A controlled storage backend for application tests.

``FakeStorage`` wraps ``InMemoryStorage``. It records every call and can be told to
make a method raise one of our errors, so tests can check which storage calls a request
made and how a provider failure reaches the caller, without network or credentials.
A failure can happen before the store is touched (the call changes nothing) or after
(the change is made, then the error is raised, like a provider that completed a write
but whose response was lost).
"""

from collections.abc import Callable
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
        self._failures: dict[Method, tuple[StorageError, bool]] = {}

    def fail(self, method: Method, error: StorageError, *, after_applying: bool = False) -> None:
        """Make every later call to ``method`` raise ``error``.

        By default the error is raised before the store is touched, so the call changes
        nothing. With ``after_applying=True`` the call changes the store first and then
        raises.
        """
        self._failures[method] = (error, after_applying)

    def put(self, key: str, stream: BinaryIO, content_type: str) -> FileInfo:
        return self._run("put", key, lambda: self._store.put(key, stream, content_type))

    def get(self, key: str) -> FileDownload:
        return self._run("get", key, lambda: self._store.get(key))

    def stat(self, key: str) -> FileInfo:
        return self._run("stat", key, lambda: self._store.stat(key))

    def list_files(self, prefix: str, limit: int, cursor: str | None) -> FilePage:
        return self._run(
            "list_files", prefix, lambda: self._store.list_files(prefix, limit, cursor)
        )

    def delete(self, key: str) -> None:
        self._run("delete", key, lambda: self._store.delete(key))

    def _run[T](self, method: Method, key: str, apply: Callable[[], T]) -> T:
        """Record the call, then apply it to the store and raise as configured."""
        self.calls.append((method, key))
        failure = self._failures.get(method)
        if failure is None:
            return apply()
        error, after_applying = failure
        if after_applying:
            apply()
        raise error


# Exists only so mypy proves that FakeStorage satisfies StorageClient.
_satisfies_storage_client: StorageClient = FakeStorage()
