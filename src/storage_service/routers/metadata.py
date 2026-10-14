"""Metadata: ``GET /metadata/{key}``."""

from fastapi import APIRouter

from storage_service.models import FileInfo
from storage_service.routers.deps import Service

router = APIRouter()


@router.get("/metadata/{key:path}")
def get_metadata(key: str, service: Service) -> FileInfo:
    return service.stat(key)
