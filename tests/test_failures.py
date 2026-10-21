"""The error model across operations (Level 5): access denial, sanitized errors, and
the failure log.

Most tests run the app over ``FakeStorage`` (the ``fake`` and ``fake_client``
fixtures) and check both the response and the one JSON line logged for it. See
"Failure logs" in docs/API.md for the fields.
"""

import json
import logging
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, ProviderUnavailable
from storage_service.main import build_service, create_app
from storage_service.service import FileService
from tests.conftest import load_provider_settings, send_file

LOGGER = "storage_service.routers.error_handlers"


@pytest.fixture(autouse=True)
def _capture_failure_logs(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)


def failure_log(caplog, response) -> dict[str, object]:
    """Return the one failure log line, after checking it matches ``response``."""
    records = [record for record in caplog.records if record.name == LOGGER]
    assert len(records) == 1
    assert records[0].exc_info is None  # expected failures get no traceback
    event: dict[str, object] = json.loads(records[0].getMessage())
    assert event["level"] == records[0].levelname
    assert event["event"] == "request_failed"
    assert event["status"] == response.status_code
    assert event["error"] == response.json()["error"]
    assert event["detail"] == response.json()["detail"]
    return event


def test_a_successful_request_logs_nothing(fake_client, caplog):
    assert send_file(fake_client, "POST", "notes.txt", b"data").status_code == 201
    assert fake_client.get("/metadata/notes.txt").status_code == 200

    assert [record for record in caplog.records if record.name == LOGGER] == []


def test_invalid_input_is_logged_as_rejected_before_the_provider(fake, fake_client, caplog):
    response = fake_client.get("/metadata/a//b.txt")

    assert response.status_code == 400
    event = failure_log(caplog, response)
    assert event["operation"] == "get_metadata"
    assert event["provider_involved"] is False
    assert event["storage_call"] is None
    assert "write_outcome" not in event  # Metadata writes nothing
    assert caplog.records[0].levelno == logging.WARNING
    assert fake.calls == []


def test_input_fastapi_rejects_is_logged_like_our_own(fake_client, caplog):
    response = fake_client.get("/files", params={"limit": "abc"})

    assert response.status_code == 400
    event = failure_log(caplog, response)
    assert event["operation"] == "list_files"
    assert event["error"] == "InvalidInput"
    assert event["provider_involved"] is False


def test_a_missing_file_is_logged_as_reported_by_the_provider(fake_client, caplog):
    response = fake_client.get("/metadata/missing.txt")

    assert response.status_code == 404
    event = failure_log(caplog, response)
    assert event["provider_involved"] is True
    assert event["storage_call"] == "stat"
    assert caplog.records[0].levelno == logging.WARNING


def test_access_denied_is_403_and_logged_for_whoever_runs_the_service(fake, fake_client, caplog):
    fake.fail("stat", AccessDenied("the storage provider denied access", provider_code="403"))

    response = fake_client.get("/metadata/notes.txt")

    assert response.status_code == 403
    assert response.json() == {
        "error": "AccessDenied",
        "detail": "the storage provider denied access",
    }
    event = failure_log(caplog, response)
    assert event["provider_code"] == "403"
    assert event["provider_involved"] is True
    assert caplog.records[0].levelno == logging.ERROR


def test_a_write_that_failed_in_its_check_is_logged_as_not_attempted(fake, fake_client, caplog):
    fake.fail("stat", ProviderUnavailable("could not reach the storage provider"))

    response = fake_client.delete("/files/old.txt")

    assert response.status_code == 503
    event = failure_log(caplog, response)
    assert event["operation"] == "delete_file"
    assert event["storage_call"] == "stat"
    assert event["write_outcome"] == "not_attempted"
    assert fake.calls == [("stat", "old.txt")]


def test_a_write_that_failed_in_the_write_call_is_logged_as_unknown(fake, fake_client, caplog):
    # The provider stores the file, then the response is lost. The log must not
    # claim that nothing changed.
    unavailable = ProviderUnavailable("could not reach the storage provider")
    fake.fail("put", unavailable, after_applying=True)

    response = send_file(fake_client, "POST", "notes.txt", b"data")

    assert response.status_code == 503
    event = failure_log(caplog, response)
    assert event["operation"] == "create_file"
    assert event["storage_call"] == "put"
    assert event["write_outcome"] == "unknown"
    assert fake_client.get("/metadata/notes.txt").status_code == 200  # it was stored


def test_a_create_refused_by_our_own_rules_is_logged_as_not_attempted(fake_client, caplog):
    assert send_file(fake_client, "POST", "notes.txt", b"data").status_code == 201
    too_big = send_file(fake_client, "POST", "big.bin", b"x" * 2048)
    taken = send_file(fake_client, "POST", "notes.txt", b"data")

    records = [json.loads(r.getMessage()) for r in caplog.records if r.name == LOGGER]
    assert [(e["status"], e["provider_involved"], e["write_outcome"]) for e in records] == [
        (too_big.status_code, False, "not_attempted"),  # 413: rejected before any call
        (taken.status_code, True, "not_attempted"),  # 409: decided from the provider's check
    ]
    assert [too_big.status_code, taken.status_code] == [413, 409]


def test_provider_messages_stay_out_of_responses_and_logs(stubbed_s3, caplog):
    storage, stubber = stubbed_s3
    # OCI's real message names the namespace and the bucket.
    stubber.add_client_error(
        "list_objects_v2",
        service_error_code="NoSuchBucket",
        service_message="Either the bucket named 'team-bucket' does not exist in the "
        "namespace 'secretnamespace' or you are not authorized to access it",
        http_status_code=404,
        expected_params={"Bucket": "test-bucket", "Prefix": "docs/", "MaxKeys": 2},
    )
    client = TestClient(create_app(FileService(storage, max_upload_bytes=1024)))

    response = client.get("/files", params={"prefix": "docs/", "limit": 2})

    assert response.status_code == 502
    assert response.json() == {
        "error": "ProviderError",
        "detail": "the storage provider rejected the request",
    }
    event = failure_log(caplog, response)
    assert event["provider_code"] == "NoSuchBucket"
    for secret in ("secretnamespace", "team-bucket", "Traceback"):
        assert secret not in caplog.text


@pytest.mark.provider
def test_wrong_credentials_are_access_denied_on_the_real_provider(provider_client, provider_prefix):
    settings = load_provider_settings()
    assert settings.s3 is not None
    wrong = replace(settings, s3=replace(settings.s3, secret_key="not-the-real-secret-key"))
    key = provider_prefix + "denied.txt"

    with TestClient(create_app(build_service(wrong))) as denied:
        responses = [
            denied.get(f"/metadata/{key}"),
            denied.get("/files", params={"prefix": provider_prefix}),
            send_file(denied, "POST", key, b"never stored"),
        ]

    for response in responses:
        assert response.status_code == 403
        assert response.json() == {
            "error": "AccessDenied",
            "detail": "the storage provider denied access",
        }
    # Create stopped at its existence check, so nothing was written.
    listing = provider_client.get("/files", params={"prefix": provider_prefix})
    assert listing.json() == {"files": [], "next_cursor": None}
