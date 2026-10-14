"""Create and replace: ``POST /files/{key}`` and ``PUT /files/{key}``."""

import os

from fastapi import APIRouter, UploadFile

from storage_service.models import FileInfo
from storage_service.routers.deps import Service

router = APIRouter()


@router.post("/files/{key:path}", status_code=201)
def create_file(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.create(key, file.file, _size_of(file))


@router.put("/files/{key:path}")
def replace_file(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.replace(key, file.file, _size_of(file))


def _size_of(upload: UploadFile) -> int:
    """Measure an uploaded file. FastAPI has already saved it to a temp file."""
    stream = upload.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size
