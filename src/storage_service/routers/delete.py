"""Delete: ``DELETE /files?path=``, for one file or a whole folder."""

from fastapi import APIRouter, Response

from storage_service.routers.deps import PathQuery, Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


@router.delete(
    "/files",
    status_code=204,
    responses=error_responses(
        {
            400: "invalid_request: the path is missing or violates a path rule.",
            403: "permission_denied: the provider denied the service access.",
            404: "not_found: no file or folder exists at the path.",
            502: (
                "provider_error: the storage provider rejected the request, or a folder "
                "was only partly deleted. The delete may still have happened."
            ),
            503: (
                "provider_unavailable: the storage provider could not be reached. "
                "The delete may still have happened."
            ),
        }
    ),
)
def delete_file(path: PathQuery, service: Service) -> Response:
    service.delete(path)
    return Response(status_code=204)
