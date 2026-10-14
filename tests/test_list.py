"""List: GET /files. Owner: Prateek Saxena."""

from tests.conftest import send_file


def test_list_pages_through_files_with_a_cursor(client):
    for name in ("a.txt", "b.txt", "c.txt"):
        send_file(client, "POST", f"docs/{name}", b"x")
    send_file(client, "POST", "other/d.txt", b"x")

    first = client.get("/files", params={"prefix": "docs/", "limit": 2}).json()
    assert [f["key"] for f in first["files"]] == ["docs/a.txt", "docs/b.txt"]
    assert first["next_cursor"] is not None

    params = {"prefix": "docs/", "limit": 2, "cursor": first["next_cursor"]}
    second = client.get("/files", params=params).json()
    assert [f["key"] for f in second["files"]] == ["docs/c.txt"]
    assert second["next_cursor"] is None


def test_list_rejects_an_out_of_range_limit(client):
    assert client.get("/files", params={"limit": 0}).status_code == 400
    assert client.get("/files", params={"limit": 1001}).status_code == 400
