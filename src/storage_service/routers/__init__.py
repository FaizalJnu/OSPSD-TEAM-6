"""The HTTP layer: URLs, request parsing, responses, and error-to-status mapping.

Routes stay thin. Each one unpacks the HTTP request, calls one FileService
method, and shapes the response. All decisions live in the service.

    GET    /files              list files (query: prefix, limit, cursor)
    POST   /files/{key}        create a file (multipart form field named "file")
    PUT    /files/{key}        replace an existing file (same form field)
    GET    /files/{key}        download a file
    DELETE /files/{key}        delete a file
    GET    /metadata/{key}     a file's info as JSON

Each operation lives in its own module: ``listing.py``, ``upload.py`` (create and
replace), ``download.py``, ``metadata.py``, and ``delete.py``. ``deps.py`` hands
every route the FileService, and ``error_handlers.py`` turns our errors into
HTTP responses.
"""
