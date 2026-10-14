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
