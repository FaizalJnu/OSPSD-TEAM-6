"""Errors this service raises on purpose.

These are plain Python exceptions with no HTTP in them, so the same errors work
for any caller: the HTTP API, a command-line tool, or an agent. ``routers/error_handlers.py`` is
the only place that turns them into HTTP status codes.
"""

from cloud_storage_api import errors as shared


class StorageError(shared.StorageError):
    """Base class for every error the service raises on purpose.

    Two optional notes travel with an error for the failure log, never to the caller
    (see ``routers/error_handlers.py``):

    * ``storage_call``: the storage call ("stat", "put", "get", "list_files",
      "delete", "delete_many") that raised the error, or whose answer made the service raise it.
      ``None`` means the request was rejected before storage was called.
    * ``provider_code``: the provider's or SDK's own name for the failure, such as
      ``NoSuchBucket`` or ``EndpointConnectionError``. It describes the provider,
      not this service, so it stays out of responses.
    """

    def __init__(
        self, message: str, *, storage_call: str | None = None, provider_code: str | None = None
    ) -> None:
        super().__init__(message)
        self.storage_call = storage_call
        self.provider_code = provider_code


class InvalidInput(StorageError, shared.InvalidRequestError):
    """The caller sent a key, size, or parameter that we do not accept."""


class FileNotFound(StorageError, shared.NotFoundError):
    """No file exists under the requested key."""


class FileAlreadyExists(StorageError, shared.ConflictError):
    """A file already exists under the key the caller tried to create."""


class FileTooLarge(StorageError, shared.FileTooLargeError):
    """The upload is bigger than the configured limit."""


class AccessDenied(StorageError, shared.PermissionDeniedError):
    """The provider refused this service's credentials or permissions for the request.

    A configuration problem on the service's side, not the caller's. Retrying will
    not help until the credentials or the bucket's permissions change.
    """


class ProviderError(StorageError, shared.ProviderError):
    """The provider refused the request: a missing bucket, an unsupported request, and so on.

    Access problems are ``AccessDenied`` instead. Usually a configuration problem,
    which retrying will not fix. It can also be a provider-side failure that lasted
    through the client's own retries, so retrying later sometimes succeeds.
    """


class ProviderUnavailable(StorageError, shared.ProviderUnavailableError):
    """The provider could not be reached: network failure, timeout, and so on.

    Retrying later may help.
    """


class InvalidOperation(StorageError, shared.InvalidOperationError):
    """The contract forbids an otherwise well-formed operation."""
