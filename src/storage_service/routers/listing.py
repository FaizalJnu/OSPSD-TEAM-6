"""List: ``GET /files?path=``."""

from typing import Annotated

from fastapi import APIRouter, Query

from storage_service.models import CommonFileInfo
from storage_service.routers.deps import Service
from storage_service.routers.error_handlers import error_responses
from storage_service.service import MAX_PATH_BYTES

router = APIRouter()


@router.get(
    "/files",
    summary="List a folder",
    responses=error_responses(
        {
            400: "invalid_request: malformed path.",
            403: "permission_denied: the provider denied the service access.",
            404: "not_found: nothing is stored under the folder.",
            502: "provider_error: the storage provider rejected the request.",
            503: "provider_unavailable: the storage provider could not be reached.",
        }
    ),
)
def list_files(
    service: Service,
    path: Annotated[
        str,
        Query(
            description=(
                "The folder's path, with or without a leading '/', such as /docs "
                f"(at most {MAX_PATH_BYTES} UTF-8 bytes, counting the leading '/'). "
                "Leave it out, or send '/', to list the root."
            )
        ),
    ] = "/",
) -> list[CommonFileInfo]:
    """Return the files and folders directly inside a folder, sorted by path.

    The whole folder comes back as one array: the service follows every provider
    page itself, so there is no cursor. Each entry's type is "file" or "folder". A
    folder entry has null size, modified_at and etag. content_type is always null
    here, because the provider's list call does not return it. Listing changes
    nothing.

    A folder exists only while a file is under it, so an empty or missing folder is
    404 not_found, and so is a file's path. The root is never 404: when nothing is
    stored it is an empty array.

    Expected failures use {"error": {"code": "...", "message": "..."}}.
    """
    return service.list_entries(path)
