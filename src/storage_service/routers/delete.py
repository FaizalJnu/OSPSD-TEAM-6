"""Delete: ``DELETE /files?path=``."""

from fastapi import APIRouter, Response

from storage_service.routers.deps import PathQuery, Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


@router.delete(
    "/files",
    status_code=204,
    responses=error_responses(
        {
            400: "InvalidInput: the path is missing or violates a path rule.",
            403: "AccessDenied: the provider denied the service access.",
            404: "FileNotFound: no file exists at the path.",
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
def delete_file(path: PathQuery, service: Service) -> Response:
    service.delete(path)
    return Response(status_code=204)
