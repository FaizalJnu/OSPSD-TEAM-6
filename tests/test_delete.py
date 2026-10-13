"""Delete: DELETE /files/{key}. Owner: Faizal Rahman."""

import pytest

from storage_service.errors import ProviderError
from tests.conftest import send_file


def test_delete_removes_the_file_and_deleting_again_is_404(client):
    send_file(client, "POST", "old.txt", b"bye")
    assert client.delete("/files/old.txt").status_code == 204
    assert client.get("/files/old.txt").status_code == 404
    assert client.delete("/files/old.txt").status_code == 404


def test_s3_delete_rejected_by_the_provider_raises_provider_error(stubbed_s3):
    storage, stubber = stubbed_s3
    stubber.add_client_error(
        "delete_object",
        service_error_code="AccessDenied",
        http_status_code=403,
        expected_params={"Bucket": "test-bucket", "Key": "old.txt"},
    )
    with pytest.raises(ProviderError):
        storage.delete("old.txt")


@pytest.mark.provider
def test_delete_removes_the_file_from_the_real_provider(provider_client, provider_prefix):
    key = provider_prefix + "old.txt"
    assert send_file(provider_client, "POST", key, b"bye").status_code == 201
    assert provider_client.delete(f"/files/{key}").status_code == 204
    assert provider_client.get(f"/metadata/{key}").status_code == 404
