"""Every documented error code reaches the person with a next step."""

import pytest

from meeting_interface.api_client import API_UNREACHABLE, BAD_RESPONSE, ApiError
from meeting_interface.messages import ERROR_HELP, UNKNOWN_ERROR
from tests.conftest import FORM

# The API service's error model (docs/API.md, "Error types"), plus the codes the
# interface raises itself. Add a code here when the API documents a new one.
DOCUMENTED_CODES = [
    "invalid_request",
    "permission_denied",
    "not_found",
    "conflict",
    "file_too_large",
    "provider_error",
    "provider_unavailable",
    "route_not_found",
    "method_not_allowed",
    "internal_error",
    API_UNREACHABLE,
    BAD_RESPONSE,
]


def test_every_documented_code_has_its_own_help():
    missing = [code for code in DOCUMENTED_CODES if code not in ERROR_HELP]

    assert missing == []


@pytest.mark.parametrize("code", DOCUMENTED_CODES)
def test_each_code_shows_its_title_message_and_next_step(client, fake_api, code):
    fake_api.next_error = ApiError(code, f"message for {code}")

    page = client.post("/runs", data=FORM).text

    assert ERROR_HELP[code].title in page
    assert ERROR_HELP[code].next_step in page
    assert f"message for {code}" in page
    assert 'role="alert"' in page


def test_unknown_code_falls_back_without_showing_the_code(client, fake_api):
    fake_api.next_error = ApiError("db_pool_exhausted", "try again")

    page = client.post("/runs", data=FORM).text

    assert UNKNOWN_ERROR.next_step in page
    assert "db_pool_exhausted" not in page
