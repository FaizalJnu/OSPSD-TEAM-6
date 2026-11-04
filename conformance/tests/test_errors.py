"""The shared error body: {"error": {"code", "message"}} (memo, "Errors", and unified #4).

Every other file checks the body through ``assert_error``. These tests cover the errors
that happen outside any operation.
"""

import pytest

from conformance.tests.conftest import ERRORS_ISSUE, assert_error

pytestmark = pytest.mark.proposed(ERRORS_ISSUE)


def test_an_unknown_route_is_route_not_found(api):
    assert_error(api.get("/no-such-route"), 404, "route_not_found")


def test_a_wrong_method_is_method_not_allowed_with_an_allow_header(api):
    response = api.post("/health")
    assert_error(response, 405, "method_not_allowed")
    assert "GET" in response.headers["Allow"]
