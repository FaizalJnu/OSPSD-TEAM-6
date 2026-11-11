"""Application entry point: builds the app and plugs the parts together.

This is the only place that decides which storage backend gets used. Run with:

    uv run --env-file .env uvicorn storage_service.main:create_app --factory
"""

from importlib.metadata import version

from cloud_storage_api.errors import StorageError as SharedStorageError
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from storage_service.config import Settings, load_settings
from storage_service.routers import delete, download, listing, metadata, move, upload
from storage_service.routers.error_handlers import (
    http_error_handler,
    internal_error_handler,
    remove_validation_responses,
    storage_error_handler,
    validation_error_handler,
)
from storage_service.service import FileService
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage
from storage_service.storage.s3 import S3Storage


def create_app(service: FileService | None = None) -> FastAPI:
    """Build the FastAPI app.

    Tests pass in a ready-made service (usually backed by InMemoryStorage).
    When ``service`` is left out, one is built from the environment settings.
    """
    if service is None:
        service = build_service(load_settings())
    app = FastAPI(title="Storage Service", version=version("storage-service"))
    app.state.file_service = service
    app.include_router(listing.router)
    app.include_router(upload.router)
    app.include_router(metadata.router)
    app.include_router(download.router)
    app.include_router(delete.router)
    app.include_router(move.router)
    app.add_exception_handler(SharedStorageError, storage_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    # Starlette's own errors (no route, wrong method, unreadable body), and bugs.
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
    remove_validation_responses(app)
    return app


def build_service(settings: Settings) -> FileService:
    return FileService(build_storage(settings), max_upload_bytes=settings.max_upload_bytes)


def build_storage(settings: Settings) -> StorageClient:
    if settings.backend == "memory":
        return InMemoryStorage()
    assert settings.s3 is not None, "load_settings guarantees s3 settings for the s3 backend"
    return S3Storage(
        endpoint=settings.s3.endpoint,
        region=settings.s3.region,
        bucket=settings.s3.bucket,
        access_key=settings.s3.access_key,
        secret_key=settings.s3.secret_key,
    )
