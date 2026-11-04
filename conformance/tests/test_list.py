"""List: GET /files?path=<folder>, the direct children in one response (unified #3)."""

from typing import Any

import httpx2
import pytest

from conformance.tests.conftest import FOLDERS_QUESTION, LIST_ISSUE, assert_error, create

pytestmark = pytest.mark.proposed(LIST_ISSUE)


def list_folder(api: httpx2.Client, folder: str) -> Any:
    return api.get("/files", params={"path": folder})


def test_list_returns_the_direct_children_sorted_by_path(api, root):
    for name in ["b.txt", "a.txt", "c.txt"]:
        create(api, f"{root}/docs/{name}")
    response = list_folder(api, root + "/docs")
    assert response.status_code == 200
    assert [entry["path"] for entry in response.json()] == [
        f"{root}/docs/a.txt",
        f"{root}/docs/b.txt",
        f"{root}/docs/c.txt",
    ]


def test_list_is_one_level_and_includes_folders_once(api, root):
    create(api, root + "/top.txt")
    create(api, root + "/sub/one.txt")
    create(api, root + "/sub/deeper/two.txt")
    paths = [entry["path"] for entry in list_folder(api, root).json()]
    assert paths == [root + "/sub", root + "/top.txt"]


def test_list_entries_are_file_info(api, root):
    created = create(api, root + "/file.txt", b"12345")
    [entry] = list_folder(api, root).json()
    for field in ["id", "name", "path", "size"]:
        assert entry[field] == created[field]


@pytest.mark.proposed(FOLDERS_QUESTION)
def test_list_marks_files_and_folders(api, root):
    create(api, root + "/file.txt")
    create(api, root + "/sub/inner.txt")
    types = {entry["name"]: entry["type"] for entry in list_folder(api, root).json()}
    assert types == {"file.txt": "file", "sub": "folder"}


def test_list_returns_every_entry_in_one_response(api, root):
    # A plain array: no cursor or page fields. Crossing a provider page (1000 keys on S3)
    # would take too long against a real service, so 30 files only checks the shape.
    for number in range(30):
        create(api, f"{root}/many/{number:03}.txt", b"")
    entries = list_folder(api, root + "/many").json()
    assert isinstance(entries, list)
    assert len(entries) == 30


def test_listing_a_missing_folder_is_not_found(api, root):
    assert_error(list_folder(api, root + "/missing"), 404, "not_found")


def test_listing_with_a_malformed_path_is_invalid_request(api, root):
    assert_error(list_folder(api, root + "/../x"), 400, "invalid_request")
