"""Delete: ``DELETE /files/{key}``."""

from fastapi import APIRouter, Response

from storage_service.routers.deps import Service

router = APIRouter()


@router.delete("/files/{key:path}", status_code=204)
def delete_file(key: str, service: Service) -> Response:
    service.delete(key)
    return Response(status_code=204)
