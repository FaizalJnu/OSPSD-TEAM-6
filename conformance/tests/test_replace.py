"""Replace: PUT /files with the same form fields as create (memo, "Replace")."""

from conformance.tests.conftest import assert_error, create, metadata, upload


def test_replace_returns_200_and_the_new_file_info(api, root):
    create(api, root + "/file.txt", b"old")
    response = upload(api, root + "/file.txt", b"new contents", method="PUT")
    assert response.status_code == 200
    info = response.json()
    assert info["path"] == root + "/file.txt"
    assert info["size"] == len(b"new contents")


def test_replace_changes_the_downloaded_bytes(api, root):
    create(api, root + "/file.txt", b"old")
    upload(api, root + "/file.txt", b"new", method="PUT")
    assert api.get("/files/download", params={"path": root + "/file.txt"}).content == b"new"


def test_replacing_a_missing_file_is_not_found_and_creates_nothing(api, root):
    create(api, root + "/other.txt")  # so the folder exists and teardown has work to do
    assert_error(upload(api, root + "/missing.txt", method="PUT"), 404, "not_found")
    assert_error(metadata(api, root + "/missing.txt"), 404, "not_found")
