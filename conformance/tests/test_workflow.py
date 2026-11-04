"""The consumer workflow from the memo, run unchanged against every service."""

from conformance.tests.conftest import assert_error, metadata


def test_consumer_workflow(api, root):
    data = b"quarterly report\n" * 1000
    path = root + "/reports/q3.txt"
    new_path = root + "/archive/q3-final.txt"

    # Upload a file.
    created = api.post("/files", data={"path": path}, files={"file": ("q3.txt", data)})
    assert created.status_code == 201, created.text

    # Read its metadata.
    info = metadata(api, path)
    assert info.status_code == 200
    assert info.json()["size"] == len(data)

    # Download it and compare the bytes.
    download = api.get("/files/download", params={"path": path})
    assert download.status_code == 200
    assert download.content == data

    # List its folder.
    listing = api.get("/files", params={"path": root + "/reports"})
    assert listing.status_code == 200
    assert [entry["path"] for entry in listing.json()] == [path]

    # Move it.
    moved = api.patch("/files", params={"path": path}, json={"new_path": new_path})
    assert moved.status_code == 200, moved.text
    assert moved.json()["path"] == new_path

    # Read its metadata at the new path.
    info = metadata(api, new_path)
    assert info.status_code == 200
    assert info.json()["size"] == len(data)
    assert_error(metadata(api, path), 404, "not_found")

    # Delete it.
    assert api.delete("/files", params={"path": new_path}).status_code == 204

    # Confirm that metadata now returns 404.
    assert_error(metadata(api, new_path), 404, "not_found")
