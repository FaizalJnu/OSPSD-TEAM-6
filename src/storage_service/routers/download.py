"""Download: ``GET /files/{key}``."""

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from storage_service.routers.deps import Service
from storage_service.routers.error_handlers import error_responses

router = APIRouter()


@router.get(
    "/files/{key:path}",
    response_class=StreamingResponse,
    responses={
        200: {"description": "The file's bytes", "content": {"application/octet-stream": {}}},
        **error_responses(
            {
                400: "InvalidInput: the key violates a key rule.",
                403: "AccessDenied: the provider denied the service access.",
                404: "FileNotFound: no file exists under the key.",
                502: "ProviderError: the storage provider rejected the request.",
                503: "ProviderUnavailable: the storage provider could not be reached.",
            }
        ),
    },
)
def download_file(key: str, service: Service) -> StreamingResponse:
    download = service.download(key)
    info = download.info
    filename = info.key.rsplit("/", 1)[-1]
    headers = {
        "Content-Length": str(info.size),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "ETag": f'"{info.etag}"',
        # Tell browsers to trust our Content-Type instead of guessing from the bytes.
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(download.chunks, media_type=info.content_type, headers=headers)
