"""Create and replace: ``POST /files/{key}`` and ``PUT /files/{key}``."""

import os

from fastapi import APIRouter, UploadFile

from storage_service.models import FileInfo
from storage_service.routers.deps import Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


@router.post(
    "/files/{key:path}",
    status_code=201,
    responses=error_responses(
        {
            400: (
                "InvalidInput: the key violates a key rule, or the file form field is "
                "missing or cannot be read."
            ),
            403: "AccessDenied: the provider denied the service access.",
            409: "FileAlreadyExists: a file already exists under the key.",
            413: "FileTooLarge: the upload is larger than MAX_UPLOAD_BYTES.",
            502: (
                "ProviderError: the storage provider rejected the request. "
                "The write may still have happened."
            ),
            503: (
                "ProviderUnavailable: the storage provider could not be reached. "
                "The write may still have happened."
            ),
        }
    ),
)
def create_file(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.create(key, file.file, _size_of(file))


@router.put(
    "/files/{key:path}",
    responses=error_responses(
        {
            400: (
                "InvalidInput: the key violates a key rule, or the file form field is "
                "missing or cannot be read."
            ),
            403: "AccessDenied: the provider denied the service access.",
            404: "FileNotFound: no file exists under the key.",
            413: "FileTooLarge: the upload is larger than MAX_UPLOAD_BYTES.",
            502: (
                "ProviderError: the storage provider rejected the request. "
                "The write may still have happened."
            ),
            503: (
                "ProviderUnavailable: the storage provider could not be reached. "
                "The write may still have happened."
            ),
        }
    ),
)
def replace_file(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.replace(key, file.file, _size_of(file))


def _size_of(upload: UploadFile) -> int:
    """Measure an uploaded file. FastAPI has already saved it to a temp file."""
    stream = upload.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size
