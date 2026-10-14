"""Metadata: ``GET /metadata/{key}``."""

from fastapi import APIRouter

from storage_service.models import FileInfo
from storage_service.routers.deps import Service

router = APIRouter()


@router.get(
    "/metadata/{key:path}",
    summary="Read file metadata",
    responses={
        400: {"description": "InvalidInput: the decoded key violates a key rule."},
        404: {"description": "FileNotFound: no file exists under the key."},
        502: {"description": "ProviderError: the storage provider rejected the request."},
        503: {"description": "ProviderUnavailable: the storage provider could not be reached."},
    },
)
def get_metadata(key: str, service: Service) -> FileInfo:
    """Return key, byte size, stored content type, unquoted ETag, and UTC modification time.

    The decoded key must be non-empty and at most 1024 UTF-8 bytes, with no
    control characters, empty path segments, or '.' / '..' segments. Reading
    metadata does not download, create, replace, or delete a file. A repeated
    read may see new metadata if another caller changes the file.

    Expected failures use {"error": "<type>", "detail": "<message>"}.
    Fix invalid input or provider configuration before retrying; an unavailable
    provider may recover later. A missing file must be created before retrying.
    """
    return service.stat(key)
