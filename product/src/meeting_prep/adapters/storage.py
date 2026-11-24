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

DOCUMENT_BYTES = 32 * 1024


class DocumentReadError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DocumentStorageAdapter:
    def __init__(self, storage: DocumentStorage, *, prefix: str = "") -> None:
        self._storage = storage
        self._prefix = prefix

    def for_user(self, user_id: str) -> DocumentStorageAdapter:
        # Only the identity store supplies these UUIDs.
        return DocumentStorageAdapter(self._storage, prefix=f"/users/{user_id}")

    def create(self, step: Step, path: str, content: bytes) -> bool:
        try:
            self._storage.create(self._prefix + path, content)
        except ConflictError:
            return False
        except Exception as error:
            raise _translate(step, error, write=True) from None
        return True

    def replace(self, step: Step, path: str, content: bytes) -> None:
        try:
            self._storage.replace(self._prefix + path, content)
        except Exception as error:
            raise _translate(step, error, write=True) from None

    def download(self, step: Step, path: str) -> bytes:
        try:
            return self._storage.download(self._prefix + path)
        except Exception as error:
            raise _translate(step, error, write=False) from None

    def check_health(self) -> None:
        self._storage.check_health()

    def read_text(self, path: str) -> str:
        if (
            not path.startswith("/")
            or len(path.encode("utf-8")) > 900
            or any(part in {"", ".", ".."} for part in path[1:].split("/"))
            or any(char in path for char in "\\%")
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            raise DocumentReadError("invalid_request")
        if path.split("/")[1] in {"users", "review-runs"}:
            raise DocumentReadError("not_found")
        data = bytearray()
        try:
            with self._storage.open_download(self._prefix + path) as stream:
                size = stream.info.size
                if size is not None and size > DOCUMENT_BYTES:
                    raise DocumentReadError("document_too_large")
                for chunk in stream.chunks(DOCUMENT_BYTES):
                    if len(data) + len(chunk) > DOCUMENT_BYTES:
                        raise DocumentReadError("document_too_large")
                    data.extend(chunk)
            return data.decode("utf-8")
        except NotFoundError:
            raise DocumentReadError("not_found") from None
        except UnicodeDecodeError:
            raise DocumentReadError("unsupported_document") from None
        except DocumentReadError:
            raise
        except Exception as error:
            raise _translate("write_agenda", error, write=False) from None


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
