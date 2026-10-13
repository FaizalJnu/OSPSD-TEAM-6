"""Metadata: GET /metadata/{key}. Owner: Darsh Shani."""

from tests.conftest import send_file


def test_metadata_reports_size_and_a_type_picked_by_the_server(client):
    send_file(client, "POST", "docs/report.pdf", b"%PDF-1.7 fake")
    meta = client.get("/metadata/docs/report.pdf").json()
    assert meta["size"] == len(b"%PDF-1.7 fake")
    assert meta["content_type"] == "application/pdf"
