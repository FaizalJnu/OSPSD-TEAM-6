"""Contract tests: every storage backend must pass these same tests.

They check the rules written in ``storage/base.py``. The in-memory backend
always runs. The S3 backend runs only when real credentials are configured,
for example:

    uv run --env-file .env pytest tests/test_storage_contract.py
"""

import io
import os
import uuid
from collections.abc import Iterator

import pytest

from storage_service.config import load_settings
from storage_service.errors import FileNotFound
from storage_service.main import build_storage
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage

S3_CONFIGURED = os.environ.get("STORAGE_BACKEND") == "s3"
needs_s3 = pytest.mark.skipif(not S3_CONFIGURED, reason="set STORAGE_BACKEND=s3 and S3_* settings")


@pytest.fixture
def prefix() -> str:
    """A unique folder-like prefix per test, so runs never collide in a real bucket."""
    return f"contract-tests/{uuid.uuid4().hex}/"


@pytest.fixture(params=["memory", pytest.param("s3", marks=needs_s3)])
def storage(request, prefix) -> Iterator[StorageClient]:
    backend = InMemoryStorage() if request.param == "memory" else build_storage(load_settings())
    yield backend
    # Clean up whatever the test wrote. This matters for the real provider.
    for info in backend.list_files(prefix, 1000, None).files:
        backend.delete(info.key)


def put_bytes(storage: StorageClient, key: str, data: bytes = b"hello") -> None:
    storage.put(key, io.BytesIO(data), "text/plain")


def test_put_then_get_round_trips_the_bytes(storage, prefix):
    key = prefix + "hello.txt"
    data = b"hello \x00 world " * 10_000
    info = storage.put(key, io.BytesIO(data), "text/plain")
    assert info.key == key
    assert info.size == len(data)

    download = storage.get(key)
    assert b"".join(download.chunks) == data
    assert download.info.content_type == "text/plain"


def test_put_replaces_existing_contents(storage, prefix):
    key = prefix + "file.txt"
    put_bytes(storage, key, b"old")
    put_bytes(storage, key, b"new")
    assert b"".join(storage.get(key).chunks) == b"new"
    assert storage.stat(key).size == 3


def test_missing_key_raises_file_not_found(storage, prefix):
    with pytest.raises(FileNotFound):
        storage.stat(prefix + "missing.txt")
    with pytest.raises(FileNotFound):
        storage.get(prefix + "missing.txt")


def test_delete_of_a_missing_key_is_silent(storage, prefix):
    storage.delete(prefix + "missing.txt")


def test_delete_removes_the_file(storage, prefix):
    key = prefix + "gone.txt"
    put_bytes(storage, key)
    storage.delete(key)
    with pytest.raises(FileNotFound):
        storage.stat(key)


def test_list_is_sorted_paginated_and_has_no_content_type(storage, prefix):
    for name in ("c", "a", "b"):
        put_bytes(storage, prefix + name)

    first = storage.list_files(prefix, 2, None)
    assert [f.key for f in first.files] == [prefix + "a", prefix + "b"]
    assert first.next_cursor is not None

    second = storage.list_files(prefix, 2, first.next_cursor)
    assert [f.key for f in second.files] == [prefix + "c"]
    assert second.next_cursor is None
    assert all(f.content_type is None for f in first.files + second.files)
