"""Health: ``GET /health`` and ``GET /health/provider``.

HTTP behavior over ``FakeStorage``, translation of HeadBucket answers by ``S3Storage``
(``stubbed_s3``, no network), and checks against the real bucket (``provider``).
"""

import json
import logging
import uuid
from dataclasses import replace

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, ProviderError, ProviderUnavailable
from storage_service.main import build_service, create_app
from tests.conftest import load_provider_settings

OK = {"status": "ok"}
UNAVAILABLE = ProviderUnavailable("could not reach the storage provider")


def test_health_is_ok_without_a_storage_call(fake, fake_client):
    response = fake_client.get("/health")

    assert response.status_code == 200
    assert response.json() == OK
    assert fake.calls == []


def test_health_stays_ok_while_the_provider_is_down(fake, fake_client):
    fake.fail("check_health", UNAVAILABLE)

    assert fake_client.get("/health").json() == OK
    assert fake_client.get("/health/provider").status_code == 503
    assert fake_client.get("/health").status_code == 200


def test_provider_health_is_ok_after_one_storage_check(fake, fake_client):
    response = fake_client.get("/health/provider")

    assert response.status_code == 200
    assert response.json() == OK
    assert fake.calls == [("check_health", "")]


HEALTH_FAILED = {
    "error": {
        "code": "provider_unavailable",
        "message": "the storage provider health check failed",
    }
}


@pytest.mark.parametrize(
    "error",
    [
        AccessDenied("the storage provider denied access", provider_code="403"),
        ProviderError(
            "the configured bucket does not exist or is not accessible",
            provider_code="NoSuchBucket",
        ),
        ProviderUnavailable(
            "could not reach the storage provider", provider_code="EndpointConnectionError"
        ),
    ],
)
def test_every_failed_provider_check_is_503_as_the_shared_interface_requires(
    fake, fake_client, caplog, error
):
    caplog.set_level(logging.WARNING, logger="storage_service.routers.error_handlers")
    fake.fail("check_health", error)

    response = fake_client.get("/health/provider")

    assert response.status_code == 503
    assert response.json() == HEALTH_FAILED
    assert fake.calls == [("check_health", "")]
    # The log keeps what the response hides: which call failed, and the provider's code.
    [record] = caplog.records
    event = json.loads(record.getMessage())
    assert event["event"] == "request_failed"
    assert event["operation"] == "provider_health"
    assert event["status"] == 503
    assert event["storage_call"] == "check_health"
    assert event["provider_code"] == error.provider_code
    assert event["provider_involved"] is True
    assert "write_outcome" not in event  # a health check never writes


def test_health_on_in_memory_storage(client):
    assert client.get("/health").json() == OK
    assert client.get("/health/provider").json() == OK


# S3Storage: HeadBucket answers, translated without network.


def test_s3_health_sends_one_head_bucket(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_response("head_bucket", {}, {"Bucket": "test-bucket"})

    assert storage.check_health() is None


@pytest.mark.parametrize("code", ["404", "NotFound", "NoSuchBucket"])
def test_s3_health_with_a_missing_bucket_is_a_provider_error(stubbed_s3, code):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "head_bucket",
        service_error_code=code,
        http_status_code=404,
        expected_params={"Bucket": "test-bucket"},
    )

    with pytest.raises(ProviderError) as caught:
        storage.check_health()
    assert str(caught.value) == "the configured bucket does not exist or is not accessible"
    assert caught.value.provider_code == code


@pytest.mark.parametrize("code", ["403", "AccessDenied", "InvalidAccessKeyId"])
def test_s3_health_with_refused_credentials_is_access_denied(stubbed_s3, code):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "head_bucket",
        service_error_code=code,
        http_status_code=403,
        expected_params={"Bucket": "test-bucket"},
    )

    with pytest.raises(AccessDenied, match="the storage provider denied access"):
        storage.check_health()


def test_s3_health_with_a_provider_server_error_is_a_provider_error(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "head_bucket",
        service_error_code="InternalError",
        http_status_code=500,
        expected_params={"Bucket": "test-bucket"},
    )

    with pytest.raises(ProviderError, match="the storage provider rejected the request"):
        storage.check_health()


def test_s3_health_that_cannot_reach_the_provider_is_provider_unavailable(stubbed_s3, monkeypatch):
    storage, _stubber = stubbed_s3

    def unreachable(**kwargs):
        raise EndpointConnectionError(endpoint_url="https://s3.example.invalid")

    monkeypatch.setattr(storage._client, "head_bucket", unreachable)
    with pytest.raises(ProviderUnavailable, match="could not reach the storage provider") as raised:
        storage.check_health()
    assert isinstance(raised.value.__cause__, EndpointConnectionError)


# The real bucket in .env.


@pytest.mark.provider
def test_health_on_the_real_provider(provider_client):
    assert provider_client.get("/health").json() == OK
    response = provider_client.get("/health/provider")
    assert response.status_code == 200
    assert response.json() == OK


@pytest.mark.provider
def test_provider_health_with_a_missing_real_bucket_is_503_while_health_stays_ok():
    settings = load_provider_settings()
    assert settings.s3 is not None
    # This name is never created, so the check cannot touch the real bucket.
    missing = replace(settings, s3=replace(settings.s3, bucket="ospsd-missing-" + uuid.uuid4().hex))

    with TestClient(create_app(build_service(missing))) as client:
        assert client.get("/health").json() == OK
        response = client.get("/health/provider")

    assert response.status_code == 503
    assert response.json() == HEALTH_FAILED


@pytest.mark.provider
def test_provider_health_with_wrong_real_credentials_is_503():
    settings = load_provider_settings()
    assert settings.s3 is not None
    wrong = replace(settings, s3=replace(settings.s3, secret_key="not-the-real-secret-key"))

    with TestClient(create_app(build_service(wrong))) as client:
        response = client.get("/health/provider")

    assert response.status_code == 503
    assert response.json() == HEALTH_FAILED
