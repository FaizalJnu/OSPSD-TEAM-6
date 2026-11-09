"""Unit tests for the service's input rules."""

import pytest

from storage_service.errors import InvalidInput
from storage_service.service import (
    guess_content_type,
    normalize_path,
    path_to_key,
    validate_key,
)


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


@pytest.mark.parametrize(
    ("path", "canonical"),
    [
        ("cat.jpg", "/cat.jpg"),
        ("/cat.jpg", "/cat.jpg"),
        ("photos/2026/cat.jpg", "/photos/2026/cat.jpg"),
        ("/photos/2026/cat.jpg", "/photos/2026/cat.jpg"),
        ("with spaces.txt", "/with spaces.txt"),
        ("ünïcödé.txt", "/ünïcödé.txt"),
        ("x" * 1023, "/" + "x" * 1023),  # the longest path: 1024 bytes with its leading "/"
    ],
)
def test_a_path_is_accepted_with_or_without_its_leading_slash(path, canonical):
    assert normalize_path(path) == canonical


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/",
        "//",
        "//a",
        "a/",
        "/a/",
        "a//b",
        "a/../b",
        "/./a",
        "..",
        "/..",
        "bad\nname",
        "bad\x7fname",
        "x" * 1024,  # 1025 bytes once the leading "/" is counted
        "é" * 512,  # 512 characters, but 1025 bytes
    ],
)
def test_a_path_that_breaks_a_rule_is_rejected(path):
    with pytest.raises(InvalidInput):
        normalize_path(path)


def test_the_key_is_the_canonical_path_without_its_leading_slash():
    assert path_to_key("/photos/2026/cat.jpg") == "photos/2026/cat.jpg"


def test_content_type_comes_from_the_extension():
    assert guess_content_type("photos/cat.jpg") == "image/jpeg"
    assert guess_content_type("no-extension") == "application/octet-stream"
