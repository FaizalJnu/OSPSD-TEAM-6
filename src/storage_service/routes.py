"""The HTTP layer: URLs, request parsing, responses, and error-to-status mapping.

Routes stay thin. Each one unpacks the HTTP request, calls one FileService
method, and shapes the response. All decisions live in the service.

    GET    /files              list files (query: prefix, limit, cursor)
    POST   /files/{key}        create a file (multipart form field named "file")
    PUT    /files/{key}        replace an existing file (same form field)
    GET    /files/{key}        download a file
    DELETE /files/{key}        delete a file
    GET    /metadata/{key}     a file's info as JSON
"""

import logging
import os
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from storage_service.errors import (
    FileAlreadyExists,
    FileNotFound,
    FileTooLarge,
    InvalidInput,
    ProviderError,
    ProviderUnavailable,
    StorageError,
)
from storage_service.models import FileInfo, FilePage
from storage_service.service import MAX_PAGE_SIZE, FileService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_service(request: Request) -> FileService:
    """Hand each route the FileService that ``main.create_app`` stored on the app."""
    service: FileService = request.app.state.file_service
    return service


# Shorthand for route signatures: "this parameter is the FileService".
Service = Annotated[FileService, Depends(get_service)]


@router.get("/files")
def list_files(
    service: Service,
    prefix: str = "",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 100,
    cursor: str | None = None,
) -> FilePage:
    return service.list_files(prefix=prefix, limit=limit, cursor=cursor)


@router.post("/files/{key:path}", status_code=201)
def create_file(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.create(key, file.file, _size_of(file))


@router.put("/files/{key:path}")
def replace_file(key: str, file: UploadFile, service: Service) -> FileInfo:
    return service.replace(key, file.file, _size_of(file))


@router.get("/files/{key:path}")
def download_file(key: str, service: Service) -> StreamingResponse:
    download = service.download(key)
    info = download.info
    filename = info.key.rsplit("/", 1)[-1]
    headers = {
        "Content-Length": str(info.size),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "ETag": f'"{info.etag}"',
        # Tell browsers to trust our Content-Type instead of guessing from the bytes.
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(download.chunks, media_type=info.content_type, headers=headers)


@router.delete("/files/{key:path}", status_code=204)
def delete_file(key: str, service: Service) -> Response:
    service.delete(key)
    return Response(status_code=204)


@router.get("/metadata/{key:path}")
def get_metadata(key: str, service: Service) -> FileInfo:
    return service.stat(key)


def _size_of(upload: UploadFile) -> int:
    """Measure an uploaded file. FastAPI has already saved it to a temp file."""
    stream = upload.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


# How each of our errors appears over HTTP. Anything not listed becomes a 500.
_STATUS_FOR_ERROR: dict[type[StorageError], int] = {
    InvalidInput: 400,
    FileNotFound: 404,
    FileAlreadyExists: 409,
    FileTooLarge: 413,
    ProviderError: 502,
    ProviderUnavailable: 503,
}


def storage_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a StorageError raised anywhere below the routes into a JSON error response."""
    status = next(
        (code for error_type, code in _STATUS_FOR_ERROR.items() if isinstance(exc, error_type)),
        500,
    )
    if status >= 500:
        # Server-side problems get logged with the full chain of causes for whoever
        # runs the service. The client only sees our short, safe message.
        logger.error("%s %s failed", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status, content={"error": type(exc).__name__, "detail": str(exc)}
    )
