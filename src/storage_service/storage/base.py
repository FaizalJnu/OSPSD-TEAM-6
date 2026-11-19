"""The contract every storage backend must follow.

``StorageClient`` has one method for each thing an operation needs from storage,
in our own types, so the service never sees a provider SDK. Adding a provider
(a local disk, Google Drive, ...) means adding one module to this package
and one branch in ``wiring.build_storage``. Nothing else has to change.
``docs/ARCHITECTURE.md`` explains why each method exists and how the backend is
wired in.

Rules every backend must follow:

* Keys are used exactly as given. Validating them is the service's job.
* ``stat`` and ``get`` raise ``FileNotFound`` when the key does not exist, and so does
  ``copy`` when its source does not exist.
* ``delete`` on a missing key succeeds silently, because that is how S3 behaves.
* ``delete_many`` treats a missing key the same way, and returns the keys it could
  not remove instead of raising for them.
* ``list_files`` returns keys in sorted order, at most ``limit`` per page, with
  ``content_type`` set to None (S3 listings do not include it).
* ``check_health`` makes one cheap provider call and returns nothing when the
  configured storage can be used.
* Provider failures surface as ``ProviderError`` or ``ProviderUnavailable``.
  SDK-specific exceptions must never escape a backend.

``tests/test_storage_contract.py`` checks these rules against every backend.
"""

from collections.abc import Sequence
from typing import BinaryIO, Protocol

from storage_service.models import FileDownload, FileInfo, FilePage


class StorageClient(Protocol):
    def put(self, key: str, stream: BinaryIO, content_type: str) -> FileInfo:
        """Store everything readable from ``stream`` under ``key`` and return its info.

        Changes provider state: creates the file, or replaces it if ``key`` already
        exists. Deciding between create and replace is the service's job, not the
        backend's.

        Inputs:

        * ``key``: used exactly as given. The service has already validated it.
        * ``stream``: read from its current position to the end. It may be empty,
          because 0-byte files are allowed. Backends read it in parts, so a large
          file never has to fit in memory.
        * ``content_type``: stored with the file and reported by later ``get`` and
          ``stat`` calls. The service picks it; backends store it unchanged.

        Returns the stored file's info as the provider reports it after the write,
        so ``size``, ``etag``, and ``last_modified`` describe what was actually
        stored. The S3 backend reads them back with a follow-up ``stat``.

        If it raises, the write may or may not have happened.
        """
        ...

    def get(self, key: str) -> FileDownload:
        """Open the file stored under ``key`` for reading. Only reads provider state.

        Returns a ``FileDownload``: the file's ``FileInfo`` (``content_type`` is the type
        stored with the file, or None if the provider has none; ``etag`` has no quotes)
        and ``chunks``, byte chunks that join to the whole file. The info is known before
        any contents are read. Contents are fetched from the provider as ``chunks`` is
        iterated, and it can be iterated only once. The backend releases its provider
        resources once ``chunks`` is exhausted or closed.

        Raises ``FileNotFound`` if no file exists under ``key``. Provider failures raise
        ``ProviderError`` or ``ProviderUnavailable``, both while the file is being opened
        and while ``chunks`` is being iterated.
        """
        ...

    def stat(self, key: str) -> FileInfo:
        """Read metadata for the exact key without downloading or changing its contents.

        The service validates the key before calling this method; the backend
        uses it unchanged. Return a FileInfo with the byte size, stored content
        type (None if unavailable), an opaque ETag without surrounding quotes,
        and the provider's timezone-aware UTC modification time. For an unchanged
        file, key, size, and ETag agree with list_files; timestamp precision may
        differ between provider operations.

        This only reads provider state. Raise FileNotFound for a missing file,
        ProviderError for provider rejection, or ProviderUnavailable when the
        provider cannot be reached. Provider SDK objects and exceptions stay
        inside the backend. A read does not lock the file against concurrent writes.
        """
        ...

    def list_files(
        self, prefix: str, limit: int, cursor: str | None, delimiter: str | None = None
    ) -> FilePage:
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

        Raises ``InvalidInput`` for a cursor this backend did not produce, and
        ``ProviderError`` or ``ProviderUnavailable`` if the provider fails. No matches is
        an empty page, not an error. A cursor from another ``prefix`` counts as one this
        backend did not produce. S3 wraps the provider's token with its prefix to check
        this, and also raises ``InvalidInput`` when the provider rejects the token.

        With a ``delimiter`` (the service uses "/"), keys that contain it after the
        prefix are not returned. Each distinct prefix up to and including the first
        delimiter is returned once in ``folders`` instead, as S3's ``CommonPrefixes``.
        Files and folders together count toward ``limit``, and the cursor continues
        after the last of either. Use the same delimiter for every page.
        """
        ...

    def copy(self, source_key: str, dest_key: str) -> FileInfo:
        """Copy the file stored under ``source_key`` to ``dest_key`` and return the copy's info.

        Changes provider state: creates the file at ``dest_key``, or replaces it if one
        exists. Deciding whether that is allowed is the service's job. The source is left
        unchanged. The copy has the source's contents and content type. Its
        ``last_modified`` is the time of the copy.

        Raises ``FileNotFound`` if no file exists under ``source_key``, and
        ``AccessDenied``, ``ProviderError``, or ``ProviderUnavailable`` if the provider
        fails. If it raises, the copy may or may not have been made.
        """
        ...

    def delete(self, key: str) -> None:
        """Remove a file. Does nothing if it does not exist."""
        ...

    def delete_many(self, keys: Sequence[str]) -> list[str]:
        """Remove several files in one provider call. Return the keys it could not remove.

        ``keys`` holds from 1 to 1000 keys; the service splits larger sets into batches
        before calling. A key that does not exist counts as removed, as for ``delete``.
        An empty result means every key is gone.

        Raises ``AccessDenied``, ``ProviderError`` or ``ProviderUnavailable`` if the call
        as a whole fails. Any of the keys may or may not have been removed by then.
        """
        ...

    def check_health(self) -> None:
        """Check with one cheap provider call that the configured storage can be used.

        Only reads, and reads no file. The S3 backend sends one HeadBucket. Returns
        nothing when the storage answers.

        Raises ``AccessDenied`` if the provider refuses the credentials,
        ``ProviderError`` if the configured storage is missing or the provider rejects
        the call, and ``ProviderUnavailable`` if the provider cannot be reached.
        """
        ...
