"""A controlled storage backend for application tests.

``FakeStorage`` wraps ``InMemoryStorage``. It records every call and can be told to
make a method raise one of our errors, so tests can check which storage calls a request
made and how a provider failure reaches the caller, without network or credentials. It
can also raise any other exception, to stand in for a bug in a backend.
A failure can happen before the store is touched (the call changes nothing) or after
(the change is made, then the error is raised, like a provider that completed a write
but whose response was lost). A download can also fail partway through its chunks, like
a provider connection that drops while the body is being read.
"""

from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import BinaryIO, Literal

from storage_service.models import FileDownload, FileInfo, FilePage
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage

Method = Literal["put", "get", "stat", "list_files", "delete"]


class FakeStorage:
    def __init__(self) -> None:
        # One (method, key) pair per call, in order. list_files records its prefix.
        self.calls: list[tuple[Method, str]] = []
        self._store = InMemoryStorage()
        self._failures: dict[Method, tuple[Exception, bool]] = {}
        self._cut_downloads: tuple[Exception, int] | None = None

    def fail(self, method: Method, error: Exception, *, after_applying: bool = False) -> None:
        """Make every later call to ``method`` raise ``error``.

        By default the error is raised before the store is touched, so the call changes
        nothing. With ``after_applying=True`` the call changes the store first and then
        raises.
        """
        self._failures[method] = (error, after_applying)

    def cut_downloads(self, error: Exception, *, after_bytes: int) -> None:
        """Make every later download raise ``error`` once ``after_bytes`` bytes are read.

        ``get`` itself succeeds and returns the file's info. The error comes from its
        chunks, after the first ``after_bytes`` bytes of the file.
        """
        self._cut_downloads = (error, after_bytes)

    def put(self, key: str, stream: BinaryIO, content_type: str) -> FileInfo:
        return self._run("put", key, lambda: self._store.put(key, stream, content_type))

    def get(self, key: str) -> FileDownload:
        download = self._run("get", key, lambda: self._store.get(key))
        if self._cut_downloads is None:
            return download
        error, after_bytes = self._cut_downloads
        return replace(download, chunks=_cut_off(download.chunks, error, after_bytes))

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


def _cut_off(chunks: Iterator[bytes], error: Exception, after_bytes: int) -> Iterator[bytes]:
    """Yield the first ``after_bytes`` bytes of ``chunks``, then raise ``error``."""
    data = b"".join(chunks)  # files in tests are small
    yield data[:after_bytes]
    raise error


# Exists only so mypy proves that FakeStorage satisfies StorageClient.
_satisfies_storage_client: StorageClient = FakeStorage()
