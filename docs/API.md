# HTTP API

What each operation accepts and returns, and how it fails. The shared sections
(keys, file info, and errors) apply to every operation. Each operation section has
one owner, who keeps it in agreement with the code and the tests.

The running service also serves interactive docs at `/docs` and the schema at
`/openapi.json`. Both are generated from the code. They show the routes, inputs, and
response fields. Metadata also lists its expected error statuses. Other routes may
still advertise 422, although invalid input returns 400 `InvalidInput`; use this page
for their error contracts.

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
* A request that fails with a 4xx status changes nothing: after a failed Create the key
  is still free, and after a failed Replace the old contents are still there.

### Errors

| Status | `error` | When |
|---|---|---|
| 400 | `InvalidInput` | The key breaks a [key rule](#keys), or the `file` form field is missing. |
| 404 | `FileNotFound` | Replace only: no file exists under the key. |
| 409 | `FileAlreadyExists` | Create only: a file already exists under the key. |
| 413 | `FileTooLarge` | The upload is larger than `MAX_UPLOAD_BYTES`. |
| 502 | `ProviderError` | The provider refused the write, usually because of configuration. |
| 503 | `ProviderUnavailable` | The provider could not be reached. |

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
* For uploads larger than 8 MB, the S3 backend uses a multipart upload, and `etag` is
  not an MD5 of the file.

### Example

Use a key under a prefix of your own, such as `demo/<your-name>/`, so cleanup is easy.

```bash
B=http://127.0.0.1:8000
printf 'hello' > hello.txt
curl -s -F "file=@hello.txt" $B/files/demo/me/hello.txt           # 201
curl -s -F "file=@hello.txt" $B/files/demo/me/hello.txt           # 409 FileAlreadyExists
printf 'hello again' > hello2.txt
curl -s -X PUT -F "file=@hello2.txt" $B/files/demo/me/hello.txt   # 200, size 11, new etag
curl -s -X DELETE $B/files/demo/me/hello.txt                      # clean up: 204
```

The Create response looks like this (`etag` and `last_modified` will differ):

```json
{"key": "demo/me/hello.txt", "size": 5, "content_type": "text/plain", "etag": "5d41402abc4b2a76b9719d911017c592", "last_modified": "2026-10-14T18:00:00Z"}
```

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

`GET /metadata/{key}`. Owner: **Darsh Shani**.

### Meaning

Read metadata for one file without downloading its contents.

### Request

The required path `key` is the full, decoded file name, including folder-like
prefixes: `/metadata/docs/report.pdf` refers to `docs/report.pdf`. It follows
the shared [key rules](#keys), including the 1024 UTF-8 byte limit. There is no
request body or operation-specific query parameter. Invalid keys are rejected
before storage is called.

### Success

**200**, with all five [file info fields](#file-info): `key` (the exact full
key), `size` (integer bytes), `content_type` (stored MIME type or `null`),
`etag` (opaque and unquoted), and `last_modified` (UTC ISO 8601 timestamp).
The key can be reused for download, replace, or delete.

### Side effects

None. Reading metadata changes neither the contents nor the stored metadata.

### Errors

Responses use the shared [error format](#error-format):

| Status | Error | When |
|---|---|---|
| 400 | `InvalidInput` | The decoded key breaks a key rule. |
| 404 | `FileNotFound` | No file exists under the key. |
| 502 | `ProviderError` | The provider rejects the request, including configuration or permission problems. |
| 503 | `ProviderUnavailable` | The provider cannot be reached. |

The missing-bucket error mapping is implemented separately in #22.

### Retry

Repeating this read is safe. Correct invalid input or provider configuration
before retrying; a missing file must be created first. Retrying later may help
after a 503. Another caller's write can change the result between reads.

### Assumptions

For an unchanged file, Metadata and List agree on `key`, `size`, and `etag`.
List always returns `content_type: null`; this does not mean the stored MIME
type is missing. Files uploaded externally retain the provider's content type.
Treat ETags as opaque, rather than assuming MD5. HEAD and LIST timestamps may
differ in precision. Separate reads do not establish a snapshot during
concurrent writes.

### Example

With the memory backend or a configured test bucket, choose a unique key:

```bash
B=http://127.0.0.1:8000
K="metadata-demo-$(date +%s)-$$/report.txt"
printf 'hello' > metadata-sample.txt
curl -i -F 'file=@metadata-sample.txt' "$B/files/$K"   # 201
curl -i "$B/metadata/$K"                             # 200
curl -i -X DELETE "$B/files/$K"                     # 204
curl -i "$B/metadata/$K"                             # 404 FileNotFound
rm metadata-sample.txt
```

The 200 body contains `key` equal to `$K`, `size: 5`,
`content_type: "text/plain"`, an unquoted `etag`, and a UTC `last_modified`.
ETag and timestamp values come from the provider. DELETE cleans up the sample;
the final read returns `{"error":"FileNotFound","detail":"no file named '<key>'"}`.
See [Metadata in TESTING.md](../TESTING.md#metadata) for recorded responses.

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
| 400 | `InvalidInput` | `limit` is not a whole number from 1 to 1000 (for example `0`, `1001`, or `abc`), or `prefix` is longer than 1024 bytes. The provider is not contacted. |
| 502 | `ProviderError` | The provider refused the request, for example bad credentials, a denied permission, or a missing bucket. |
| 503 | `ProviderUnavailable` | The provider could not be reached or timed out. |

A cursor this API did not produce should be 400 `InvalidInput`. Today it gives 200 with
an empty page on the in-memory backend, and 502 `ProviderError` on OCI. See
[Known bugs](#known-bugs).

### Retry

List only reads, so repeating any request is safe. After a 503, retry later with the
same parameters, including the same `cursor`: on OCI, sending a cursor a second time
returned the same page again. After a 400 or 502, retrying the same request gives the
same result until the input or the configuration changes.

### Assumptions

* **No snapshot.** Each page is read from the bucket as it is at that moment. A file
  created or deleted while a caller is paging may or may not appear.
* **Cursors belong to one prefix.** Send a cursor back only with the `prefix` it came
  with. What happens with another prefix is not settled yet (BUG-CURSOR). How long a
  cursor stays usable has not been tested.
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
for name in a b c; do curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$B/files/$P$name.txt"; done
curl -s -G $B/files --data-urlencode "prefix=$P"
rm x.txt
```

Each delete prints `204`, and the listing returns `{"files":[],"next_cursor":null}`.
