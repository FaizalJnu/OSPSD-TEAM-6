"""Download: ``GET /files/{key}``."""

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from storage_service.routers.deps import Service

router = APIRouter()


@router.get("/files/{key:path}")
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
