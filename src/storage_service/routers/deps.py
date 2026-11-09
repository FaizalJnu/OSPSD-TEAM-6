"""Dependencies shared by every route module.

``Service`` is the shorthand a route uses to ask for the FileService that
``main.create_app`` stored on the app. ``PathQuery`` is the shorthand for the
``?path=`` query parameter that names a file.
"""

from typing import Annotated

from fastapi import Depends, Query, Request

from storage_service.service import MAX_PATH_BYTES, FileService


def get_service(request: Request) -> FileService:
    """Hand each route the FileService that ``main.create_app`` stored on the app."""
    service: FileService = request.app.state.file_service
    return service


# Shorthand for route signatures: "this parameter is the FileService".
Service = Annotated[FileService, Depends(get_service)]

# Shorthand for route signatures: a parameter named ``path`` of this type is read from
# ``?path=``. The route passes it on as it arrived, and the service checks it.
PathQuery = Annotated[
    str,
    Query(
        description=(
            "The file's path, with or without a leading '/', such as docs/report.pdf "
            f"(at most {MAX_PATH_BYTES} UTF-8 bytes, counting the leading '/'). "
            "Percent-encode it: in a query string, '+' means a space."
        )
    ),
]
