"""Text from providers and the model is shown, never run."""

from meeting_interface.api_client import ApiError
from meeting_interface.fake_api import FakeApiClient
from meeting_interface.models import RunResult, StepOutcome, StepStatus
from tests.conftest import FORM


def run_with(fake_api: FakeApiClient, **step: str) -> None:
    fake_api.next_result = RunResult(
        "run-x", "succeeded", [StepOutcome("read_issues", StepStatus.SUCCEEDED, **step)]
    )


def test_markup_in_provider_text_is_escaped(client, fake_api):
    run_with(fake_api, detail='<script>alert(1)</script><img src=x onerror="alert(2)">')

    page = client.post("/runs", data=FORM).text

    assert "<script>alert(1)" not in page
    assert "<img src=x" not in page
    assert "&lt;script&gt;" in page


def test_markup_in_error_message_is_escaped(client, fake_api):
    fake_api.next_error = ApiError("provider_error", "<b>bold</b>")

    page = client.post("/runs", data=FORM).text

    assert "<b>bold</b>" not in page
    assert "&lt;b&gt;bold&lt;/b&gt;" in page


def test_javascript_link_is_not_clickable(client, fake_api):
    run_with(fake_api, link="javascript:alert(1)")

    page = client.post("/runs", data=FORM).text

    assert "javascript:" not in page


def test_https_link_opens_without_sharing_the_page(client, fake_api):
    run_with(fake_api, link="https://trello.test/c/1")

    page = client.post("/runs", data=FORM).text

    assert 'href="https://trello.test/c/1"' in page
    assert 'rel="noopener noreferrer"' in page


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
