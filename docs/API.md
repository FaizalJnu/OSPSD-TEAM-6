# HTTP API

What each operation accepts and returns, and how it fails. The shared sections
(keys, file info, and errors) apply to every operation. Each operation section has
one owner, who keeps it in agreement with the code and the tests.

The running service also serves interactive docs at `/docs` and the schema at
`/openapi.json`. Both are generated from the code. They show the routes, inputs, and
response fields, but list only the success status and a 422 for every route. The service
never returns 422 (invalid input is a 400 `InvalidInput`), so use this page for errors.

Examples assume the server runs locally, as in the README:

```bash
B=http://127.0.0.1:8000
```

## Operations

| Operation | Method and path | Owner |
|---|---|---|
| [Create](#create-and-replace) | `POST /files/{key}` | Debasmith Mandal |
| [Replace](#create-and-replace) | `PUT /files/{key}` | Debasmith Mandal |
| [Download](#download) | `GET /files/{key}` | Vikram Markali |
| [Metadata](#metadata) | `GET /metadata/{key}` | Darsh Shani |
| [Delete](#delete) | `DELETE /files/{key}` | Faizal Rahman |
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

An operation given a key that breaks a rule returns 400 `InvalidInput` without
contacting the provider.

In a URL, the key is everything after `/files/` or `/metadata/`, slashes included.
Percent-encode characters that cannot appear in a URL path. For example,
`with spaces.txt` is sent as `/files/with%20spaces.txt`. The rules apply to the
decoded key.

## File info

Create, Replace, and Metadata return one file info object. List returns file info
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

Every error the service reports itself has this JSON body:

```json
{"error": "FileNotFound", "detail": "no file named 'photos/2026/cat.jpg'"}
```

`error` is one of the types in the table below, and is what programs should check.
`detail` is a short explanation for people.

### Error types

| `error` | Status | When it happens | Does retrying help? |
|---|---|---|---|
| `InvalidInput` | 400 | A key breaks a [key rule](#keys), the List `prefix` is longer than 1024 bytes, the List `limit` is not a whole number from 1 to 1000, or Create or Replace is missing the `file` form field. | No. Change the input. |
| `FileNotFound` | 404 | No file exists under the key (Download, Metadata, Replace, Delete). | Not until a file is created under that key. |
| `FileAlreadyExists` | 409 | Create was called for a key that already has a file. | No. Use Replace, or Delete the file first. |
| `FileTooLarge` | 413 | The upload to Create or Replace is larger than `MAX_UPLOAD_BYTES` (default 1 GiB). | No, not with the same file. |
| `ProviderError` | 502 | The provider refused the request: bad credentials, a missing bucket, and so on. Usually a configuration problem. | No. Fix the configuration first. |
| `ProviderUnavailable` | 503 | The provider could not be reached: network failure, timeout, and so on. | Retrying later may help. |

### After a failed write

A 502 or 503 from Create, Replace, or Delete does not prove that nothing changed.
Create and Replace store the file and then read its info back from the provider. If
that read fails, the caller gets the error although the new contents were stored. A
timeout can also hide a write or delete that the provider completed. Before retrying,
check the file with Metadata. Retrying a Create whose file was stored returns 409.

### Responses in another format

Some responses come from FastAPI before our code runs, and do not use the error format
above:

| Status | When | Body |
|---|---|---|
| 404 | The path matches no route, for example `GET /nothing`. | `{"detail": "Not Found"}` |
| 405 | The path exists but not for that method, for example `POST /files`. | `{"detail": "Method Not Allowed"}` |
| 500 | An unexpected failure inside the service. | Plain text: `Internal Server Error` |

A 404 without an `error` field means the path is wrong, not that the file is missing.

Invalid input that FastAPI catches first, such as `limit=abc` or a missing `file` field,
uses our format: 400 `InvalidInput`, with the field name at the start of `detail`.
Moving the three responses above to our format is tracked as a follow-up.

### Known bugs

On OCI, two cases currently return a different response than the table above says:

* A missing bucket is reported as 404 `FileNotFound` by Metadata, Replace, and Delete.
  See [FIX-2](../fixesRequired.md#fix-2-a-missing-bucket-is-reported-as-a-missing-file).
* A malformed list cursor returns 502 `ProviderError`. See
  [FIX-3](../fixesRequired.md#fix-3-a-malformed-list-cursor-returns-the-wrong-error).

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

`POST /files/{key}` and `PUT /files/{key}`. Owner: **Debasmith Mandal**. Not written
yet.

### Meaning

### Request

### Success

### Side effects

### Errors

### Retry

### Assumptions

### Example

## Download

`GET /files/{key}`. Owner: **Vikram Markali**.

### Meaning

Returns the contents of the file stored under a key, as a download. It only reads:
nothing in the bucket changes.

### Request

`GET /files/{key}`, where `{key}` is the file's [key](#keys) (required, slashes
included). There are no query parameters and no body.

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
| 400 | `InvalidInput` | The key breaks a [key rule](#keys). The provider is not contacted. |
| 404 | `FileNotFound` | No file exists under the key. |
| 502 | `ProviderError` | The provider refused the request, for example bad credentials, a denied permission, or a missing bucket. |
| 503 | `ProviderUnavailable` | The provider could not be reached or timed out. |

These statuses are only possible before the body starts. If the provider fails after
the 200 headers are sent, the response is cut off before `Content-Length` bytes arrive,
with no error body. Compare the received size with `Content-Length` to detect this.

### Retry

Download only reads, so repeating it is always safe. After a 503, retrying later may
succeed. After a 400, 404, or 502, retrying the same request gives the same result until
the key, the stored files, or the configuration change. A cut-off body can be retried
from the start.

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

### Example

Pick any key, for example `examples/hello.txt`. Create a file under it first (Download
needs an existing file), download it with its headers, compare the bytes, then delete
it. In Windows `cmd.exe`:

```bat
set B=http://127.0.0.1:8000
echo hello from the download example> hello.txt
curl.exe -s -F "file=@hello.txt" %B%/files/examples/hello.txt
curl.exe -s -D - -o back.txt %B%/files/examples/hello.txt
fc /b hello.txt back.txt
curl.exe -i -X DELETE %B%/files/examples/hello.txt
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
`HTTP/1.1 204 No Content`. To check the cleanup, `curl.exe -i %B%/files/examples/hello.txt`
now returns `404` with `{"error":"FileNotFound",...}`. On macOS or Linux, use
`B=http://127.0.0.1:8000`, `$B` instead of `%B%`, `curl` instead of `curl.exe`,
`cmp hello.txt back.txt` instead of `fc /b`, and `rm` instead of `del`.

## Metadata

`GET /metadata/{key}`. Owner: **Darsh Shani**. Not written yet.

### Meaning

### Request

### Success

### Side effects

### Errors

### Retry

### Assumptions

### Example

## Delete

`DELETE /files/{key}`. Owner: **Faizal Rahman**. Not written yet.

### Meaning

### Request

### Success

### Side effects

### Errors

### Retry

### Assumptions

### Example

## List

`GET /files`. Owner: **Prateek Saxena**. Not written yet.

### Meaning

### Request

### Success

### Side effects

### Errors

### Retry

### Assumptions

### Example
