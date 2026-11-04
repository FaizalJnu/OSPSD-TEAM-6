"""Move: PATCH /files?path=<from> with {"new_path": "<to>"} (unified #5)."""

from typing import Any

import httpx2
import pytest

from conformance.tests.conftest import MOVE_ISSUE, assert_error, create, metadata

pytestmark = pytest.mark.proposed(MOVE_ISSUE)


def move(api: httpx2.Client, path: str, new_path: str) -> Any:
    return api.patch("/files", params={"path": path}, json={"new_path": new_path})


def test_move_returns_the_file_info_at_the_new_path(api, root):
    create(api, root + "/old.txt", b"12345")
    response = move(api, root + "/old.txt", root + "/new.txt")
    assert response.status_code == 200
    info = response.json()
    assert info["path"] == root + "/new.txt"
    assert info["name"] == "new.txt"
    assert info["size"] == 5


def test_move_leaves_nothing_at_the_old_path_and_keeps_the_bytes(api, root):
    create(api, root + "/old.txt", b"contents")
    move(api, root + "/old.txt", root + "/sub/new.txt")
    assert_error(metadata(api, root + "/old.txt"), 404, "not_found")
    download = api.get("/files/download", params={"path": root + "/sub/new.txt"})
    assert download.content == b"contents"


def test_moving_onto_an_existing_file_is_a_conflict_and_changes_nothing(api, root):
    create(api, root + "/a.txt", b"a")
    create(api, root + "/b.txt", b"b")
    assert_error(move(api, root + "/a.txt", root + "/b.txt"), 409, "conflict")
    assert api.get("/files/download", params={"path": root + "/a.txt"}).content == b"a"
    assert api.get("/files/download", params={"path": root + "/b.txt"}).content == b"b"


@pytest.mark.parametrize("new_name", ["file.txt", "FILE.txt"], ids=["same", "case-only"])
def test_moving_to_the_same_path_or_only_changing_case_is_invalid(api, root, new_name):
    create(api, root + "/file.txt")
    response = move(api, root + "/file.txt", root + "/" + new_name)
    assert_error(response, 422, "invalid_operation")
    assert metadata(api, root + "/file.txt").status_code == 200


def test_moving_a_folder_is_invalid(api, root):
    create(api, root + "/folder/inner.txt")
    response = move(api, root + "/folder", root + "/elsewhere")
    assert_error(response, 422, "invalid_operation")


def test_moving_a_missing_file_is_not_found(api, root):
    create(api, root + "/other.txt")
    assert_error(move(api, root + "/missing.txt", root + "/new.txt"), 404, "not_found")


@pytest.mark.parametrize("body", [{}, {"new_path": ""}, {"new_path": "/a/../b"}, "not json"])
def test_a_missing_or_malformed_new_path_is_invalid_request(api, root, body):
    create(api, root + "/file.txt")
    if isinstance(body, str):
        response = api.patch(
            "/files",
            params={"path": root + "/file.txt"},
            content=body,
            headers={"Content-Type": "application/json"},
        )
    else:
        response = api.patch("/files", params={"path": root + "/file.txt"}, json=body)
    assert_error(response, 400, "invalid_request")
