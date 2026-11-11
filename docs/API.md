# HTTP API

What each operation accepts and returns, and how it fails. The shared sections
(keys, paths, file info, and errors) apply to every operation. Each operation section has
one owner, who keeps it in agreement with the code and the tests.

The running service also serves interactive docs at `/docs` and the schema at
`/openapi.json`. Both are generated from the code. They show the routes, inputs,
response fields, and each route's error statuses with the [error format](#error-format).
This page explains when each error happens and whether retrying helps.

Examples assume the server runs locally, as in the README:

```bash
B=http://127.0.0.1:8000
```

## Operations

| Operation | Method and path | Owner |
|---|---|---|
| [Create](#create-and-replace) | `POST /files/{key}` | Debasmith Mandal |
| [Replace](#create-and-replace) | `PUT /files/{key}` | Debasmith Mandal |
| [Download](#download) | `GET /files/download?path=` | Vikram Markali |
| [Metadata](#metadata) | `GET /files/metadata?path=` | Darsh Shani |
| [Delete](#delete) | `DELETE /files?path=` | Faizal Rahman |
| [Move](#move) | `PATCH /files?path=` | Vikram Markali |
| [List](#list) | `GET /files` | Prateek Saxena |

## Keys

A **key** is a file's full name, including any folder-like prefix, such as
`photos/2026/cat.jpg`. The caller chooses it when creating a file. The `key` field in
[file info](#file-info) is the same string, so a key returned by one operation can be
used in the others.

A key must:

* be non-empty and at most 1024 bytes when encoded as UTF-8
* contain no ASCII control characters (code points 0 to 31, and 127)
* not start or end with `/`, and not contain `//`
* not have a segment (the text between slashes) that is exactly `.` or `..`

An operation given a key that breaks a rule returns 400 `invalid_request` without
contacting the provider.

In a Create or Replace URL, the key is everything after `/files/`, slashes included.
Percent-encode characters that cannot appear in a URL path. For example,
`with spaces.txt` is sent as `/files/with%20spaces.txt`. The rules apply to the
decoded key.

## Paths

Download and Metadata name their file, Delete its file or folder, and Move its file,
with a **path** in the `path` query parameter. Move's destination is a path too, in its
JSON body. The other operations still take a [key](#keys) in the URL until they move to
the shared routes.

A path can be sent with or without its leading `/`: `docs/report.pdf` and
`/docs/report.pdf` name the same file. Its canonical form always starts with `/`, and
the file's key is the canonical path without that `/`, so a file stored under the key
`docs/report.pdf` is at the path `/docs/report.pdf`. Files already in the bucket keep
their keys.

A path must:

* be non-empty, and not be `/` alone
* be at most 1024 bytes when encoded as UTF-8, counting the leading `/`
* contain no ASCII control characters (code points 0 to 31, and 127)
* not end with `/`, and not contain `//`
* not have a segment (the text between slashes) that is exactly `.` or `..`

An operation given a path that breaks a rule, or no `path` at all, returns 400
`invalid_request` without contacting the provider.

Percent-encode the path in a query string. A `+` there means a space, so a literal `+`
must be sent as `%2B`. `curl -G --data-urlencode "path=$P"` does the encoding for you.

## File info

Create and Replace still return the legacy file info object. Metadata and Move return the shared model described in [Metadata](#metadata). List returns file info
objects in its `files` array.

| Field | JSON type | Meaning |
|---|---|---|
| `key` | string | The file's full name, including any folder-like prefix. See [Keys](#keys). |
| `size` | integer | Size of the contents in bytes. |
| `content_type` | string or null | MIME type, such as `image/jpeg`. For files uploaded through this service, the server picks it from the key's extension (`application/octet-stream` when the extension is unknown) and ignores the type the client sends. Always `null` in listings, because the S3 list call does not return it. |
| `etag` | string | The provider's fingerprint of the contents, without surrounding quotes. It changes when the contents change. Treat it as an opaque string: for large uploads it is not an MD5 of the file. |
| `last_modified` | string | When the provider last wrote this file, as an ISO 8601 timestamp in UTC ending in `Z`. The number of fractional-second digits can vary, so parse it instead of comparing strings. |

Example, from the in-memory backend:

```json
{
  "key": "photos/2026/cat.jpg",
  "size": 17,
  "content_type": "image/jpeg",
  "etag": "08a83d6686281a5a292732435b21f83a",
  "last_modified": "2026-10-14T00:20:31.589428Z"
}
```

## Errors

### Error format

Every error response has this JSON body, including a path with no route, a method
the path does not accept, a request body that cannot be read, and a bug in the
service:

```json
{"error": {"code": "not_found", "message": "no file named 'photos/2026/cat.jpg'"}}
```

`error.code` is the stable identifier in the table below. `error.message` is a safe explanation for people.

### Error types

| `error` | Status | When it happens | Does retrying help? |
|---|---|---|---|
| `invalid_request` | 400 | A key breaks a [key rule](#keys), the List `prefix` is longer than 1024 bytes, the List `limit` is not a whole number from 1 to 1000, or Create or Replace is missing the `file` form field or sends a `multipart/form-data` body that cannot be read (for example, no boundary). | No. Change the input. |
| `permission_denied` | 403 | The provider refused the service's credentials or permissions, for example a wrong secret key or a bucket policy that does not allow the operation. This is the service's configuration, not the caller's. | No, not until whoever runs the service fixes the credentials or permissions. |
| `not_found` | 404 | No file exists under the key (Download, Metadata, Replace), or no file or folder exists at the path (Delete). | Not until a file is created there. |
| `conflict` | 409 | Create was called for a key that already has a file. | No. Use Replace, or Delete the file first. |
| `file_too_large` | 413 | The upload to Create or Replace is larger than `MAX_UPLOAD_BYTES` (default 1 GiB). | No, not with the same file. |
| `provider_error` | 502 | The provider refused the request for another reason: a missing bucket, an unsupported request, and so on. Usually a configuration problem, but it can also be a provider-side failure, such as throttling or an internal error, that lasted through the client's own retries. | Usually not: fix the configuration first. If the configuration is correct, retrying later sometimes succeeds. |
| `provider_unavailable` | 503 | The provider could not be reached: network failure, timeout, and so on. | Retrying later may help. |
| `route_not_found` | 404 | The path matches no route, for example `GET /nothing`. Unlike `not_found`, it means the URL is wrong. | No. Fix the URL. |
| `method_not_allowed` | 405 | The path exists, but not for this method, for example `POST /files`. The `Allow` header lists every method the path accepts, such as `POST, PUT` for `/files/{key}`. | No. Use an allowed method. |
| `internal_error` | 500 | A bug in the service. `error.message` is always `the service failed unexpectedly`, whatever went wrong. | Not until it is fixed. After a failed Create, Replace, or Delete, check with Metadata first: the write may have happened. |

`route_not_found` and `method_not_allowed` happen before any operation runs, and
`internal_error` can happen in any operation, so the operation sections below do not
repeat them.

When FastAPI or Starlette rejects the input before our code runs, `error.message` starts with
the field's name: `limit: ...` for `limit=abc`, `file: Field required` for a missing
`file` field, and `file: Missing boundary in multipart.` for a multipart body without a
boundary.

### After a failed write

A 502 or 503 from Create, Replace, or Delete does not prove that nothing changed.
Create and Replace store the file and then read its info back from the provider. If
that read fails, the caller gets the error although the new contents were stored. A
timeout can also hide a write or delete that the provider completed. Before retrying,
check the file with Metadata. Retrying a Create whose file was stored returns 409.

A folder Delete can also fail with some of its files gone and others still there. See
Retry under [Delete](#delete).

### What stays internal

`error.code` and `error.message` describe this service, not the provider. The provider's own error
code (such as `NoSuchBucket` or `SignatureDoesNotMatch`), its message (which on OCI
names the namespace and bucket), and stack traces never appear in a response. A
caller can tell the failure classes apart from `error.code` alone: `invalid_request`
(the input), `not_found` (no such file), `permission_denied` (the service's
permissions), and `provider_error` or `provider_unavailable` (the provider failed).
The provider's code goes to the [failure log](#failure-logs) for whoever runs the
service.

### Failure logs

Every failed request writes one JSON line to the server's log (stderr), for example:

```json
{"level": "ERROR", "event": "request_failed", "operation": "create_file", "status": 503, "error": "provider_unavailable", "detail": "could not reach the storage provider", "provider_involved": true, "storage_call": "put", "provider_code": "EndpointConnectionError", "write_outcome": "unknown"}
```

| Field | Meaning |
|---|---|
| `level` | `WARNING` when the caller can fix it (400, 404, 405, 409, 413). `ERROR` when whoever runs the service has to act (403 `permission_denied`, 500, 502, 503, and an interrupted download). |
| `operation` | `create_file`, `replace_file`, `download_file`, `get_metadata`, `delete_file`, or `list_files`. `null` when the request matched no operation (404 `route_not_found`, 405 `method_not_allowed`). |
| `status`, `error`, `detail` | The status, common code and message the caller received (the log keeps flat fields). For an interrupted download, `status` is the 200 the caller received, and `error` and `detail` name the failure it could not be told about. |
| `provider_involved` | `true` when a storage call raised the error or decided it (a 404 or 409 from the existence check). `false` when the request was rejected before storage was called. `null` after a 500 `internal_error`: a bug can strike anywhere, so we cannot tell. |
| `storage_call` | The storage call involved: `stat`, `put`, `get`, `list_files`, `delete`, or `delete_many`, or `null`. |
| `provider_code` | Only when the provider or its SDK named the failure, for example `NoSuchBucket`, `403`, or `EndpointConnectionError`. Never sent to the caller. |
| `write_outcome` | Create, Replace, and Delete only. `not_attempted` when the request failed before the write call, so nothing changed. `unknown` when the write call itself failed, or after a 500 `internal_error`: the provider may have completed it (see [After a failed write](#after-a-failed-write)). |
| `interrupted`, `bytes_sent`, `size` | Download only, when reading the file failed after the 200 status and headers were sent: `interrupted` is `true`, `bytes_sent` is how many bytes the caller was sent, and `size` is the file's size, the `Content-Length` it was promised. |

Expected failures are logged without a traceback. Only a bug includes one, after its
JSON line: a 500 `internal_error`, or a download interrupted by one. After a 500,
Starlette hands the exception to the server, so uvicorn prints the same traceback a
second time, starting with `Exception in ASGI application`.

The JSON lines never contain credentials or the provider's message. A 500's traceback
shows the bug's own exception, including its message. With no logging configured,
Python prints these lines (`WARNING` and above) to stderr, as uvicorn does.

### Bucket checks

After an ambiguous S3 HEAD 404/NotFound, Metadata and the existence checks for
Create, Replace, and Delete probe the bucket before reporting a missing file.
An accessible bucket preserves 404 `not_found`. A bucket the provider denies
access to returns 403 `permission_denied` with detail "the storage provider denied access
to the configured bucket". Any other failed probe, such as a missing bucket, returns
502 `provider_error` with detail "the configured bucket does not exist or is not
accessible". The detail contains neither the bucket name nor the raw provider error
code. A connection failure during the probe returns
503 `provider_unavailable`. Create, Replace, and Delete stop before writing if
this check fails.

The probe adds one SDK call per ambiguous miss and requires bucket-read
permissions. It does not lock the bucket against concurrent changes. Successful
reads and explicit `NoSuchKey` responses do not need the probe.

### Known bugs

No known error-mapping bugs remain on OCI. Fixed bugs and their records are in
[fixesRequired.md](../fixesRequired.md).

## Filling in an operation section

Each owner writes these headings for their operation. Link to the shared sections
above instead of repeating them.

* **Meaning:** what the operation does for the caller, and whether it only reads or
  changes stored files.
* **Request:** the method and path, and every path, query, or form input: whether it
  is required, its default, and its constraints.
* **Success:** the status code and every response field or header, with its meaning.
* **Side effects:** what changes in the bucket, and what is guaranteed to stay the
  same. "None" for reads.
* **Errors:** each status and error type this operation can return, and when.
* **Retry:** whether repeating the request is safe, after a success and after each
  error.
* **Assumptions:** anything callers can observe that depends on the provider or on a
  decision we made.
* **Example:** a complete curl request with its expected output, how to choose a
  sample key, and how to clean up afterwards.

## Create and Replace

`POST /files/{key}` and `PUT /files/{key}`. Owner: **Debasmith Mandal**.

### Meaning

Create stores a new file under a key that is not taken yet. Replace overwrites the
contents of a file that already exists. Both change stored files.

### Request

* `POST /files/{key}` (Create) or `PUT /files/{key}` (Replace). The key follows the
  [key rules](#keys).
* Body: `multipart/form-data` with one required form field named `file`, holding the
  contents. Any size from 0 bytes up to `MAX_UPLOAD_BYTES` (default 1 GiB). Empty files
  are allowed.
* The filename and content type the client sends with the file are ignored.

### Success

* Create returns `201 Created`. Replace returns `200 OK`.
* The body is the stored file's [file info](#file-info): `key` is the key from the URL,
  `size` is the number of bytes received, `content_type` is picked from the key's
  extension, `etag` is the provider's fingerprint of the new contents, and
  `last_modified` is when the provider stored them.
* A Metadata request right afterwards returns the same file info.

### Side effects

* Create: a file now exists under the key.
* Replace: the old contents are gone. `size`, `etag`, and `last_modified` describe the
  new contents.
* Local validation failures change nothing. A provider failure can leave an uncertain write even when access is denied. After a 400 or 413, the key is
  as it was before. After a 409, the existing file is unchanged. After a failed Replace,
  the old contents are still there.

### Errors

| Status | `error` | When |
|---|---|---|
| 400 | `invalid_request` | The key breaks a [key rule](#keys), the `file` form field is missing, or the `multipart/form-data` body cannot be read: no boundary, more than 1000 files, or a text field over 1 MB. |
| 403 | `permission_denied` | The provider denied the service's credentials or permissions. |
| 404 | `not_found` | Replace only: no file exists under the key. |
| 409 | `conflict` | Create only: a file already exists under the key. |
| 413 | `file_too_large` | The upload is larger than `MAX_UPLOAD_BYTES`. |
| 502 | `provider_error` | The provider refused the write, usually because of configuration. |
| 503 | `provider_unavailable` | The provider could not be reached. |

### Retry

* After a success, repeating Create returns 409. Repeating Replace with the same
  contents is safe: the contents and `etag` stay the same, and `last_modified` moves
  to the time of the latest write (OCI stores it to the second).
* After a 400, 404, 409, or 413, change the request first. Repeating it unchanged fails
  the same way.
* After a 502 or 503, the write may or may not have happened (see
  [After a failed write](#after-a-failed-write)). Check with Metadata before retrying.

### Assumptions

* The server picks `content_type` from the key's extension (`application/octet-stream`
  when the extension is unknown) and ignores what the client claims.
* The size limit is checked after the whole upload has arrived in a temp file on the
  server, so an oversized upload uses bandwidth and temp space before it is rejected.
* Create and Replace check whether the key exists and then write, in two separate
  provider calls. Two clients racing on the same key can both pass the check, and the
  last write wins.
* With S3-compatible providers that return generic HEAD 404s, every successful Create
  makes an extra `head_bucket` call: its existence check must miss. A small upload
  therefore takes four SDK calls instead of three: `head_object`, `head_bucket`,
  `upload_fileobj` (one `put_object`), then `head_object` to read back metadata.
  Multipart uploads require more calls. Replace of an existing file does not probe
  the bucket; Replace, Delete, and Metadata of a missing file do. These probes
  require bucket-read permissions; see [Bucket checks](#bucket-checks).
* For uploads larger than 8 MB, the S3 backend uses a multipart upload, and `etag` is
  not an MD5 of the file.

### Example

Use a key under a prefix of your own, such as `demo/<your-name>/`, so cleanup is easy.

```bash
B=http://127.0.0.1:8000
printf 'hello' > hello.txt
curl -s -F "file=@hello.txt" $B/files/demo/me/hello.txt           # 201
curl -s -F "file=@hello.txt" $B/files/demo/me/hello.txt           # 409 conflict
printf 'hello again' > hello2.txt
curl -s -X PUT -F "file=@hello2.txt" $B/files/demo/me/hello.txt   # 200, size 11, new etag
curl -s -X DELETE "$B/files?path=demo/me/hello.txt"               # clean up: 204
```

The Create response looks like this (`etag` and `last_modified` will differ):

```json
{"key": "demo/me/hello.txt", "size": 5, "content_type": "text/plain", "etag": "5d41402abc4b2a76b9719d911017c592", "last_modified": "2026-10-14T18:00:00Z"}
```

## Download

`GET /files/download?path=`. Owner: **Vikram Markali**.

**Changed:** `GET /files/{key}` no longer exists. It was replaced by
`GET /files/download?path=`, the route the shared contract uses, so send the key as
`?path=` instead. A `GET` on the old URL now returns 405 `method_not_allowed`, because
`/files/{key}` still accepts Create and Replace. Stored files keep their names, so no
data moves.

### Meaning

Returns the contents of the file at a path, as a download. It only reads: nothing in
the bucket changes.

### Request

The required query parameter `path` names the file:
`/files/download?path=docs/report.pdf` downloads the file stored as `docs/report.pdf`.
It follows the shared [path rules](#paths). There is no request body. A missing or
invalid path is rejected before storage is called.

### Success

Status **200**. The body is the file's exact bytes, streamed from the provider in
pieces, so large files never have to fit in the server's memory. The headers:

| Header | Meaning |
|---|---|
| `Content-Type` | The type stored with the file at upload, the same value as `content_type` in [file info](#file-info). For `text/*` types the server adds `; charset=utf-8`, for example `text/plain; charset=utf-8`. |
| `Content-Length` | The file's size in bytes, the same value as `size` in file info. |
| `ETag` | The file's `etag` from file info, wrapped in double quotes as HTTP requires, for example `"08a83d6686281a5a292732435b21f83a"`. |
| `Content-Disposition` | `attachment; filename*=UTF-8''<name>`, where `<name>` is the last segment of the key, percent-encoded as UTF-8. `docs/résumé.pdf` gives `attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf`, so browsers save the file instead of displaying it. |
| `X-Content-Type-Options` | Always `nosniff`: browsers must use `Content-Type` instead of guessing the type from the bytes. |

### Side effects

None.

### Errors

The body uses the [error format](#error-format).

| Status | `error` | When |
|---|---|---|
| 400 | `invalid_request` | `path` is missing or breaks a [path rule](#paths). The provider is not contacted. |
| 403 | `permission_denied` | The provider denied the service's credentials or permissions. |
| 404 | `not_found` | No file exists at the path. |
| 502 | `provider_error` | The provider refused the request, for example because of a missing bucket. |
| 503 | `provider_unavailable` | The provider could not be reached or timed out. |

These statuses are only possible before the body starts. If reading the file fails
after the 200 status and headers are sent, the service stops sending and the server
closes the connection before `Content-Length` bytes arrive. There is no error body.
Compare the received size with `Content-Length` to detect this: curl, for example,
exits with code 18 (partial file). The service still logs the failure, as one line
with `"status": 200` and `"interrupted": true` (see [Failure logs](#failure-logs)).
uvicorn also logs `ASGI callable returned without completing response.`

### Retry

Download only reads, so repeating it is always safe. After a 503, retrying later may
succeed. After a 400 or 404, retrying the same request gives the same result until the
path or the stored files change. A 502 is usually a configuration problem and repeats
until the configuration changes, but it can also be a passing provider-side failure, so
retrying later sometimes succeeds (see [Error types](#error-types)). A cut-off body can
be retried from the start.

### Assumptions

* The `ETag` header is quoted, while every JSON `etag` field (Create, Replace,
  Metadata, List) has no quotes. They are the same value: strip the quotes to compare.
* `Content-Type` is the type the provider stored with the file. For files uploaded
  through this service, that is the type picked from the key's extension. For files
  uploaded another way, such as the provider's console, it is whatever that tool stored,
  which may not match the extension. The OCI Console stored `text/plain` for a `.txt`
  file. If the provider stored no type, the response has no `Content-Type` header, and
  Metadata reports `content_type` as `null`.
* The file name in `Content-Disposition` is only a suggestion to the client. The
  download is the same file whatever name it is saved under.
* A path that names a folder (other files are stored under `path/`) returns 404
  `not_found`, because S3 has no object at that path. What Download should return
  for a folder is still open in the shared contract (Dayana20/ospsd26-cloud-storage
  issue #8).

### Example

Pick any path, for example `examples/hello.txt`. Create a file there first (Download
needs an existing file), download it with its headers, compare the bytes, then delete
it. In Windows `cmd.exe`:

```bat
set B=http://127.0.0.1:8000
echo hello from the download example> hello.txt
curl.exe -s -F "file=@hello.txt" %B%/files/examples/hello.txt
curl.exe -s -D - -o back.txt "%B%/files/download?path=examples/hello.txt"
fc /b hello.txt back.txt
curl.exe -i -X DELETE "%B%/files?path=examples/hello.txt"
del hello.txt back.txt
```

`-D -` prints the headers and `-o back.txt` saves only the body. (`-i -o` would put the
headers into the file too.) Expected output, with your own `etag` and `date`:

```text
HTTP/1.1 200 OK
date: Wed, 14 Oct 2026 18:48:55 GMT
server: uvicorn
content-length: 33
content-disposition: attachment; filename*=UTF-8''hello.txt
etag: "d5dd2e893e86e4e636ad6261081837ed"
x-content-type-options: nosniff
content-type: text/plain; charset=utf-8
```

`fc /b` then prints `FC: no differences encountered`, and the delete returns
`HTTP/1.1 204 No Content`. To check the cleanup,
`curl.exe -i "%B%/files/download?path=examples/hello.txt"` now returns `404` with `{"error":{"code":"not_found","message":"..."}}`. On macOS or Linux, use
`B=http://127.0.0.1:8000`, `$B` instead of `%B%`, `curl` instead of `curl.exe`,
`cmp hello.txt back.txt` instead of `fc /b`, and `rm` instead of `del`.

## Metadata

`GET /files/metadata?path=`. Owner: **Darsh Shani**.

The required `path` query parameter accepts an optional leading slash and follows
[Paths](#paths). The legacy `/metadata/{key}` route is removed. Metadata is
registered before the legacy catch-all Download route so it cannot be interpreted
as a request to download an object named `metadata`.

Success returns 200 and shared file info: `id` (null on S3), `name`, canonical
`path`, byte `size`, UTC `modified_at` ending in `Z`, opaque unquoted `etag`, and
`type` (null outside listings). Team 6 retains `content_type` as an extension.
Create, Replace, and List keep their old models until their owners migrate them.

Reading metadata performs `stat` only and neither downloads contents nor writes.
A successful S3 HEAD gives metadata; an ambiguous miss adds a bucket probe.
400 means malformed/missing input, 403 provider denial, 404 missing entry in
accessible storage, 502 another provider failure/missing bucket, 503 an
unreachable provider, and 500 an unexpected failure. Every JSON error uses the
nested [error format](#error-format). A read does not lock against concurrent
writes.

```bash
curl -G --data-urlencode 'path=/docs/report.pdf' "$B/files/metadata"
```

## Delete

`DELETE /files?path=`. Owner: **Faizal Rahman**.

**Changed:** `DELETE /files/{key}` no longer exists. Send the key as `?path=` instead.
Stored files keep their names, so no data moves.

### Meaning

Remove one file, or a folder and everything under it. This changes stored files.

### Request

The required query parameter `path` names the file or folder:
`/files?path=docs/report.pdf` deletes the file stored as `docs/report.pdf`, and
`/files?path=docs` deletes every file whose key starts with `docs/`, at every depth.
It follows the shared [path rules](#paths), so a folder has no trailing `/`, and `/`
alone is rejected: this route cannot empty the bucket. There is no request body. A
missing or invalid path is rejected before storage is called.

### Success

**204** with an empty body.

### Side effects

S3 has no real folders: a folder is the files whose keys share a prefix. The service
first looks for a file at the path (`stat`, an S3 `HeadObject`).

* **If there is a file,** it is deleted (`delete`, an S3 `DeleteObject`). Nothing else
  in the bucket changes. S3 allows a file and a folder at the same path, such as `docs`
  and `docs/a.txt`. Then only the file is deleted.
* **If there is no file,** the service lists every key under `<path>/` (`list_files`,
  an S3 `ListObjectsV2` per 1000 keys), then deletes them (`delete_many`, an S3
  `DeleteObjects` per 1000 keys). The `/` is part of the match, so deleting `docs`
  leaves `docs2/a.txt` and `docs-backup/b.txt` alone.

Afterwards, Download and Metadata return 404 for every deleted file, and List no longer
includes them. If the check or the listing fails, nothing is deleted and nothing
changes.

### Errors

Responses use the shared [error format](#error-format):

| Status | Error | When |
|---|---|---|
| 400 | `invalid_request` | The path is missing or breaks a path rule. The provider is not contacted. |
| 403 | `permission_denied` | The provider denied the service's credentials or permissions. |
| 404 | `not_found` | No file exists at the path and no file is under it. Nothing is deleted. `error.message` is `no file or folder at '/<path>'`. |
| 502 | `provider_error` | The provider rejects the check, the listing, or the delete, for example because of a missing bucket. Or a folder delete did not finish (see below). |
| 503 | `provider_unavailable` | The provider cannot be reached. |

An ambiguous HEAD 404 is checked against the bucket before reporting a missing
file, and nothing is deleted if that check fails. A missing bucket returns 502
`provider_error`, a denied one 403 `permission_denied`, and a connection failure during that
check 503. See [Bucket checks](#bucket-checks).

A folder delete is not all-or-nothing. It stops at the first batch of up to 1000 keys
that does not finish:

| What went wrong | Response | What may have changed |
|---|---|---|
| The check or the listing failed | That failure's own status | Nothing. |
| The first batch failed as a whole | That failure's own status: 403, 502, or 503 | That batch may be partly or fully deleted. |
| A later batch failed, whatever the cause | 502 `provider_error` | Every earlier batch is deleted. That batch may be too. |
| The provider reported keys it could not delete, in any batch | 502 `provider_error` | The other keys of that batch and every earlier batch are deleted. |

The last two return the `error.message`
`the delete of folder '/docs' did not finish; some files may remain`, with the
canonical path of the folder. They are always 502, even for a timeout, because the
caller most needs to know that the folder may be partly deleted.

### Retry

* After a success, repeating the request returns 404.
* After a 400 or 404, repeating it unchanged gives the same result.
* After a 502 or 503 for a file, the file may or may not be gone (see
  [After a failed write](#after-a-failed-write)). Check with Metadata: 404 means it
  is gone. A 502 is usually a configuration problem, but it can also be a
  provider-side failure that outlasted the client's retries, so retrying later
  sometimes succeeds. Retrying later may help after a 503.
* After an error for a folder, List with `prefix=<path>/` shows what remains, and
  repeating the request deletes it. The retry returns 204 when it finishes, or 404
  if the failed request had already removed everything.

### Assumptions

* The 404 for a missing file or folder is our rule, not the provider's. S3's
  `DeleteObject` succeeds silently for a missing key, so the service checks first.
* The check and the delete are two separate calls. If another client deletes the
  file between them, this request still returns 204. If another client replaces the
  file between them, the new contents are deleted. The same race is listed under
  [Known limitations](../README.md#known-limitations).
* A folder delete removes the keys it listed. A file added under the folder after the
  listing stays there, even though the request returns 204.
* `DeleteObjects` answers 200 even when it could not delete some keys, so the service
  reads the list of failed keys in the response.

### Example

With the memory backend or a configured test bucket, choose a unique name:

```bash
B=http://127.0.0.1:8000
K="delete-demo-$(date +%s)-$$/old.txt"
printf 'bye' > delete-sample.txt
curl -i -F 'file=@delete-sample.txt' "$B/files/$K"   # 201
curl -i -X DELETE "$B/files?path=$K"                 # 204, empty body
curl -i -X DELETE "$B/files?path=$K"                 # 404 not_found
curl -i "$B/files/metadata?path=$K"                             # 404 not_found

F="delete-demo-$(date +%s)-$$-folder"
curl -s -o /dev/null -F 'file=@delete-sample.txt' "$B/files/$F/a.txt"
curl -s -o /dev/null -F 'file=@delete-sample.txt' "$B/files/$F/sub/b.txt"
curl -i -X DELETE "$B/files?path=$F"                 # 204: both files are gone
curl -i -X DELETE "$B/files?path=$F"                 # 404 not_found
rm delete-sample.txt
```

The second delete of each returns
`{"error":{"code":"not_found","message":"no file or folder at '/<path>'"}}`. The first delete
already removed the samples from the bucket, so only the local file needs cleaning up.
See [Delete in TESTING.md](../TESTING.md#delete) for the recorded tests.

## Move

`PATCH /files?path=` with the JSON body `{"new_path": "..."}`. Owner: **Vikram Markali**.
This is the shared contract's `move(from_path, to_path)`; the HTTP shape is
Dayana20/ospsd26-cloud-storage issue #5.

### Meaning

Move one file to a new path. This changes stored files: afterwards the file is at
`new_path` and nothing is left at `path`. Only files can be moved, not folders.

### Request

* Query parameter `path` (required): the file to move. It follows the shared
  [path rules](#paths).
* JSON body (required, `Content-Type: application/json`): `{"new_path": "<path>"}`,
  where the file should be afterwards. It follows the same path rules.

A missing or invalid `path` or `new_path`, or a body that is not valid JSON, is
rejected before storage is called.

### Success

**200** with the shared file info of the file at its new path, as
[Metadata](#metadata) returns it: `id` (null on S3), `name`, canonical `path`, `size`,
`modified_at`, `etag`, `type` (null), and Team 6's `content_type` extension. The
contents, `size`, `etag`, and `content_type` are the original's. `modified_at` is the
time of the move.

### Side effects

The file is at `new_path` and `path` is empty. Nothing else changes, and nothing is
ever overwritten.

S3 has no move call, so the service makes these provider calls, in order:

1. `stat` on `path` (S3 `HeadObject`). If it finds nothing, a listing of `path/`
   tells a folder from a missing file.
2. `stat` on `new_path`, then a listing of `new_path/`, to make sure neither a file
   nor a folder is there.
3. `copy` (S3 `CopyObject`): the provider copies the file to `new_path` itself, so
   the contents never pass through this service.
4. `delete` on `path` (S3 `DeleteObject`).

If any check in steps 1 and 2 fails, nothing is copied and nothing changes.

### Errors

Responses use the shared [error format](#error-format):

| Status | Error | When |
|---|---|---|
| 400 | `invalid_request` | `path` or `new_path` is missing or breaks a path rule, or the body is not valid JSON. The provider is not contacted. |
| 403 | `permission_denied` | The provider denied the service's credentials or permissions, before anything was copied. |
| 404 | `not_found` | No file exists at `path`. Nothing is copied. |
| 409 | `conflict` | A file, or a folder (files stored under `new_path/`), already exists at `new_path`. Nothing is copied or overwritten. |
| 422 | `invalid_operation` | `new_path` is the same path as `path`, differs from it only in letter case, or `path` is a folder. The provider is not contacted, except to tell a folder apart. |
| 502 | `provider_error` | The provider failed. This includes a **partial move**: the copy succeeded, but deleting the original failed, for any reason (even a 403 or 503 from the provider). The file is then at `new_path`, and may still be at `path`. |
| 503 | `provider_unavailable` | The provider could not be reached during the checks or the copy. |

### Retry

* After a success, repeating the request returns 404, because nothing is at `path`
  any more.
* After a 400, 404, 409, or 422, repeating it unchanged gives the same result.
* After a 502 or 503, the outcome is uncertain: the file may be at `path`, at
  `new_path`, or at both. Check both with Metadata before retrying. If it is at both,
  delete the one at `path`. If it is only at `path`, retry the move.

### Assumptions

* A case-only rename (`/A.pdf` to `/a.pdf`) is refused: some providers treat those
  as one file and S3 treats them as two, so the shared contract forbids it.
* Moving a folder is not supported. On S3 it would mean copying and deleting every
  file under it, which takes many calls and cannot be all-or-nothing.
* `id` is null on S3, because S3 has no identifier that survives a move. Identify
  files by path.
* The checks and the copy are separate calls. If another client creates a file at
  `new_path` between them, the copy replaces it.
* AWS documents a limit of 5 GB per `CopyObject` call, so larger files would need a
  multipart copy, which this service does not do. That limit is from the AWS
  documentation and is **not verified on OCI**.

### Example

With the memory backend or a configured test bucket, in Windows `cmd.exe`:

```bat
set B=http://127.0.0.1:8000
echo hello from the move example> hello.txt
curl.exe -s -F "file=@hello.txt" %B%/files/examples/hello.txt
curl.exe -s -X PATCH "%B%/files?path=examples/hello.txt" -H "Content-Type: application/json" -d "{\"new_path\": \"examples/moved.txt\"}"
curl.exe -s "%B%/files/metadata?path=examples/hello.txt"
curl.exe -s -X DELETE "%B%/files?path=examples/moved.txt"
del hello.txt
```

The move returns 200 with `"path":"/examples/moved.txt"`, the metadata request for
the old path returns 404 `not_found`, and the last line removes the sample from the
bucket. In bash, use `B=http://127.0.0.1:8000`, `$B` instead of `%B%`, `curl` instead
of `curl.exe`, `-d '{"new_path": "examples/moved.txt"}'`, and `rm` instead of `del`.
See [Move in TESTING.md](../TESTING.md#move) for the recorded tests.

## List

`GET /files`. Owner: **Prateek Saxena**.

### Meaning

Returns one page of the files whose keys start with a prefix, sorted by key. Following
`next_cursor` from page to page lists every matching file. It only reads: nothing in the
bucket changes.

### Request

`GET /files`, with no body. Every query parameter is optional.

| Parameter | Default | Constraints | Meaning |
|---|---|---|---|
| `prefix` | `""`, which lists every file | At most 1024 bytes as UTF-8. The [key rules](#keys) do not apply. | Only keys that start with exactly this text are listed. It is plain text, not a folder: `docs` matches `docs/a.txt`, `docs2/b.txt`, and `docsx.txt`. Use `docs/` to list only what is under `docs/`. |
| `limit` | `100` | A whole number from 1 to 1000. | The most files this page may hold. |
| `cursor` | none, which starts at the first page | A `next_cursor` from an earlier response with the same `prefix`, unchanged. | Where to continue. |

Percent-encode `prefix` and `cursor` in the URL. `curl -G --data-urlencode` does this
for you, as in the example below.

### Success

Status **200**, with this JSON object:

| Field | JSON type | Meaning |
|---|---|---|
| `files` | array of [file info](#file-info) | The files on this page, sorted by key. At most `limit` of them, and possibly none. `content_type` is always `null`. |
| `next_cursor` | string or null | `null` when there are no more files. Otherwise, send it back as `cursor`, with the same `prefix`, to get the next page. It is opaque: do not parse, build, or compare cursors. |

What callers can rely on:

* **Order.** Keys are sorted by their UTF-8 bytes. Uppercase comes before lowercase
  (`B.txt` before `a.txt`), `.` before `/` (`a.txt` before `a/x.txt`), and non-ASCII
  after ASCII (`é.txt` after `z.txt`).
* **Depth.** Keys at every depth under the prefix are included. There is no grouping
  into folders: `docs/` lists both `docs/a.txt` and `docs/sub/b.txt`.
* **Completeness.** To read every matching file, keep sending `next_cursor` back until
  it is `null`. Across those pages, every file that exists for the whole traversal
  appears exactly once, and no file outside the prefix appears.
* **Page size.** A page can hold fewer than `limit` files, even none, and still have a
  `next_cursor`. Only a `null` cursor means the end. (S3 allows short pages. On OCI,
  every page before the last was full in our runs.)
* **No matches** is not an error: the response is 200 with
  `{"files": [], "next_cursor": null}`.

### Side effects

None.

### Errors

The body uses the [error format](#error-format).

| Status | `error` | When |
|---|---|---|
| 400 | `invalid_request` | `limit` is not a whole number from 1 to 1000 (for example `0`, `1001`, or `abc`), or `prefix` is longer than 1024 bytes. The provider is not contacted. |
| 400 | `invalid_request` | `cursor` is not a `next_cursor` this API returned for this `prefix`, for example `garbage`, a key name, or a cursor from another `prefix`. The provider is not contacted. |
| 403 | `permission_denied` | The provider denied the service's credentials or permissions. |
| 502 | `provider_error` | The provider refused the request, for example because of a missing bucket. |
| 503 | `provider_unavailable` | The provider could not be reached or timed out. |

### Retry

List only reads, so repeating any request is safe. After a 503, retry later with the
same parameters, including the same `cursor`: on OCI, sending a cursor a second time
returned the same page again. After a 400, retrying the same request gives the same
result until the input changes. A 502 is usually a configuration problem and repeats
until the configuration changes, but it can also be a passing provider-side failure, so
retrying later sometimes succeeds (see [Error types](#error-types)).

### Assumptions

* **No snapshot.** Each page is read from the bucket as it is at that moment. A file
  created or deleted while a caller is paging may or may not appear.
* **Cursors belong to one prefix.** Send a cursor back only with the `prefix` it came
  with. Every backend answers a cursor from another prefix with 400 `invalid_request`.
  On S3 the cursor carries its prefix, because providers do not all check: OCI
  continued from the cursor's position and returned 200 with a wrong (empty) page.
  How long a cursor stays usable depends on the provider and has not been tested.
* **Cursor strings change.** On OCI, two requests for the same page return different
  `next_cursor` strings, and both work. Compare pages by their files, not by cursor.
* **`content_type` is `null`**, because the S3 list call does not return it. Use
  [Metadata](#metadata) for one file's type.
* For an unchanged file, `key`, `size`, and `etag` are the same as in the Metadata and
  Create or Replace responses. OCI reports `last_modified` in whole seconds.
* The 1000 maximum for `limit` is S3's maximum number of keys per list call.

### Example

Pick a prefix nobody else uses, for example `examples/list-demo/`, and check that it is
empty first. Create three files, list them two per page, follow the cursor, then delete
them. On macOS or Linux:

```bash
B=http://127.0.0.1:8000
P=examples/list-demo/
curl -s -G $B/files --data-urlencode "prefix=$P"
printf 'x' > x.txt
for name in c a b; do curl -s -o /dev/null -w '%{http_code}\n' -F "file=@x.txt" "$B/files/$P$name.txt"; done
curl -s -G $B/files --data-urlencode "prefix=$P" --data-urlencode "limit=2"
```

The first listing returns `{"files":[],"next_cursor":null}`, and each create prints
`201`. The two-file page, from OCI (your `etag`, `last_modified`, and cursor will
differ):

```json
{"files":[{"key":"examples/list-demo/a.txt","size":1,"content_type":null,"etag":"9dd4e461268c8034f5c8564e155c67a6","last_modified":"2026-10-14T20:31:34Z"},{"key":"examples/list-demo/b.txt","size":1,"content_type":null,"etag":"9dd4e461268c8034f5c8564e155c67a6","last_modified":"2026-10-14T20:31:34Z"}],"next_cursor":"1:OsT0j2SY..."}
```

Send `next_cursor` back to get the last page:

```bash
curl -s -G $B/files --data-urlencode "prefix=$P" --data-urlencode "limit=2" --data-urlencode "cursor=<next_cursor>"
```

```json
{"files":[{"key":"examples/list-demo/c.txt","size":1,"content_type":null,"etag":"9dd4e461268c8034f5c8564e155c67a6","last_modified":"2026-10-14T20:31:34Z"}],"next_cursor":null}
```

Clean up, then check that the prefix is empty again:

```bash
for name in a b c; do curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$B/files?path=$P$name.txt"; done
curl -s -G $B/files --data-urlencode "prefix=$P"
rm x.txt
```

Each delete prints `204`, and the listing returns `{"files":[],"next_cursor":null}`.
