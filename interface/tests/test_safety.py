"""Text from the API, the providers and the model is shown, never run."""

from meeting_interface.api_client import ApiError
from meeting_interface.fake_api import OK, run_with
from tests.conftest import FORM


def test_markup_in_ids_from_the_api_is_escaped(client, fake_api):
    fake_api.next_error = ApiError(
        "provider_error",
        "x",
        run=run_with(OK, OK, status="partial", issue_id='<img src=x onerror="alert(1)">'),
    )

    page = client.post("/runs", data=FORM).text

    assert "<img src=x" not in page
    assert "&lt;img" in page


def test_markup_in_error_message_is_escaped(client, fake_api):
    fake_api.next_error = ApiError("provider_error", "<b>bold</b>")

    page = client.post("/runs", data=FORM).text

    assert "<b>bold</b>" not in page
    assert "&lt;b&gt;bold&lt;/b&gt;" in page


def test_pages_send_a_content_security_policy(client):
    headers = client.get("/").headers

    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"


def test_pages_have_no_inline_script_or_style_the_policy_would_block(client):
    page = client.get("/").text

    assert "<script>" not in page
    assert "<style" not in page
    assert " style=" not in page
    assert "includeIndicatorStyles" in page


def test_api_docs_are_not_served(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
