"""Contract tests: every storage backend must pass these same tests.

They check the rules written in ``storage/base.py``. The in-memory backend runs
in the fast suite. The S3 backend is marked ``provider`` and runs against the
bucket in ``.env`` only when asked for:

    uv run --env-file .env pytest -m provider
"""

import io
import uuid
from collections.abc import Iterator

import pytest

from storage_service.errors import FileNotFound, InvalidInput
from storage_service.main import build_storage
from storage_service.storage.base import StorageClient
from storage_service.storage.memory import InMemoryStorage
from tests.conftest import delete_everything_under, load_provider_settings


@pytest.fixture
def prefix() -> str:
    """A unique folder-like prefix per test, so runs never collide in a real bucket."""
    return f"contract-tests/{uuid.uuid4().hex}/"


@pytest.fixture(params=["memory", pytest.param("s3", marks=pytest.mark.provider)])
def storage(request, prefix) -> Iterator[StorageClient]:
    if request.param == "memory":
        backend: StorageClient = InMemoryStorage()
    else:
        backend = build_storage(load_provider_settings())
    yield backend
    # Clean up whatever the test wrote. This matters for the real provider.
    delete_everything_under(backend, prefix)


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
    with pytest.raises(FileNotFound):
        storage.copy(prefix + "missing.txt", prefix + "copy.txt")


def test_copy_makes_a_second_file_and_keeps_the_original(storage, prefix):
    source, dest = prefix + "a.txt", prefix + "b.txt"
    put_bytes(storage, source, b"copied bytes")

    info = storage.copy(source, dest)

    assert info.key == dest
    assert info.size == len(b"copied bytes")
    assert b"".join(storage.get(dest).chunks) == b"copied bytes"
    assert storage.stat(dest).content_type == "text/plain"
    assert b"".join(storage.get(source).chunks) == b"copied bytes"


def test_delete_of_a_missing_key_is_silent(storage, prefix):
    storage.delete(prefix + "missing.txt")


def test_check_health_of_working_storage_returns_nothing(storage):
    assert storage.check_health() is None


def test_delete_removes_the_file(storage, prefix):
    key = prefix + "gone.txt"
    put_bytes(storage, key)
    storage.delete(key)
    with pytest.raises(FileNotFound):
        storage.stat(key)


def test_delete_many_removes_the_keys_and_ignores_missing_ones(storage, prefix):
    for name in ("a", "sub/b", "keep"):
        put_bytes(storage, prefix + name)

    failed = storage.delete_many([prefix + "a", prefix + "sub/b", prefix + "missing"])

    assert failed == []
    for name in ("a", "sub/b"):
        with pytest.raises(FileNotFound):
            storage.stat(prefix + name)
    assert storage.stat(prefix + "keep").key == prefix + "keep"


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


def test_list_with_a_cursor_this_backend_did_not_produce_is_invalid_input(storage, prefix):
    put_bytes(storage, prefix + "a")

    with pytest.raises(InvalidInput):
        storage.list_files(prefix, 2, "garbage")


def test_list_with_a_cursor_from_another_prefix_is_invalid_input(storage, prefix):
    for name in ("a", "b", "c"):
        put_bytes(storage, prefix + "docs/" + name)
    cursor = storage.list_files(prefix + "docs/", 2, None).next_cursor
    assert cursor is not None

    # "other/" sorts before "docs/a", so a provider that just continued from the
    # cursor's position would answer with an empty page instead of an error.
    with pytest.raises(InvalidInput):
        storage.list_files(prefix + "other/", 2, cursor)


def test_list_matches_the_prefix_as_text_at_every_depth_in_byte_order(storage, prefix):
    for name in ("docs/é.txt", "docs/sub/b.txt", "docs2/c.txt", "docs/a.txt", "docs/B.txt"):
        put_bytes(storage, prefix + name)

    page = storage.list_files(prefix + "docs/", 10, None)

    # docs2/ is a look-alike, not a match. Uppercase sorts before lowercase, and
    # non-ASCII after ASCII.
    expected = ("docs/B.txt", "docs/a.txt", "docs/sub/b.txt", "docs/é.txt")
    assert [f.key for f in page.files] == [prefix + name for name in expected]


def test_list_with_a_delimiter_returns_direct_files_and_subfolders(storage, prefix):
    for name in ("docs/a.txt", "docs/sub/b.txt", "docs/sub/deeper/c.txt", "docs/z/d.txt"):
        put_bytes(storage, prefix + name)
    put_bytes(storage, prefix + "docs2/e.txt")  # a look-alike, not inside docs/

    page = storage.list_files(prefix + "docs/", 10, None, delimiter="/")

    assert [f.key for f in page.files] == [prefix + "docs/a.txt"]
    assert page.folders == [prefix + "docs/sub/", prefix + "docs/z/"]
    assert page.next_cursor is None


def test_list_with_a_delimiter_pages_over_files_and_folders_once_each(storage, prefix):
    for name in ("a.txt", "b/x.txt", "b/y.txt", "c.txt", "d/z.txt"):
        put_bytes(storage, prefix + name)

    files: list[str] = []
    folders: list[str] = []
    cursor = None
    for _ in range(10):
        page = storage.list_files(prefix, 1, cursor, delimiter="/")
        assert len(page.files) + len(page.folders) <= 1
        files += [f.key for f in page.files]
        folders += page.folders
        cursor = page.next_cursor
        if cursor is None:
            break

    assert files == [prefix + "a.txt", prefix + "c.txt"]
    assert folders == [prefix + "b/", prefix + "d/"]
