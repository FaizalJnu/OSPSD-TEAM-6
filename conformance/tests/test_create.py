"""Create: POST /files with the form fields file and path (memo, "Create")."""

import pytest

from conformance.tests.conftest import ERRORS_ISSUE, assert_error, create, upload


def test_create_returns_201_and_the_file_info(api, root):
    response = upload(api, root + "/report.pdf", b"%PDF-1.7 content")
    assert response.status_code == 201
    info = response.json()
    assert info["path"] == root + "/report.pdf"
    assert info["name"] == "report.pdf"
    assert info["size"] == len(b"%PDF-1.7 content")


def test_create_accepts_an_empty_file(api, root):
    assert create(api, root + "/empty.txt", b"")["size"] == 0


def test_create_makes_the_parent_folders(api, root):
    create(api, root + "/a/b/c.txt")
    assert api.get("/files", params={"path": root + "/a/b"}).status_code == 200


@pytest.mark.proposed(ERRORS_ISSUE)
def test_creating_an_existing_file_is_a_conflict_and_keeps_the_old_contents(api, root):
    create(api, root + "/file.txt", b"old")
    assert_error(upload(api, root + "/file.txt", b"new"), 409, "conflict")
    download = api.get("/files/download", params={"path": root + "/file.txt"})
    assert download.content == b"old"


@pytest.mark.parametrize("missing", ["file", "path"])
def test_a_missing_form_field_is_invalid_request(api, root, missing):
    data = {} if missing == "path" else {"path": root + "/a.txt"}
    files = {} if missing == "file" else {"file": ("f", b"x")}
    response = api.post("/files", data=data, files=files or None)
    assert_error(response, 400, "invalid_request")
