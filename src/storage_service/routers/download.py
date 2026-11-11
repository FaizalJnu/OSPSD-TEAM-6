"""Download: ``GET /files/download?path=``."""

from collections.abc import Iterator
from contextlib import suppress
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.types import Send

from storage_service.routers.deps import PathQuery, Service
from storage_service.routers.error_handlers import error_responses, log_interrupted_download

router = APIRouter()


@router.get(
    "/files/download",
    response_class=StreamingResponse,
    responses={
        200: {"description": "The file's bytes", "content": {"application/octet-stream": {}}},
        **error_responses(
            {
                400: "invalid_request: the path is missing or violates a path rule.",
                403: "permission_denied: the provider denied the service access.",
                404: "not_found: no file exists at the path.",
                502: "provider_error: the storage provider rejected the request.",
                503: "provider_unavailable: the storage provider could not be reached.",
            }
        ),
    },
)
def download_file(path: PathQuery, service: Service, request: Request) -> StreamingResponse:
    download = service.download(path)
    info = download.info
    filename = info.key.rsplit("/", 1)[-1]
    headers = {
        "Content-Length": str(info.size),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "ETag": f'"{info.etag}"',
        # Tell browsers to trust our Content-Type instead of guessing from the bytes.
        "X-Content-Type-Options": "nosniff",
    }
    chunks = _logging_failures(download.chunks, request, info.size)
    return _DownloadResponse(chunks, media_type=info.content_type, headers=headers)


class _CutOff(Exception):
    """Reading the file failed after the 200 headers were sent. Already logged."""


class _DownloadResponse(StreamingResponse):
    """A streaming response that is left unfinished if reading the file fails.

    Once the 200 status and headers are sent, an error can no longer reach the caller.
    Re-raising it would not help: Starlette would only report "response already
    started". Finishing the response normally would not work either: the server rejects
    a body shorter than its ``Content-Length``, and that error would reach the 500
    handler. So the response stops without finishing. The server closes the connection
    (uvicorn logs "ASGI callable returned without completing response."), and the
    caller receives fewer bytes than ``Content-Length``, which is how it can tell.
    """

    async def stream_response(self, send: Send) -> None:
        with suppress(_CutOff):
            await super().stream_response(send)


def _logging_failures(chunks: Iterator[bytes], request: Request, size: int) -> Iterator[bytes]:
    """Stream ``chunks``. If reading them fails, log it and stop with ``_CutOff``."""
    sent = 0
    try:
        for chunk in chunks:
            yield chunk
            sent += len(chunk)  # asking for the next chunk means this one was sent
    except Exception as exc:
        log_interrupted_download(request, exc, bytes_sent=sent, size=size)
        raise _CutOff from exc
