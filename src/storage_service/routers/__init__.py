"""The HTTP layer: URLs, request parsing, responses, and error-to-status mapping.

Routes stay thin. Each one unpacks the HTTP request, calls one FileService
method, and shapes the response. All decisions live in the service.

    GET    /files              list a folder (query: path)
    POST   /files              create a file (multipart form fields "path" and "file")
    PUT    /files              replace an existing file (same form fields)
    POST   /files/{key}        deprecated create, by key (form field "file")
    PUT    /files/{key}        deprecated replace, by key (form field "file")
    GET    /files/download     download a file (query: path)
    DELETE /files              delete a file (query: path)
    GET    /files/metadata     a file's info as JSON (query: path)
    PATCH  /files              move a file (query: path; JSON body: new_path)
    GET    /health             the API is running (no provider call)
    GET    /health/provider    the storage provider can be used (one cheap call)

Each operation lives in its own module: ``listing.py``, ``upload.py`` (create and
replace), ``download.py``, ``metadata.py``, ``delete.py``, ``move.py``, and
``health.py``. ``deps.py`` hands
every route the FileService, and ``error_handlers.py`` gives every error response,
ours and the framework's, the same JSON format.
"""
