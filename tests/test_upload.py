"""Create and replace: POST and PUT /files/{key}. Owner: Debasmith Mandal."""

from tests.conftest import MAX_UPLOAD_BYTES, send_file


def test_upload_then_download_returns_identical_bytes(client):
    data = b"\x89PNG not really an image \x00\xff"
    created = send_file(client, "POST", "photos/cat.png", data)
    assert created.status_code == 201
    assert created.json()["size"] == len(data)

    downloaded = client.get("/files/photos/cat.png")
    assert downloaded.status_code == 200
    assert downloaded.content == data
    assert downloaded.headers["content-type"] == "image/png"


def test_create_refuses_to_overwrite(client):
    send_file(client, "POST", "notes.txt", b"first")
    second = send_file(client, "POST", "notes.txt", b"second")
    assert second.status_code == 409
    assert second.json()["error"] == "FileAlreadyExists"
    assert client.get("/files/notes.txt").content == b"first"


def test_replace_overwrites_an_existing_file(client):
    send_file(client, "POST", "notes.txt", b"first")
    assert send_file(client, "PUT", "notes.txt", b"second").status_code == 200
    assert client.get("/files/notes.txt").content == b"second"


def test_replace_of_a_missing_file_is_404(client):
    assert send_file(client, "PUT", "missing.txt", b"data").status_code == 404


def test_upload_over_the_limit_is_413(client):
    too_big = b"x" * (MAX_UPLOAD_BYTES + 1)
    assert send_file(client, "POST", "big.bin", too_big).status_code == 413
    assert client.get("/files/big.bin").status_code == 404


def test_invalid_key_is_400(client):
    response = send_file(client, "POST", "a//b.txt", b"data")
    assert response.status_code == 400
    assert response.json()["error"] == "InvalidInput"
