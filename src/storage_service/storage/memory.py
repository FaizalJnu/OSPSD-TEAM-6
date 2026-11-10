"""A storage backend that keeps files in a Python dict.

Used by the test suite, and handy for trying the API without any provider
(``STORAGE_BACKEND=memory``). Everything is lost when the process stops.

It deliberately copies S3's behavior, limitations included (silent deletes, no
content type in listings), so a test that passes here means something for S3.
"""

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import BinaryIO

from storage_service.errors import FileNotFound, InvalidInput
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
            after = _decode_cursor(cursor, prefix)
            keys = [key for key in keys if key > after]
        page = keys[:limit]
        next_cursor = _encode_cursor(prefix, page[-1]) if len(keys) > limit else None
        files = [replace(self._files[key].info, content_type=None) for key in page]
        return FilePage(files=files, next_cursor=next_cursor)

    def delete(self, key: str) -> None:
        self._files.pop(key, None)

    def delete_many(self, keys: Sequence[str]) -> list[str]:
        for key in keys:
            self._files.pop(key, None)
        return []

    def _lookup(self, key: str) -> _StoredFile:
        stored = self._files.get(key)
        if stored is None:
            raise FileNotFound(f"no file named {key!r}")
        return stored


# A cursor names the prefix it was made for and the last key on its page. It is
# encoded so that callers treat it as opaque, and so that a string this backend did
# not produce can be told apart and rejected, as S3 rejects an unknown token.
_CURSOR_MARK = "mem1."


def _encode_cursor(prefix: str, last_key: str) -> str:
    payload = json.dumps({"prefix": prefix, "after": last_key}).encode()
    return _CURSOR_MARK + base64.urlsafe_b64encode(payload).decode()


def _decode_cursor(cursor: str, prefix: str) -> str:
    """Return the key the cursor continues after, or raise ``InvalidInput``."""
    invalid = InvalidInput("cursor is not a next_cursor this API returned for this prefix")
    if not cursor.startswith(_CURSOR_MARK):
        raise invalid
    try:
        fields = json.loads(base64.urlsafe_b64decode(cursor[len(_CURSOR_MARK) :]))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise invalid from None
    if not isinstance(fields, dict) or fields.get("prefix") != prefix:
        raise invalid
    after = fields.get("after")
    if not isinstance(after, str):
        raise invalid
    return after
