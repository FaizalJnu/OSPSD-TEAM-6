"""Metadata: id, name, path, size, modified_at (memo, "Metadata" and "The data model")."""

from datetime import UTC, datetime, timedelta

import pytest

from conformance.tests.conftest import (
    ROUTES_QUESTION,
    TIMESTAMP_QUESTION,
    assert_error,
    create,
    metadata,
)

# Teams 1 and 3 use this route today. Team 6 uses GET /metadata/{key}.
pytestmark = pytest.mark.proposed(ROUTES_QUESTION)

SHARED_FIELDS = {"id", "name", "path", "size", "modified_at"}


def test_metadata_has_the_shared_fields(api, root):
    create(api, root + "/docs/report.pdf", b"12345")
    response = metadata(api, root + "/docs/report.pdf")
    assert response.status_code == 200
    info = response.json()
    assert SHARED_FIELDS <= set(info)  # Extensions such as etag are allowed.
    assert info["id"] is None or isinstance(info["id"], str)  # null on S3 (unified #5)
    assert info["name"] == "report.pdf"
    assert info["path"] == root + "/docs/report.pdf"
    assert info["size"] == 5


def test_metadata_matches_what_create_returned(api, root):
    created = create(api, root + "/file.txt")
    info = metadata(api, root + "/file.txt").json()
    for field in SHARED_FIELDS - {"modified_at"}:  # precision may differ by operation
        assert info[field] == created[field]


def test_modified_at_is_an_iso_8601_time_with_a_timezone(api, root):
    create(api, root + "/file.txt")
    modified_at = datetime.fromisoformat(metadata(api, root + "/file.txt").json()["modified_at"])
    assert modified_at.tzinfo is not None
    # Generous, because the provider's clock is not ours.
    assert abs(datetime.now(UTC) - modified_at) < timedelta(hours=1)


@pytest.mark.proposed(TIMESTAMP_QUESTION)
def test_modified_at_is_utc_ending_in_z(api, root):
    create(api, root + "/file.txt")
    assert metadata(api, root + "/file.txt").json()["modified_at"].endswith("Z")


def test_metadata_for_a_missing_file_is_not_found(api, root):
    assert_error(metadata(api, root + "/missing.txt"), 404, "not_found")
