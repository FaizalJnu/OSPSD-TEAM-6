"""Unit tests for the service's input rules."""

import pytest

from storage_service.errors import InvalidInput
from storage_service.service import guess_content_type, validate_key


@pytest.mark.parametrize(
    "key", ["cat.jpg", "photos/2026/cat.jpg", "with spaces.txt", "ünïcödé.txt", "x" * 1024]
)
def test_reasonable_keys_are_accepted(key):
    validate_key(key)


@pytest.mark.parametrize(
    "key",
    ["", "/leading", "trailing/", "a//b", "a/../b", "./a", "..", "bad\nname", "x" * 1025],
)
def test_unsafe_or_malformed_keys_are_rejected(key):
    with pytest.raises(InvalidInput):
        validate_key(key)


def test_content_type_comes_from_the_extension():
    assert guess_content_type("photos/cat.jpg") == "image/jpeg"
    assert guess_content_type("no-extension") == "application/octet-stream"
