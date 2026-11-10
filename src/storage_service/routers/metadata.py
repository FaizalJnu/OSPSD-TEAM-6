"""Metadata: ``GET /files/metadata?path=``."""

from fastapi import APIRouter

from storage_service.models import CommonFileInfo
from storage_service.routers.deps import PathQuery, Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


@router.get(
    "/files/metadata",
    summary="Read file metadata",
    responses=error_responses(
        {
            400: "invalid_request: missing or malformed path.",
            403: "permission_denied: the provider denied the service access.",
            404: "not_found: no file exists under the key.",
            502: "provider_error: the storage provider rejected the request.",
            503: "provider_unavailable: the storage provider could not be reached.",
        }
    ),
)
def get_metadata(path: PathQuery, service: Service) -> CommonFileInfo:
    """Return shared file info with null S3 id and UTC modification time.

    The canonical path is at most 1024 UTF-8 bytes including its leading slash, with no
    control characters, empty path segments, or '.' / '..' segments. Reading
    metadata does not download, create, replace, or delete a file. A repeated
    read may see new metadata if another caller changes the file.

    Expected failures use {"error": {"code": "...", "message": "..."}}.
    Fix invalid input or provider configuration before retrying; an unavailable
    provider may recover later. A missing file must be created before retrying.
    """
    return service.get_metadata(path)
