"""List: ``GET /files``."""

from typing import Annotated

from fastapi import APIRouter, Query

from storage_service.models import FilePage
from storage_service.routers.deps import Service
from storage_service.service import MAX_PAGE_SIZE

router = APIRouter()


@router.get("/files")
def list_files(
    service: Service,
    prefix: str = "",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 100,
    cursor: str | None = None,
) -> FilePage:
    return service.list_files(prefix=prefix, limit=limit, cursor=cursor)
