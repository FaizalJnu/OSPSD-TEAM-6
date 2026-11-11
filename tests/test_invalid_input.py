"""Invalid input always returns 400 InvalidInput, even when FastAPI rejects it first.

FastAPI checks types, ranges, and required fields before our code runs. These
tests make sure those rejections use our error format, like every other error.
"""

from fastapi.testclient import TestClient


def test_upload_without_file_field_returns_400_and_stores_nothing(client: TestClient) -> None:
    response = client.post("/files/notes.txt")

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["message"].startswith("file: ")
    assert client.get("/files/metadata?path=notes.txt").status_code == 404
