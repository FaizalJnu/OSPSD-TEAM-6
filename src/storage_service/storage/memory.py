"""A storage backend that keeps files in a Python dict.

Used by the test suite, and handy for trying the API without any provider
(``STORAGE_BACKEND=memory``). Everything is lost when the process stops.

It deliberately copies S3's behavior, limitations included (silent deletes, no
content type in listings), so a test that passes here means something for S3.
"""

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import BinaryIO

from storage_service.errors import FileNotFound
from storage_service.models import FileDownload, FileInfo, FilePage


@dataclass(frozen=True)
class _StoredFile:
    info: FileInfo
    data: bytes


class InMemoryStorage:
    def __init__(self) -> None:
        self._files: dict[str, _StoredFile] = {}

    def put(self, key: str, stream: BinaryIO, content_type: str) -> FileInfo:
        data = stream.read()  # Reading it all is fine for a test double; S3Storage streams.
        info = FileInfo(
            key=key,
            size=len(data),
            content_type=content_type,
            etag=hashlib.md5(data, usedforsecurity=False).hexdigest(),
            last_modified=datetime.now(UTC),
        )
        self._files[key] = _StoredFile(info=info, data=data)
        return info

    def get(self, key: str) -> FileDownload:
        stored = self._lookup(key)
        return FileDownload(info=stored.info, chunks=iter([stored.data]))

    def stat(self, key: str) -> FileInfo:
        return self._lookup(key).info

    def list_files(self, prefix: str, limit: int, cursor: str | None) -> FilePage:
        keys = sorted(key for key in self._files if key.startswith(prefix))
        if cursor is not None:
            keys = [key for key in keys if key > cursor]
        page = keys[:limit]
        next_cursor = page[-1] if len(keys) > limit else None
        files = [replace(self._files[key].info, content_type=None) for key in page]
        return FilePage(files=files, next_cursor=next_cursor)

    def delete(self, key: str) -> None:
        self._files.pop(key, None)

    def _lookup(self, key: str) -> _StoredFile:
        stored = self._files.get(key)
        if stored is None:
            raise FileNotFound(f"no file named {key!r}")
        return stored
