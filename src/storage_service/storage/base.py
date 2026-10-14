"""The contract every storage backend must follow.

``StorageClient`` has one method for each thing an operation needs from storage,
in our own types, so the service never sees a provider SDK. Adding a provider
(Garage, a local disk, Google Drive, ...) means adding one module to this package
and one branch in ``main.build_storage``. Nothing else has to change.
``docs/ARCHITECTURE.md`` explains why each method exists and how the backend is
wired in.

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

        Raises ``FileNotFound`` if no file exists under ``key``. Provider failures raise
        ``ProviderError`` or ``ProviderUnavailable``, both while the file is being opened
        and while ``chunks`` is being iterated.
        """
        ...

    def stat(self, key: str) -> FileInfo:
        """Return a file's info without reading its contents."""
        ...

    def list_files(self, prefix: str, limit: int, cursor: str | None) -> FilePage:
        """Return one page of the files whose keys start with ``prefix``. Only reads.

        ``prefix`` is plain text compared with the start of each key, not a folder: keys
        at every depth under it match, and ``""`` matches every file. ``limit`` is from 1
        to 1000; the service checks it before calling. ``cursor`` is None for the first
        page, or a ``next_cursor`` this backend returned for the same ``prefix``.

        Returns a ``FilePage`` with at most ``limit`` files, sorted by the UTF-8 bytes of
        their keys. Each has ``content_type`` None (S3 listings do not include it) and an
        ``etag`` without quotes. ``next_cursor`` is None when no files are left. A page
        can be shorter than ``limit``, even empty, and still have a ``next_cursor``, so
        callers continue until it is None. Cursors are opaque: the backend picks their
        format, and callers only pass them back unchanged.

        Following the cursors over files that do not change returns each matching file
        exactly once. Pages are not a snapshot: a file created or deleted between calls
        may or may not appear.

        Raises ``ProviderError`` or ``ProviderUnavailable`` if the provider fails. No
        matches is an empty page, not an error. What happens with a cursor this backend
        did not produce is not settled yet (BUG-CURSOR in fixesRequired.md, FIX-3).
        """
        ...

    def delete(self, key: str) -> None:
        """Remove a file. Does nothing if it does not exist."""
        ...
