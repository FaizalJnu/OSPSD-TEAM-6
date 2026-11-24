"""Translate shared document storage errors at the workflow boundary."""

from cloud_storage_api import (
    ConflictError,
    DocumentStorage,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
    StorageError,
)

from meeting_prep.adapters.base import ErrorCode, Step, StepError


class DocumentStorageAdapter:
    def __init__(self, storage: DocumentStorage) -> None:
        self._storage = storage

    def create(self, step: Step, path: str, content: bytes) -> bool:
        try:
            self._storage.create(path, content)
        except ConflictError:
            return False
        except Exception as error:
            raise _translate(step, error, write=True) from None
        return True

    def replace(self, step: Step, path: str, content: bytes) -> None:
        try:
            self._storage.replace(path, content)
        except Exception as error:
            raise _translate(step, error, write=True) from None

    def download(self, step: Step, path: str) -> bytes:
        try:
            return self._storage.download(path)
        except Exception as error:
            raise _translate(step, error, write=False) from None

    def check_health(self) -> None:
        self._storage.check_health()


def _translate(step: Step, error: Exception, *, write: bool) -> StepError:
    provider_code = error.code if isinstance(error, StorageError) else type(error).__name__
    if isinstance(error, PermissionDeniedError):
        return StepError(
            step,
            "permission_denied",
            retryable=False,
            may_have_applied=False,
            provider_code=provider_code,
        )
    if isinstance(error, NotFoundError):
        return StepError(
            step,
            "run_record_invalid",
            retryable=False,
            may_have_applied=False,
            provider_code=provider_code,
        )
    if isinstance(error, (ProviderError, ProviderUnavailableError)):
        code: ErrorCode = (
            "provider_unavailable"
            if isinstance(error, ProviderUnavailableError)
            else "provider_error"
        )
        return StepError(
            step, code, retryable=True, may_have_applied=write, provider_code=provider_code
        )
    invalid = isinstance(error, (InvalidRequestError, InvalidOperationError))
    return StepError(
        step,
        "internal_error",
        retryable=False,
        may_have_applied=write and not invalid,
        provider_code=provider_code,
    )
