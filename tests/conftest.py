"""Fixtures and helpers shared by every test file.

Three ways to reach storage, from fastest to slowest:

* ``client``: the HTTP API over in-memory storage. No network. Most tests use this.
* ``stubbed_s3``: the real ``S3Storage`` with botocore's Stubber in front of its
  client, for testing how provider responses and errors are translated. No network.
* ``provider_client``: the HTTP API wired exactly like production, against the
  bucket in ``.env``. Only for tests marked ``provider``, which the fast suite skips:

      uv run --env-file .env pytest -m provider
"""

import uuid
from collections.abc import Iterator
from typing import NamedTuple

import pytest
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from storage_service.config import ConfigError, Settings, load_settings
from storage_service.main import build_storage, create_app
from storage_service.service import FileService
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage
from storage_service.storage.s3 import S3Storage

MAX_UPLOAD_BYTES = 1024


@pytest.fixture
def client() -> TestClient:
    """A client for a fresh app with empty in-memory storage, so tests never share state."""
    service = FileService(InMemoryStorage(), max_upload_bytes=MAX_UPLOAD_BYTES)
    return TestClient(create_app(service))


def send_file(client: TestClient, method: str, key: str, data: bytes):
    return client.request(method, f"/files/{key}", files={"file": ("upload", data)})


def load_provider_settings() -> Settings:
    """Settings for a test that needs a real bucket.

    Fails instead of skipping: a provider test that quietly ran against the
    in-memory backend would report a real-provider check that never happened.
    """
    hint = "provider tests need STORAGE_BACKEND=s3 and the S3_* settings in .env"
    try:
        settings = load_settings()
    except ConfigError as err:
        pytest.fail(f"{hint} ({err})")
    if settings.backend != "s3":
        pytest.fail(f"{hint} (STORAGE_BACKEND is {settings.backend!r})")
    return settings


def delete_everything_under(storage: StorageClient, prefix: str) -> None:
    """Delete every file under ``prefix``, following every page of the listing.

    Used to clean up after provider tests. A page can be short, or even empty, and
    still have a cursor, so stop only when there is no cursor.
    """
    keys: list[str] = []
    cursor: str | None = None
    while True:
        page = storage.list_files(prefix, 1000, cursor)
        keys += [info.key for info in page.files]
        cursor = page.next_cursor
        if cursor is None:
            break
    for key in keys:  # list everything first, so deleting cannot disturb the cursor
        storage.delete(key)


@pytest.fixture
def provider_prefix() -> str:
    """A unique folder-like prefix per test, so runs never collide in a real bucket."""
    return f"api-tests/{uuid.uuid4().hex}/"


@pytest.fixture
def provider_client(provider_prefix: str) -> Iterator[TestClient]:
    """A client for the app as production builds it, against the bucket in ``.env``.

    Put every key under ``provider_prefix``: everything there is deleted afterwards,
    even when the test fails.
    """
    settings = load_provider_settings()
    with TestClient(create_app()) as client:
        yield client
    # Clean up through a separate storage client, so cleanup still works when the
    # API under test is broken.
    delete_everything_under(build_storage(settings), provider_prefix)


class StubbedS3(NamedTuple):
    storage: S3Storage
    stubber: Stubber


@pytest.fixture
def stubbed_s3() -> Iterator[StubbedS3]:
    """An ``S3Storage`` whose provider calls are answered by botocore's Stubber.

    Queue each expected call with ``stubber.add_response`` or
    ``stubber.add_client_error``, then call the storage method. A call with nothing
    queued fails the test instead of reaching the network, and a queued response
    that was never used fails it too.
    """
    storage = S3Storage(
        endpoint="https://s3.example.invalid",
        region="us-east-1",
        bucket="test-bucket",
        access_key="test-access-key",
        secret_key="test-secret-key",
    )
    # The Stubber has to wrap the boto3 client itself, which S3Storage keeps private.
    with Stubber(storage._client) as stubber:
        yield StubbedS3(storage, stubber)
        stubber.assert_no_pending_responses()
