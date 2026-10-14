"""The contract every storage backend must follow.

The rest of the service only talks to storage through this contract, so adding
a provider (Garage, a local disk, Google Drive, ...) means adding one module to
this package. Nothing outside ``storage/`` has to change.

Rules every backend must follow:

* Keys are used exactly as given. Validating them is the service's job.
* ``stat`` and ``get`` raise ``FileNotFound`` when the key does not exist.
* ``delete`` on a missing key succeeds silently, because that is how S3 behaves.
* ``list_files`` returns keys in sorted order, at most ``limit`` per page, with
  ``content_type`` set to None (S3 listings do not include it).
* Provider failures surface as ``ProviderError`` or ``ProviderUnavailable``.
  SDK-specific exceptions must never escape a backend.

``tests/test_storage_contract.py`` checks these rules against every backend.
"""

from typing import BinaryIO, Protocol

from storage_service.models import FileDownload, FileInfo, FilePage


class StorageClient(Protocol):
    def put(self, key: str, stream: BinaryIO, content_type: str) -> FileInfo:
        """Store everything readable from ``stream`` under ``key``, replacing any old file."""
        ...

    def get(self, key: str) -> FileDownload:
        """Open the file stored under ``key`` for reading. Only reads provider state.

        Returns a ``FileDownload``: the file's ``FileInfo`` (``content_type`` is the type
        stored with the file, or None if the provider has none; ``etag`` has no quotes)
        and ``chunks``, byte chunks that join to the whole file. The info is known before
        any contents are read. Contents are fetched from the provider as ``chunks`` is
        iterated, and it can be iterated only once. The backend releases its provider
        resources once ``chunks`` is exhausted, or closed after reading has started.

        Raises ``FileNotFound`` if no file exists under ``key``, and ``ProviderError`` or
        ``ProviderUnavailable`` if the provider fails while the file is being opened. A
        failure while ``chunks`` is being read is not translated yet (see the Download
        gaps in TESTING.md).
        """
        ...

    def stat(self, key: str) -> FileInfo:
        """Return a file's info without reading its contents."""
        ...

    def list_files(self, prefix: str, limit: int, cursor: str | None) -> FilePage:
        """Return up to ``limit`` files whose keys start with ``prefix``."""
        ...

    def delete(self, key: str) -> None:
        """Remove a file. Does nothing if it does not exist."""
        ...
