"""The error model across operations (Level 5): access denial, sanitized errors, the
failure log, errors outside any operation, and the errors /openapi.json lists.

Most tests run the app over ``FakeStorage`` (the ``fake`` and ``fake_client``
fixtures) and check both the response and the one JSON line logged for it. See
"Failure logs" in docs/API.md for the fields.
"""

import json
import logging
from dataclasses import replace
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, ProviderUnavailable, StorageError
from storage_service.main import build_service, create_app
from storage_service.service import FileService
from tests.conftest import MAX_UPLOAD_BYTES, load_provider_settings, send_file

LOGGER = "storage_service.routers.error_handlers"


@pytest.fixture(autouse=True)
def _capture_failure_logs(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)


def failure_log(caplog, response) -> dict[str, object]:
    """Return the one failure log line, after checking it matches ``response``."""
    records = [record for record in caplog.records if record.name == LOGGER]
    assert len(records) == 1
    # Expected failures get no traceback. Only an unexpected 500 has one.
    assert (records[0].exc_info is not None) == (response.status_code == 500)
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


def test_a_path_with_no_route_is_route_not_found_not_a_missing_file(fake, fake_client, caplog):
    response = fake_client.get("/nothing")

    assert response.status_code == 404
    assert response.json() == {"error": "RouteNotFound", "detail": "no route matches this path"}
    event = failure_log(caplog, response)
    assert event["operation"] is None  # no operation ran
    assert event["provider_involved"] is False
    assert event["storage_call"] is None
    assert caplog.records[0].levelno == logging.WARNING
    assert fake.calls == []


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("POST", "/files", "GET"),
        # Starlette's own Allow names only the first route that matches the path: POST.
        ("PATCH", "/files/notes.txt", "DELETE, GET, POST, PUT"),
    ],
)
def test_a_method_the_path_does_not_accept_is_405_with_every_allowed_method(
    fake, fake_client, caplog, method, path, allowed
):
    response = fake_client.request(method, path)

    assert response.status_code == 405
    assert response.json() == {
        "error": "MethodNotAllowed",
        "detail": f"this path does not accept {method}",
    }
    assert response.headers["allow"] == allowed
    event = failure_log(caplog, response)
    # Starlette matched the path to a route of another method. It was not run.
    assert event["operation"] is None
    assert "write_outcome" not in event
    assert caplog.records[0].levelno == logging.WARNING
    assert fake.calls == []


# Request bodies Starlette cannot read, with the parser's message. Its limits are
# 1000 files and 1 MB per text field.
UNREADABLE_BODIES: dict[str, tuple[dict[str, Any], str]] = {
    "no boundary": (
        {"content": b"data", "headers": {"Content-Type": "multipart/form-data"}},
        "Missing boundary in multipart.",
    ),
    "1001 files": (
        {"files": [("file", ("upload", b"x"))] * 1001},
        "Too many files. Maximum number of files is 1000.",
    ),
    "a text field over 1 MB": (
        {"files": {"file": ("upload", b"x")}, "data": {"note": "x" * (1024 * 1024 + 1)}},
        "Part exceeded maximum size of 1024KB.",
    ),
}


@pytest.mark.parametrize("body", UNREADABLE_BODIES)
@pytest.mark.parametrize(
    ("method", "operation"), [("POST", "create_file"), ("PUT", "replace_file")]
)
def test_a_multipart_body_that_cannot_be_read_is_invalid_input(
    fake, fake_client, caplog, method, operation, body
):
    request, message = UNREADABLE_BODIES[body]

    response = fake_client.request(method, "/files/notes.txt", **request)

    assert response.status_code == 400
    assert response.json() == {"error": "InvalidInput", "detail": f"file: {message}"}
    event = failure_log(caplog, response)
    assert event["operation"] == operation
    assert event["provider_involved"] is False
    assert event["write_outcome"] == "not_attempted"
    assert fake.calls == []


def test_a_bug_is_a_500_internal_error_that_claims_nothing_about_the_write(fake, caplog):
    fake.fail("put", RuntimeError("bug: the backend's secret internals"))
    # A real server still reports the exception after our handler, so TestClient
    # would re-raise it unless told not to.
    client = TestClient(
        create_app(FileService(fake, max_upload_bytes=MAX_UPLOAD_BYTES)),
        raise_server_exceptions=False,
    )

    response = send_file(client, "POST", "notes.txt", b"data")

    assert response.status_code == 500
    assert response.json() == {
        "error": "InternalError",
        "detail": "the service failed unexpectedly",
    }
    assert "secret internals" not in response.text
    event = failure_log(caplog, response)  # also checks that the traceback is logged
    assert event["operation"] == "create_file"
    assert event["provider_involved"] is None  # unknown: the bug may be anywhere
    assert event["storage_call"] is None
    assert event["write_outcome"] == "unknown"
    assert caplog.records[0].levelno == logging.ERROR


def test_a_storage_error_with_no_status_of_its_own_is_an_internal_error(fake, fake_client, caplog):
    # Only StorageError's subclasses have a status. Raising the base class is a bug.
    fake.fail("stat", StorageError("raised without a subclass"))

    response = fake_client.get("/metadata/notes.txt")

    assert response.status_code == 500
    assert response.json() == {
        "error": "InternalError",
        "detail": "the service failed unexpectedly",
    }
    event = failure_log(caplog, response)
    assert event["operation"] == "get_metadata"
    assert event["provider_involved"] is None


def serve_get(app, path: str) -> list[dict[str, Any]]:
    """Send one GET to ``app`` the way uvicorn does, and return every message it sends.

    For a response the app leaves unfinished, TestClient returns an empty body instead
    of the bytes that were sent, so it cannot show what the caller received.
    """
    messages: list[dict[str, Any]] = []
    requested = False

    async def receive() -> dict[str, Any]:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await anyio.sleep_forever()  # the client stays connected
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},  # as uvicorn reports
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    anyio.run(app, scope, receive, send)
    return messages


@pytest.mark.parametrize(
    ("error", "logged"),
    [
        (
            ProviderUnavailable(
                "could not reach the storage provider", provider_code="ResponseStreamingError"
            ),
            {
                "level": "ERROR",
                "error": "ProviderUnavailable",
                "detail": "could not reach the storage provider",
                "provider_involved": True,
                "storage_call": "get",
                "provider_code": "ResponseStreamingError",
            },
        ),
        (
            RuntimeError("bug: the backend's secret internals"),
            {
                "level": "ERROR",
                "error": "InternalError",
                "detail": "the service failed unexpectedly",
                "provider_involved": None,
                "storage_call": None,
            },
        ),
    ],
    ids=["provider", "bug"],
)
def test_a_download_cut_off_after_its_headers_is_left_unfinished_and_logs_the_200(
    fake, fake_client, caplog, error, logged
):
    assert send_file(fake_client, "POST", "big.bin", b"x" * 100).status_code == 201
    fake.cut_downloads(error, after_bytes=11)

    start, *body = serve_get(fake_client.app, "/files/big.bin")

    # The status and Content-Length went out before the failure.
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    assert (b"content-length", b"100") in start["headers"]
    # 11 bytes, and never the message that ends the body: the server closes the
    # connection, and the caller can tell from Content-Length that it was cut off.
    assert b"".join(message["body"] for message in body) == b"x" * 11
    assert all(message["more_body"] for message in body)
    records = [record for record in caplog.records if record.name == LOGGER]
    assert len(records) == 1
    assert json.loads(records[0].getMessage()) == {
        "event": "request_failed",
        "operation": "download_file",
        "status": 200,  # what the caller received
        **logged,
        "interrupted": True,
        "bytes_sent": 11,
        "size": 100,
    }
    # Only the bug is logged with its traceback.
    assert (records[0].exc_info is not None) == isinstance(error, RuntimeError)
    assert "secret internals" not in records[0].getMessage()


def test_openapi_lists_each_routes_errors_with_our_body_and_no_422(client):
    schema = client.get("/openapi.json").json()

    every_route = {"400", "403", "500", "502", "503"}
    expected = {
        ("GET", "/files"): every_route,
        ("POST", "/files/{key}"): every_route | {"409", "413"},
        ("PUT", "/files/{key}"): every_route | {"404", "413"},
        ("GET", "/files/{key}"): every_route | {"404"},
        ("DELETE", "/files/{key}"): every_route | {"404"},
        ("GET", "/metadata/{key}"): every_route | {"404"},
    }
    error_body = {"$ref": "#/components/schemas/ErrorBody"}
    for (method, path), statuses in expected.items():
        responses = schema["paths"][path][method.lower()]["responses"]
        errors = {status for status in responses if int(status) >= 400}
        assert errors == statuses, (method, path)
        for status in errors:
            assert responses[status]["content"]["application/json"]["schema"] == error_body
    assert set(schema["components"]["schemas"]["ErrorBody"]["properties"]) == {"error", "detail"}
    assert "HTTPValidationError" not in schema["components"]["schemas"]


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
