# HTTP API

What each operation accepts and returns, and how it fails. The shared sections
(keys, file info, and errors) apply to every operation. Each operation section has
one owner, who keeps it in agreement with the code and the tests.

The running service also serves interactive docs at `/docs` and the schema at
`/openapi.json`. Both are generated from the code. They show the routes, inputs, and
response fields, but list only the success status and a 422 for every route, so use
this page for errors.

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
| `InvalidInput` | 400 | A key breaks a [key rule](#keys), or the List `prefix` is longer than 1024 bytes. | No. Change the input. |
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
| 422 | Create or Replace without the `file` form field. List with a `limit` that is not a whole number, or is outside 1 to 1000. | `{"detail": [...]}`, a list of the problems FastAPI found |
| 404 | The path matches no route, for example `GET /nothing`. | `{"detail": "Not Found"}` |
| 405 | The path exists but not for that method, for example `POST /files`. | `{"detail": "Method Not Allowed"}` |
| 500 | An unexpected failure inside the service. | Plain text: `Internal Server Error` |

A 404 without an `error` field means the path is wrong, not that the file is missing.

The 422 responses are a **known inconsistency**: they report invalid input, which this
API otherwise reports as 400 `InvalidInput`. A planned change (ERR-400) will return
400 `InvalidInput` for them instead. Until then, a missing `file` field returns:

```json
{"detail": [{"type": "missing", "loc": ["body", "file"], "msg": "Field required", "input": null}]}
```

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

`GET /files/{key}`. Owner: **Vikram Markali**. Not written yet.

### Meaning

### Request

### Success

### Side effects

### Errors

### Retry

### Assumptions

### Example

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
