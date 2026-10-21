"""Errors this service raises on purpose.

These are plain Python exceptions with no HTTP in them, so the same errors work
for any caller: the HTTP API, a command-line tool, or an agent. ``routers/error_handlers.py`` is
the only place that turns them into HTTP status codes.
"""


class StorageError(Exception):
    """Base class for every error the service raises on purpose."""


class InvalidInput(StorageError):
    """The caller sent a key, size, or parameter that we do not accept."""


class FileNotFound(StorageError):
    """No file exists under the requested key."""


class FileAlreadyExists(StorageError):
    """A file already exists under the key the caller tried to create."""


class FileTooLarge(StorageError):
    """The upload is bigger than the configured limit."""


class ProviderError(StorageError):
    """The provider refused the request: bad credentials, missing bucket, and so on.

    Usually a configuration problem, which retrying will not fix. It can also be a
    provider-side failure that lasted through the client's own retries, so retrying
    later sometimes succeeds.
    """


class ProviderUnavailable(StorageError):
    """The provider could not be reached: network failure, timeout, and so on.

    Retrying later may help.
    """
