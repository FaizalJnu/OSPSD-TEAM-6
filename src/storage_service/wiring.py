"""Builds the storage backend and the service from settings, without a web framework.

This is the only place that decides which storage backend gets used. ``main.py``
builds the HTTP app on top of ``build_service``. Programs that only need the
shared ``DocumentStorage`` interface, such as other teams' services, call
``document_storage_from_env`` and never import FastAPI.
"""

import os
from collections.abc import Mapping

from storage_service.config import Settings, load_settings
from storage_service.service import FileService
from storage_service.shared_storage import SharedDocumentStorage
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage
from storage_service.storage.s3 import S3Storage


def document_storage_from_env(env: Mapping[str, str] = os.environ) -> SharedDocumentStorage:
    """Return the shared ``DocumentStorage`` adapter, configured from ``env``.

    It reads the same settings as the HTTP service (see ``.env.example``) and
    raises ``ConfigError`` naming a missing or invalid setting, never its value.
    """
    return SharedDocumentStorage(build_service(load_settings(env)))


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
