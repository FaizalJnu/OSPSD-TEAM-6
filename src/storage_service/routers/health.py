"""Health: ``GET /health`` for the API alone, ``GET /health/provider`` for its storage."""

from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter

from storage_service.routers.deps import SharedStorage
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


@dataclass(frozen=True)
class HealthStatus:
    """The body of a successful health check."""

    status: Literal["ok"]


@router.get(
    "/health",
    summary="Check that the API is running",
    responses=error_responses({}),
)
def health() -> HealthStatus:
    """Return {"status": "ok"} whenever the service can answer requests.

    It makes no provider call, so a provider outage never fails it. Use it as the
    liveness check, so an outage does not make the platform restart the service.
    """
    return HealthStatus(status="ok")


@router.get(
    "/health/provider",
    summary="Check that the storage provider can be used",
    responses=error_responses(
        {
            503: (
                "provider_unavailable: the provider check failed. The provider could "
                "not be reached, refused the credentials, or has no configured bucket."
            ),
        }
    ),
)
def provider_health(storage: SharedStorage) -> HealthStatus:
    """Return {"status": "ok"} if one cheap provider call succeeds.

    On S3 the call is one HeadBucket on the configured bucket. It reads no file and
    changes nothing. As the shared interface's check_health requires, every failed
    check is 503 provider_unavailable; the failure log keeps the provider's code.
    Missing settings never reach this route: the service does not start without them.
    """
    storage.check_health()
    return HealthStatus(status="ok")
