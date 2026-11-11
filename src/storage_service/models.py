"""The data shapes the service passes around.

These are plain dataclasses rather than FastAPI or Pydantic models, so the core
of the service does not depend on the web framework. FastAPI can still turn
them into JSON when a route returns one.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cloud_storage_api import FileInfo as SharedFileInfo


@dataclass(frozen=True)
class FileInfo:
    """What we know about one stored file.

    key:           The file's full name, including any folder-like prefix,
                   for example "photos/2026/cat.jpg".
    size:          Size in bytes.
    content_type:  MIME type such as "image/jpeg". Always None in listings,
                   because the S3 list call does not return it.
    etag:          The provider's fingerprint of the contents. It changes when
                   the contents change. Treat it as an opaque string: for large
                   uploads it is not an MD5 of the file.
    last_modified: When the provider last wrote this file (timezone-aware UTC).
    """

    key: str
    size: int
    content_type: str | None
    etag: str
    last_modified: datetime


@dataclass(frozen=True)
class FilePage:
    """One page of a file listing.

    next_cursor is None on the last page. Otherwise, pass it back as ``cursor``
    to get the next page. Cursors are opaque: do not parse or build them.

    folders is only filled when the listing used a delimiter: the folder prefixes
    one level down, each ending with the delimiter, for example "docs/sub/".
    """

    files: list[FileInfo]
    next_cursor: str | None
    folders: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FolderEntry:
    """One direct child of a listed folder.

    key:  The child's key. A folder's key has no trailing "/", for example "docs/sub".
    info: The file's info, or None when the child is a folder.
    """

    key: str
    info: FileInfo | None


@dataclass(frozen=True)
class FileDownload:
    """A file being read: its info plus its contents as a stream of chunks.

    Chunks are produced only as the caller asks for them, so a 4 GB file never
    has to fit in memory. Iterate it once; it cannot be rewound.
    """

    info: FileInfo
    chunks: Iterator[bytes]


@dataclass
class CommonFileInfo(SharedFileInfo):
    """Tagged shared file info with Team 6's retained content-type extension."""

    content_type: str | None = None


def common_file_info(info: FileInfo) -> CommonFileInfo:
    """Convert provider metadata to the common model without inventing an S3 id."""
    return CommonFileInfo(
        id=None,
        name=info.key.rsplit("/", 1)[-1],
        path="/" + info.key,
        size=info.size,
        modified_at=info.last_modified.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        etag=info.etag,
        type=None,
        content_type=info.content_type,
    )
