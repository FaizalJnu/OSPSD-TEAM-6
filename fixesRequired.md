# Fixes required

Bugs found while running the service against OCI Object Storage (bucket in
`us-ashburn-1`, boto3 1.43). All three are confirmed with the observed output
below. Each fix goes in its own PR, starting with a test that fails because of
the bug (see "Bug tasks: shared process" in `instructions.md`).

| ID | Problem | Impact | Owner | Reviewer |
|---|---|---|---|---|
| FIX-1 | OCI rejects every upload | Blocks everyone using OCI | Faizal | Debasmith |
| FIX-2 | A missing bucket is reported as a missing file | Misleading 404s | Darsh (BUG-BUCKET) | Faizal |
| FIX-3 | A malformed list cursor returns 502 on OCI and 200 in memory | Wrong error for a caller mistake | Prateek (BUG-CURSOR) | Vikram |

## FIX-1: OCI rejects every upload

**Until this is fixed:** if you use OCI, add these two lines to your `.env`:

```dotenv
AWS_REQUEST_CHECKSUM_CALCULATION=when_required
AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
```

**Symptom.** Every create or replace returns 502. With a correct OCI `.env`,
`uv run --env-file .env pytest -m provider` gives 5 failed, 2 passed. Every test
that uploads fails; the tests that only read or delete pass.

**Observed.**

```text
botocore.exceptions.ClientError: An error occurred (NotImplemented) when calling the
PutObject operation: AWS chunked encoding not supported.
-> ProviderError: storage provider rejected the request (NotImplemented)   [HTTP 502]
```

**Cause.** Since version 1.36, boto3 sends a checksum with every upload by
default, using the `aws-chunked` transfer encoding. OCI's S3 compatibility API
does not support that encoding.

**Evidence for the cause.** With the two variables above set only on the
command line (`.env` unchanged), the same run gives 7 passed.

**Fix.** In `storage/s3.py`, add `request_checksum_calculation="when_required"`
and `response_checksum_validation="when_required"` to the botocore `Config`. A
value set in `Config` takes precedence over the environment variables, so:

* Remove the two "only if uploads fail" checksum lines from `.env.example`.
* Leave the README's OCI steps listing only the six `S3_*` settings.

**Tradeoff to state in the PR.** On AWS, uploads no longer carry the extra CRC
checksum by default. TLS still protects the transfer. The setting stays inside
`s3.py`, which is where provider quirks belong (grading 8.2).

**Regression test.** The provider tests are the real check. Remove the two lines
from your `.env`, run `uv run --env-file .env pytest -m provider`, and paste the
failing output (5 failed). Apply the fix and paste the passing output (7
passed). Also upload a file larger than 8 MB once, because that goes through the
multipart path (`UploadPart`), which no current test covers.

## FIX-2: A missing bucket is reported as a missing file

**Symptom.** With `S3_BUCKET` set to a bucket that does not exist, some
operations say the *file* is missing instead of reporting a configuration
problem.

**Reproduce.**

```bash
S3_BUCKET=ospsd-no-such-bucket uv run --env-file .env uvicorn storage_service.main:create_app --factory
curl -i http://127.0.0.1:8000/metadata/x.txt
curl -i -X DELETE http://127.0.0.1:8000/files/x.txt
```

**Observed on OCI.**

| Operation | Status | Body | Correct? |
|---|---|---|---|
| `GET /metadata/x.txt` | 404 | `{"error":"FileNotFound","detail":"no file named 'x.txt'"}` | No |
| `DELETE /files/x.txt` | 404 | `{"error":"FileNotFound","detail":"no file named 'x.txt'"}` | No |
| `GET /files/x.txt` | 502 | `{"error":"ProviderError","detail":"storage provider rejected the request (NoSuchBucket)"}` | Yes |
| `GET /files` | 502 | `{"error":"ProviderError","detail":"storage provider rejected the request (NoSuchBucket)"}` | Yes |

`PUT /files/{key}` goes through the same existence check, so it also returns 404.

**Cause.** Metadata, delete, and replace check for the file with
`head_object`. A HEAD response has no body, so for a missing bucket botocore can
only report the error code `"404"`, the same code as for a missing key.
`s3.py` maps `"404"` to `FileNotFound`. Download and list use calls that return
an error body, so they correctly see `NoSuchBucket`.

**Fix (inside `s3.py`; `service.py` must not change).** Pick one and explain
the tradeoff in the PR:

* (a) Check the bucket once at startup with `head_bucket`, through an explicit
  method that `main.build_storage` calls. Startup fails with a clear error.
  Don't put network calls in `S3Storage.__init__`, because the `stubbed_s3`
  fixture builds one. Downside: the service can't start while the provider is
  unreachable, and a bucket deleted while the service runs isn't caught.
* (b) When `head_object` returns 404, call `head_bucket` to tell the two cases
  apart. Downside: one extra provider call on every miss.

**Regression test.** A `stubbed_s3` test that queues a 404 for `head_object`
(plus whatever your chosen fix calls) and expects `ProviderError`. Record the
curl output above before and after the fix.

## FIX-3: A malformed list cursor returns the wrong error

**Symptom.** A cursor that this API did not produce gives different results on
the two backends, and neither is right.

**Observed.**

| Backend | Request | Status | Body |
|---|---|---|---|
| OCI | `GET /files?cursor=garbage` | 502 | `{"error":"ProviderError","detail":"storage provider rejected the request (InvalidArgument)"}` |
| OCI | `GET /files?prefix=docs/&cursor=abc123` | 502 | same as above |
| memory | `GET /files?cursor=garbage` | 200 | `{"files":[],"next_cursor":null}` |

OCI's message is `InvalidArgument: Illegal argument: unable to decode the token`.

**Cause.**
* `s3.py` treats every client error from the provider as a configuration
  problem (502), even when the caller sent the bad value.
* The memory backend uses the last key as its cursor, so it accepts any string.

**Fix.**
* **Contract:** a cursor this API did not produce returns 400 `InvalidInput`.
* **In `s3.list_files`:** map `InvalidArgument` to `InvalidInput`, but only when
  a cursor was passed. Keep the provider's error code inside `s3.py`.
* **Memory backend:** make its cursors recognizable so it can reject unknown
  ones (for example, encode them).
* **Coordination:** if you change the shared `_translate_errors`, talk to Darsh
  first, because FIX-2 touches it too.
* **Docs:** document the cursor rule in the API contract, including what happens
  when a cursor from one prefix is reused with another.

**Regression test.** A contract test in `test_storage_contract.py` (runs on
memory, and on S3 with `-m provider`) that expects `InvalidInput` for a garbage
cursor, plus an HTTP test in `test_list.py` that expects 400.

## Noted for Level 5 (no fix now)

Every expected provider failure above writes a full traceback of about 60 lines
to the server log. The log also includes the provider's raw message, which names
the OCI namespace and bucket. Level 5 (section 5.5) and grading 9.3 ask for
concise, sanitized failure logs. Handle this when we design the Level 5 error
model.
