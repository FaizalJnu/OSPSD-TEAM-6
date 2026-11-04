"""The shared path rule (memo, "Paths").

Callers may send a path with or without a leading ``/``. The service turns it into one
canonical form that starts with ``/``, and every response uses that form. Empty paths,
empty segments, ``.``, ``..``, and a trailing ``/`` are rejected.
"""

from conformance.reference.errors import ContractError

# Team 6's limit, the only one confirmed so far. The shared limit is the smallest one
# all three services support.
MAX_PATH_BYTES = 1024


def canonical_path(raw: str) -> str:
    """Return the canonical form of a file or folder path, or raise ``invalid_request``."""
    path = raw if raw.startswith("/") else "/" + raw
    if path == "/":
        raise _invalid("path must not be empty")
    if path.endswith("/"):
        raise _invalid("path must not end with /")
    if any(segment in ("", ".", "..") for segment in path[1:].split("/")):
        raise _invalid("path must not contain empty, '.' or '..' segments")
    if len(path.encode()) > MAX_PATH_BYTES:
        raise _invalid(f"path must be at most {MAX_PATH_BYTES} UTF-8 bytes")
    return path


def canonical_folder(raw: str) -> str:
    """Like ``canonical_path``, but ``/`` (or ``""``) names the root folder."""
    if raw in ("", "/"):
        return "/"
    return canonical_path(raw)


def _invalid(message: str) -> ContractError:
    return ContractError(400, "invalid_request", message)
