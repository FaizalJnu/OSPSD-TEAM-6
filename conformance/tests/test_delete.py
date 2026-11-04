"""Delete: DELETE /files?path=<path>, files and whole folders (memo, "Delete")."""

from typing import Any

import httpx2

from conformance.tests.conftest import assert_error, create, metadata


def delete(api: httpx2.Client, path: str) -> Any:
    return api.delete("/files", params={"path": path})


def test_delete_returns_204_with_no_body_and_the_file_is_gone(api, root):
    create(api, root + "/file.txt")
    response = delete(api, root + "/file.txt")
    assert response.status_code == 204
    assert response.content == b""
    assert_error(metadata(api, root + "/file.txt"), 404, "not_found")


def test_deleting_a_folder_removes_everything_in_it(api, root):
    create(api, root + "/keep.txt")
    create(api, root + "/folder/a.txt")
    create(api, root + "/folder/sub/b.txt")
    assert delete(api, root + "/folder").status_code == 204
    assert_error(metadata(api, root + "/folder/a.txt"), 404, "not_found")
    assert_error(metadata(api, root + "/folder/sub/b.txt"), 404, "not_found")
    assert metadata(api, root + "/keep.txt").status_code == 200


def test_deleting_a_folder_spares_a_sibling_with_the_same_prefix(api, root):
    # A folder delete must not treat its path as a plain text prefix.
    create(api, root + "/data/a.txt")
    create(api, root + "/data-backup/a.txt")
    delete(api, root + "/data")
    assert metadata(api, root + "/data-backup/a.txt").status_code == 200


def test_deleting_a_missing_path_is_not_found(api, root):
    create(api, root + "/other.txt")
    assert_error(delete(api, root + "/missing.txt"), 404, "not_found")


def test_deleting_twice_is_not_found_the_second_time(api, root):
    create(api, root + "/file.txt")
    delete(api, root + "/file.txt")
    assert_error(delete(api, root + "/file.txt"), 404, "not_found")
