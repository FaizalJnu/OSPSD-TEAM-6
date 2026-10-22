"""Delete: ``DELETE /files/{key}``."""

from fastapi import APIRouter, Response

from storage_service.routers.deps import Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


@router.delete(
    "/files/{key:path}",
    status_code=204,
    responses=error_responses(
        {
            400: "InvalidInput: the key violates a key rule.",
            403: "AccessDenied: the provider denied the service access.",
            404: "FileNotFound: no file exists under the key.",
            502: (
                "ProviderError: the storage provider rejected the request. "
                "The delete may still have happened."
            ),
            503: (
                "ProviderUnavailable: the storage provider could not be reached. "
                "The delete may still have happened."
            ),
        }
    ),
)
def delete_file(key: str, service: Service) -> Response:
    service.delete(key)
    return Response(status_code=204)
