"""Files kept in a dict, keyed by canonical path.

Folders are implicit, as on S3: a folder exists while some file's path is under it.
Paths are compared exactly, so ``/A.txt`` and ``/a.txt`` are two files (S3's behavior).
"""

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from conformance.reference.errors import conflict, invalid_operation, not_found


@dataclass(frozen=True)
class StoredFile:
    path: str
    id: str
    data: bytes
    modified_at: datetime


@dataclass(frozen=True)
class Folder:
    path: str


class Store:
    def __init__(self) -> None:
        self._files: dict[str, StoredFile] = {}

    def create(self, path: str, data: bytes) -> StoredFile:
        if self._exists(path):
            raise conflict(path)
        if self._file_above(path) is not None:
            raise invalid_operation(f"{self._file_above(path)} is a file, not a folder")
        return self._write(path, data, uuid.uuid4().hex)

    def replace(self, path: str, data: bytes) -> StoredFile:
        stored = self._files.get(path)
        if stored is None:
            if self._is_folder(path):
                raise invalid_operation(f"{path} is a folder")
            raise not_found(path)
        return self._write(path, data, stored.id)

    def get(self, path: str) -> StoredFile:
        stored = self._files.get(path)
        if stored is None:
            if self._is_folder(path):
                raise invalid_operation(f"{path} is a folder")
            raise not_found(path)
        return stored

    def list_folder(self, folder: str) -> list[StoredFile | Folder]:
        """Return the direct children of ``folder``, sorted by path."""
        if folder in self._files:
            raise invalid_operation(f"{folder} is a file")
        if folder != "/" and not self._is_folder(folder):
            raise not_found(folder)
        base = "" if folder == "/" else folder
        children: dict[str, StoredFile | Folder] = {}
        for path, stored in self._files.items():
            if not path.startswith(base + "/"):
                continue
            name, _, rest = path[len(base) + 1 :].partition("/")
            child = f"{base}/{name}"
            children[child] = Folder(child) if rest else stored
        return [children[path] for path in sorted(children)]

    def move(self, path: str, new_path: str) -> StoredFile:
        stored = self._files.get(path)
        if stored is None:
            if self._is_folder(path):
                raise invalid_operation("only files can be moved")
            raise not_found(path)
        if new_path.casefold() == path.casefold():
            raise invalid_operation("new_path must differ from path by more than letter case")
        if self._exists(new_path):
            raise conflict(new_path)
        if self._file_above(new_path) is not None:
            raise invalid_operation(f"{self._file_above(new_path)} is a file, not a folder")
        del self._files[path]
        moved = replace(stored, path=new_path)
        self._files[new_path] = moved
        return moved

    def delete(self, path: str) -> None:
        if self._files.pop(path, None) is not None:
            return
        under = [key for key in self._files if key.startswith(path + "/")]
        if not under:
            raise not_found(path)
        for key in under:
            del self._files[key]

    def _write(self, path: str, data: bytes, file_id: str) -> StoredFile:
        stored = StoredFile(path=path, id=file_id, data=data, modified_at=datetime.now(UTC))
        self._files[path] = stored
        return stored

    def _exists(self, path: str) -> bool:
        return path in self._files or self._is_folder(path)

    def _is_folder(self, path: str) -> bool:
        return any(key.startswith(path + "/") for key in self._files)

    def _file_above(self, path: str) -> str | None:
        """The first parent of ``path`` that is a file, if any."""
        segments = path.split("/")
        for end in range(2, len(segments)):
            parent = "/".join(segments[:end])
            if parent in self._files:
                return parent
        return None
