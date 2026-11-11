"""Move: ``PATCH /files?path=`` with the JSON body ``{"new_path": "..."}``."""

from fastapi import APIRouter
from pydantic import BaseModel

from storage_service.models import CommonFileInfo
from storage_service.routers.deps import PathQuery, Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


class MoveRequest(BaseModel):
    """The body of a Move: where the file should be afterwards."""

    new_path: str


@router.patch(
    "/files",
    summary="Move a file",
    responses=error_responses(
        {
            400: "invalid_request: path or new_path is missing or malformed, or the body "
            "is not valid JSON.",
            403: "permission_denied: the provider denied the service access.",
            404: "not_found: no file exists at path.",
            409: "conflict: a file or folder already exists at new_path.",
            422: "invalid_operation: new_path is the same as path, differs only in letter "
            "case, or path is a folder.",
            502: "provider_error: the provider failed, or the file was copied but deleting "
            "the original could not be confirmed. Check both paths before retrying.",
            503: "provider_unavailable: the provider could not be reached. The move may "
            "still have happened.",
        }
    ),
)
def move_file(path: PathQuery, body: MoveRequest, service: Service) -> CommonFileInfo:
    """Move a file: copy it to new_path, then delete it at path. Nothing is overwritten."""
    return service.move(path, body.new_path)
