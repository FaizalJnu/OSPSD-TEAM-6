"""Delete: DELETE /files?path=. Owner: Faizal Rahman."""

import pytest
from fastapi.testclient import TestClient

from storage_service.errors import AccessDenied, ProviderError, ProviderUnavailable
from tests.conftest import send_file


def delete_path(client: TestClient, path: str):
    return client.delete("/files", params={"path": path})


def test_delete_removes_the_file_and_deleting_again_is_404(client):
    send_file(client, "POST", "old.txt", b"bye")
    assert delete_path(client, "old.txt").status_code == 204
    assert client.get("/files/old.txt").status_code == 404
    assert delete_path(client, "old.txt").status_code == 404


def test_delete_checks_the_file_exists_then_deletes_it(fake, fake_client):
    send_file(fake_client, "POST", "old.txt", b"bye")
    fake.calls.clear()

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 204
    assert response.content == b""
    assert fake.calls == [("stat", "old.txt"), ("delete", "old.txt")]


@pytest.mark.parametrize("path", ["docs/old.txt", "/docs/old.txt"])
def test_delete_finds_the_file_with_or_without_the_leading_slash(fake, fake_client, path):
    send_file(fake_client, "POST", "docs/old.txt", b"bye")
    fake.calls.clear()

    assert delete_path(fake_client, path).status_code == 204
    # Storage only ever sees the key, so a file stored before paths existed is still found.
    assert fake.calls == [("stat", "docs/old.txt"), ("delete", "docs/old.txt")]


def test_delete_of_a_missing_file_is_404_and_never_calls_delete(fake, fake_client):
    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 404
    assert response.json()["error"] == "FileNotFound"
    assert fake.calls == [("stat", "old.txt")]


def test_delete_of_a_missing_file_reports_the_canonical_path(client):
    response = delete_path(client, "docs/old.txt")

    assert response.json() == {"error": "FileNotFound", "detail": "no file at '/docs/old.txt'"}


@pytest.mark.parametrize("path", ["", "/", "docs/", "a//b", "a/../b", "bad\nname", "x" * 1024])
def test_delete_of_an_invalid_path_is_400_and_never_calls_storage(fake, fake_client, path):
    response = delete_path(fake_client, path)

    assert response.status_code == 400
    assert response.json()["error"] == "InvalidInput"
    assert fake.calls == []


def test_delete_without_a_path_is_400_and_never_calls_storage(fake, fake_client):
    response = fake_client.delete("/files")

    assert response.status_code == 400
    assert response.json() == {"error": "InvalidInput", "detail": "path: Field required"}
    assert fake.calls == []


def test_delete_decodes_the_path_from_the_query_string(client):
    # In a query string "+" means a space, so a literal "+" has to arrive as %2B.
    send_file(client, "POST", "a+b c.txt", b"bye")

    assert client.delete("/files?path=a%2Bb%20c.txt").status_code == 204
    assert client.get("/metadata/a+b c.txt").status_code == 404


def test_the_old_keyed_delete_route_no_longer_deletes(client):
    send_file(client, "POST", "old.txt", b"bye")

    assert client.delete("/files/old.txt").status_code != 204
    assert client.get("/metadata/old.txt").status_code == 200


def test_delete_returns_503_and_never_deletes_when_the_check_cannot_reach_the_provider(
    fake, fake_client
):
    fake.fail("stat", ProviderUnavailable("could not reach the storage provider"))

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 503
    assert response.json() == {
        "error": "ProviderUnavailable",
        "detail": "could not reach the storage provider",
    }
    assert fake.calls == [("stat", "old.txt")]


def test_delete_returns_502_when_the_provider_rejects_the_delete(fake, fake_client):
    send_file(fake_client, "POST", "old.txt", b"bye")
    fake.calls.clear()
    fake.fail("delete", ProviderError("the storage provider rejected the request"))

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 502
    assert response.json() == {
        "error": "ProviderError",
        "detail": "the storage provider rejected the request",
    }
    assert fake.calls == [("stat", "old.txt"), ("delete", "old.txt")]


def test_delete_that_removes_the_file_then_fails_returns_503_and_a_retry_is_404(fake, fake_client):
    send_file(fake_client, "POST", "old.txt", b"bye")
    unavailable = ProviderUnavailable("could not reach the storage provider")
    fake.fail("delete", unavailable, after_applying=True)

    response = delete_path(fake_client, "old.txt")

    assert response.status_code == 503
    assert response.json() == {"error": "ProviderUnavailable", "detail": str(unavailable)}
    # The 503 did not mean nothing changed: the file is gone.
    assert fake_client.get("/metadata/old.txt").status_code == 404
    assert delete_path(fake_client, "old.txt").status_code == 404


def test_s3_delete_denied_by_the_provider_raises_access_denied(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "delete_object",
        service_error_code="AccessDenied",
        http_status_code=403,
        expected_params={"Bucket": "test-bucket", "Key": "old.txt"},
    )
    with pytest.raises(AccessDenied):
        storage.delete("old.txt")


@pytest.mark.provider
def test_delete_removes_the_file_from_the_real_provider(provider_client, provider_prefix):
    key = provider_prefix + "old.txt"
    assert send_file(provider_client, "POST", key, b"bye").status_code == 201
    assert delete_path(provider_client, key).status_code == 204
    assert provider_client.get(f"/metadata/{key}").status_code == 404
