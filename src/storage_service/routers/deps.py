"""Dependencies shared by every route module.

``Service`` is the shorthand a route uses to ask for the FileService that
``main.create_app`` stored on the app.
"""

from typing import Annotated

from fastapi import Depends, Request

from storage_service.service import FileService


def get_service(request: Request) -> FileService:
    """Hand each route the FileService that ``main.create_app`` stored on the app."""
    service: FileService = request.app.state.file_service
    return service


# Shorthand for route signatures: "this parameter is the FileService".
Service = Annotated[FileService, Depends(get_service)]
