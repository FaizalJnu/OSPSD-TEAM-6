"""Paths: with or without a leading /, always returned with one (memo, "Paths")."""

import pytest

from conformance.tests.conftest import assert_error, create, metadata, upload


def test_a_path_without_a_leading_slash_is_returned_with_one(api, root):
    info = create(api, root.lstrip("/") + "/notes.txt")
    assert info["path"] == root + "/notes.txt"
    assert info["name"] == "notes.txt"


def test_both_forms_name_the_same_file(api, root):
    create(api, root + "/notes.txt")
    response = metadata(api, root.lstrip("/") + "/notes.txt")
    assert response.status_code == 200
    assert response.json()["path"] == root + "/notes.txt"


@pytest.mark.parametrize(
    "bad",
    ["", "/", "{root}/", "{root}//a.txt", "{root}/./a.txt", "{root}/../a.txt", "{root}/.."],
)
def test_a_malformed_path_is_invalid_request(api, root, bad):
    response = upload(api, bad.format(root=root))
    assert_error(response, 400, "invalid_request")


def test_a_malformed_path_is_rejected_by_every_operation(api, root):
    bad = root + "/../a.txt"
    assert_error(metadata(api, bad), 400, "invalid_request")
    assert_error(api.get("/files/download", params={"path": bad}), 400, "invalid_request")
    assert_error(api.delete("/files", params={"path": bad}), 400, "invalid_request")
