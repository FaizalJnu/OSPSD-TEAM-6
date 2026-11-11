"""List: ``GET /files``."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Query

from storage_service.models import FileInfo
from storage_service.routers.deps import Service
from storage_service.routers.error_handlers import error_responses
from storage_service.service import MAX_KEY_BYTES, MAX_PAGE_SIZE

router = APIRouter()


@dataclass(frozen=True)
class ListResponse:
    """One page of files, as this route has always returned it (no folders)."""

    files: list[FileInfo]
    next_cursor: str | None


@router.get(
    "/files",
    summary="List files",
    responses=error_responses(
        {
            400: "invalid_request: limit is not 1 to 1000, or prefix is too long.",
            403: "permission_denied: the provider denied the service access.",
            502: "provider_error: the storage provider rejected the request.",
            503: "provider_unavailable: the storage provider could not be reached.",
        }
    ),
)
def list_files(
    service: Service,
    prefix: Annotated[
        str,
        Query(
            description=(
                f"Only list keys that start with this text (at most {MAX_KEY_BYTES} UTF-8 "
                "bytes). It is plain text, not a folder: 'docs' also matches 'docs2/a.txt'."
            )
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_SIZE, description="The most files to return in this page."),
    ] = 100,
    cursor: Annotated[
        str | None,
        Query(description="The next_cursor from the previous page, sent back unchanged."),
    ] = None,
) -> ListResponse:
    """Return one page of files, sorted by key, without changing anything.

    Keys at every depth under the prefix are included. To read every file, keep
    sending next_cursor back as cursor until it is null. A page can hold fewer than
    limit files and still have a next_cursor. content_type is always null here.

    Expected failures use {"error": "<type>", "detail": "<message>"}.
    """
    page = service.list_files(prefix=prefix, limit=limit, cursor=cursor)
    return ListResponse(files=page.files, next_cursor=page.next_cursor)
