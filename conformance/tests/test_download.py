"""Download: returns the exact stored bytes (memo, "Download")."""

import pytest

from conformance.tests.conftest import ROUTES_QUESTION, assert_error, create

# Teams 1 and 3 use this route today. Team 6 uses GET /files/{key}.
pytestmark = pytest.mark.proposed(ROUTES_QUESTION)


@pytest.mark.parametrize(
    "data",
    [b"hello", b"", bytes(range(256)) * 4096],
    ids=["text", "empty", "binary-1MiB"],
)
def test_download_returns_the_exact_bytes(api, root, data):
    create(api, root + "/file.bin", data)
    response = api.get("/files/download", params={"path": root + "/file.bin"})
    assert response.status_code == 200
    assert response.content == data


def test_downloading_a_missing_file_is_not_found(api, root):
    response = api.get("/files/download", params={"path": root + "/missing.txt"})
    assert_error(response, 404, "not_found")
