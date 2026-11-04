"""Health: one check for the service, one for its storage provider (memo, "Health")."""


def test_service_health_is_ok(api):
    response = api.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_provider_health_is_ok(api):
    response = api.get("/health/provider")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
