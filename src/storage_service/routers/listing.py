"""List: ``GET /files``."""

from typing import Annotated

from fastapi import APIRouter, Query

from storage_service.models import FilePage
from storage_service.routers.deps import Service
from storage_service.service import MAX_KEY_BYTES, MAX_PAGE_SIZE

router = APIRouter()


@router.get(
    "/files",
    summary="List files",
    responses={
        400: {"description": "InvalidInput: limit is not 1 to 1000, or prefix is too long."},
        502: {"description": "ProviderError: the storage provider rejected the request."},
        503: {"description": "ProviderUnavailable: the storage provider could not be reached."},
    },
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
) -> FilePage:
    """Return one page of files, sorted by key, without changing anything.

    Keys at every depth under the prefix are included. To read every file, keep
    sending next_cursor back as cursor until it is null. A page can hold fewer than
    limit files and still have a next_cursor. content_type is always null here.

    Expected failures use {"error": "<type>", "detail": "<message>"}.
    """
    return service.list_files(prefix=prefix, limit=limit, cursor=cursor)
