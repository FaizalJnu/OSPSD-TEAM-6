"""The cleanup helper that provider tests rely on to leave the bucket empty."""

import io

from storage_service.models import FilePage
from storage_service.storage.memory import InMemoryStorage
from tests.conftest import delete_everything_under
from tests.fakes import FakeStorage


def test_cleanup_deletes_more_than_one_page_of_files():
    storage = InMemoryStorage()
    for n in range(1001):
        storage.put(f"tests/{n:04}.txt", io.BytesIO(b"x"), "text/plain")

    delete_everything_under(storage, "tests/")

    assert storage.list_files("tests/", 1000, None).files == []


class _ShortFirstPage(FakeStorage):
    """Returns an empty first page with a cursor, which the List contract allows."""

    def list_files(
        self, prefix: str, limit: int, cursor: str | None, delimiter: str | None = None
    ) -> FilePage:
        if cursor is None:
            return FilePage(files=[], next_cursor="page-2")
        return super().list_files(prefix, limit, None, delimiter)


def test_cleanup_follows_the_cursor_past_an_empty_page():
    storage = _ShortFirstPage()
    storage.put("tests/a.txt", io.BytesIO(b"x"), "text/plain")

    delete_everything_under(storage, "tests/")

    assert ("delete", "tests/a.txt") in storage.calls
