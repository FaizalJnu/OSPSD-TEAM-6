"""The HTTP layer: URLs, request parsing, responses, and error-to-status mapping.

Routes stay thin. Each one unpacks the HTTP request, calls one FileService
method, and shapes the response. All decisions live in the service.

    GET    /files              list files (query: prefix, limit, cursor)
    POST   /files/{key}        create a file (multipart form field named "file")
    PUT    /files/{key}        replace an existing file (same form field)
    GET    /files/download     download a file (query: path)
    DELETE /files              delete a file (query: path)
    GET    /files/metadata     a file's info as JSON (query: path)
    PATCH  /files              move a file (query: path; JSON body: new_path)

Each operation lives in its own module: ``listing.py``, ``upload.py`` (create and
replace), ``download.py``, ``metadata.py``, ``delete.py``, and ``move.py``. ``deps.py`` hands
every route the FileService, and ``error_handlers.py`` gives every error response,
ours and the framework's, the same JSON format.
"""
