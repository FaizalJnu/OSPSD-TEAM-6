"""Public regression checks for the tagged HW2 error and metadata contract."""

import pytest
from cloud_storage_api.errors import (
    ConflictError,
    FileTooLargeError,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
)

from tests.conftest import send_file


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (InvalidRequestError("bad input"), 400, "invalid_request"),
        (PermissionDeniedError("access refused"), 403, "permission_denied"),
        (NotFoundError("missing"), 404, "not_found"),
        (ConflictError("occupied"), 409, "conflict"),
        (FileTooLargeError("too large"), 413, "file_too_large"),
        (InvalidOperationError("not permitted"), 422, "invalid_operation"),
        (ProviderError("provider failed"), 502, "provider_error"),
        (ProviderUnavailableError("unreachable"), 503, "provider_unavailable"),
    ],
)
def test_shared_errors_are_handled_without_leaking_framework_details(
    fake, fake_client, error, status, code
):
    fake.fail("stat", error)
    response = fake_client.get("/files/metadata", params={"path": "docs/a.txt"})
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": str(error)}}


def test_metadata_static_route_wins_over_legacy_download(fake_client):
    assert send_file(fake_client, "POST", "docs/a.txt", b"hello").status_code == 201
    response = fake_client.get("/files/metadata", params={"path": "/docs/a.txt"})
    assert response.status_code == 200
    assert response.json()["path"] == "/docs/a.txt"
    assert response.json()["id"] is None
    assert response.json()["modified_at"].endswith("Z")
    assert fake_client.get("/metadata/docs/a.txt").status_code == 404


@pytest.mark.parametrize("path", ["", "/", "a//b", "a/../b", "a/", "a\x00b"])
def test_invalid_metadata_path_never_reaches_storage(fake, fake_client, path):
    response = fake_client.get("/files/metadata", params={"path": path})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert fake.calls == []


@pytest.mark.parametrize("spelling", ["docs/a+b c.txt", "/docs/a+b c.txt"])
def test_metadata_normalizes_paths_without_changing_encoded_names(fake, fake_client, spelling):
    from io import BytesIO

    fake.put("docs/a+b c.txt", BytesIO(b"hello"), "text/plain")
    fake.calls.clear()
    response = fake_client.get("/files/metadata", params={"path": spelling})
    assert response.status_code == 200
    assert response.json()["path"] == "/docs/a+b c.txt"
    assert fake.calls == [("stat", "docs/a+b c.txt")]


def test_metadata_rejects_path_above_limit_including_leading_slash(fake, fake_client):
    response = fake_client.get("/files/metadata", params={"path": "x" * 1024})
    assert response.status_code == 400
    assert fake.calls == []


def test_semantic_422_survives_openapi_validation_cleanup(fake_client):
    from fastapi import FastAPI

    from storage_service.routers.error_handlers import error_responses

    app: FastAPI = fake_client.app

    @app.get("/semantic", responses=error_responses({422: "invalid_operation"}))
    def semantic() -> None:
        raise InvalidOperationError("not permitted")

    response = fake_client.get("/semantic")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_operation"
    responses = fake_client.get("/openapi.json").json()["paths"]["/semantic"]["get"]["responses"]
    assert responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorBody"
    }


def test_a_tagged_provider_error_after_an_applied_write_keeps_unknown_outcome(
    fake, fake_client, caplog
):
    import json
    import logging

    caplog.set_level(logging.ERROR, logger="storage_service.routers.error_handlers")
    fake.fail("put", ProviderUnavailableError("completion unconfirmed"), after_applying=True)
    response = send_file(fake_client, "POST", "written.txt", b"stored")
    assert response.status_code == 503
    events = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "storage_service.routers.error_handlers"
    ]
    assert len(events) == 1
    assert events[0]["write_outcome"] == "unknown"
    assert events[0]["storage_call"] == "put"
    assert events[0]["provider_involved"] is True
    assert fake_client.get("/files/metadata", params={"path": "written.txt"}).status_code == 200
