"""Download: GET /files/{key}. Owner: Vikram Markali."""


def test_download_of_a_missing_file_is_404(client):
    response = client.get("/files/missing.txt")
    assert response.status_code == 404
    assert response.json()["error"] == "FileNotFound"
