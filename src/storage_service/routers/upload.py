"""Create and replace: ``POST /files`` and ``PUT /files``.

Both take a ``multipart/form-data`` body with two fields: ``path``, the file's path,
and ``file``, its contents. They return the shared file info, like Metadata and Move.

``POST /files/{key}`` and ``PUT /files/{key}`` are the routes from before the shared
contract. They stay for existing callers, marked deprecated: they take a key in the URL
and return the legacy file info, with ``key`` and ``last_modified``. Both pairs run the
same rules and log failures under the same names, ``create_file`` and ``replace_file``.
"""

import os

from fastapi import APIRouter, UploadFile

from storage_service.models import CommonFileInfo, FileInfo
from storage_service.routers.deps import PathForm, Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()

_TOO_LARGE = "file_too_large: the upload is larger than MAX_UPLOAD_BYTES."
_WRITE_FAILURES = {
    403: "permission_denied: the provider denied the service access.",
    502: (
        "provider_error: the storage provider rejected the request. "
        "The write may still have happened."
    ),
    503: (
        "provider_unavailable: the storage provider could not be reached. "
        "The write may still have happened."
    ),
}


@router.post(
    "/files",
    status_code=201,
    summary="Create a file",
    responses=error_responses(
        {
            400: (
                "invalid_request: the path is missing or violates a path rule, or the "
                "file form field is missing or cannot be read."
            ),
            409: "conflict: a file already exists at the path.",
            413: _TOO_LARGE,
            **_WRITE_FAILURES,
        }
    ),
)
def create_file(path: PathForm, file: UploadFile, service: Service) -> CommonFileInfo:
    """Store a new file at ``path``. Nothing is overwritten."""
    return service.create_at(path, file.file, _size_of(file))


@router.put(
    "/files",
    summary="Replace a file",
    responses=error_responses(
        {
            400: (
                "invalid_request: the path is missing or violates a path rule, or the "
                "file form field is missing or cannot be read."
            ),
            404: "not_found: no file exists at the path.",
            413: _TOO_LARGE,
            **_WRITE_FAILURES,
        }
    ),
)
def replace_file(path: PathForm, file: UploadFile, service: Service) -> CommonFileInfo:
    """Overwrite the contents of the file at ``path``. It must exist already."""
    return service.replace_at(path, file.file, _size_of(file))


@router.post(
    "/files/{key:path}",
    name="create_file",
    status_code=201,
    summary="Create a file by key (deprecated: use POST /files)",
    deprecated=True,
    responses=error_responses(
        {
            400: (
                "invalid_request: the key violates a key rule, or the file form field is "
                "missing or cannot be read."
            ),
            409: "conflict: a file already exists under the key.",
            413: _TOO_LARGE,
            **_WRITE_FAILURES,
        }
    ),
)
def create_file_by_key(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.create(key, file.file, _size_of(file))


@router.put(
    "/files/{key:path}",
    name="replace_file",
    summary="Replace a file by key (deprecated: use PUT /files)",
    deprecated=True,
    responses=error_responses(
        {
            400: (
                "invalid_request: the key violates a key rule, or the file form field is "
                "missing or cannot be read."
            ),
            404: "not_found: no file exists under the key.",
            413: _TOO_LARGE,
            **_WRITE_FAILURES,
        }
    ),
)
def replace_file_by_key(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.replace(key, file.file, _size_of(file))


def _size_of(upload: UploadFile) -> int:
    """Measure an uploaded file. FastAPI has already saved it to a temp file."""
    stream = upload.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size
