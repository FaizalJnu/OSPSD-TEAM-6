"""Download: ``GET /files/download?path=``."""

from collections.abc import Iterator
from contextlib import suppress
from urllib.parse import quote

from cloud_storage_api import DownloadStream
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from storage_service.errors import ProviderError
from storage_service.routers.deps import PathQuery, SharedStorage
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
def download_file(path: PathQuery, storage: SharedStorage, request: Request) -> StreamingResponse:
    download = storage.open_download(path)
    try:
        info = download.info
        if info.size is None:
            raise ProviderError(
                "the provider returned a download without a file size", storage_call="get"
            )
        headers = {
            "Content-Length": str(info.size),
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(info.name)}",
            "X-Content-Type-Options": "nosniff",
        }
        if info.etag is not None:
            headers["ETag"] = f'"{info.etag}"'
        chunks = _logging_failures(download.chunks(), request, info.size)
        return _DownloadResponse(
            chunks,
            download=download,
            media_type=getattr(info, "content_type", None),
            headers=headers,
        )
    except BaseException:
        download.close()
        raise


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

    def __init__(
        self,
        chunks: Iterator[bytes],
        *,
        download: DownloadStream,
        media_type: str | None,
        headers: dict[str, str],
    ) -> None:
        super().__init__(chunks, media_type=media_type, headers=headers)
        self._download = download

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._download.close()

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
