# OSPSD-TEAM-6

A self-hostable HTTP API for storing and retrieving files. It works with any
S3-compatible storage (OCI Object Storage, Garage, MinIO, AWS S3, Cloudflare R2),
so switching providers only requires changing configuration.

## Team Members

Team 6, OSPSD Fall 2026.

| Name | GitHub | NetID |
| --- | --- | --- |
| Faizal Rahman | [@faizaljnu](https://github.com/faizaljnu) | fr2471 |
| Debasmith Mandal | [@specsnerd007](https://github.com/specsnerd007) | dm6412 |
| Vikram Markali | [@vikram739](https://github.com/vikram739) | vrm9190 |
| Darsh Shani | [@noobui-omen](https://github.com/noobui-omen) | ds8292 |
| Prateek Saxena | [@prateeks99](https://github.com/prateeks99)| ps5838 |

## Requirements

* [uv](https://docs.astral.sh/uv/)
* Python 3.13, pinned in `.python-version`. uv downloads it automatically if
  it is not installed.
* For a real provider: an S3-compatible bucket and an access key pair

Dependencies are locked in `uv.lock`, which is committed. `uv sync` installs
exactly those versions into `.venv`. CI runs `uv sync --locked`, which fails if
`pyproject.toml` and `uv.lock` disagree. To add or upgrade a dependency, use
`uv add <package>` (or `uv add --dev <package>`) and commit both files.

## Quick start (no provider needed)

```bash
git clone git@github.com:FaizalJnu/OSPSD-TEAM-6.git && cd OSPSD-TEAM-6
uv sync
STORAGE_BACKEND=memory uv run uvicorn storage_service.main:create_app --factory --reload
```

Interactive API docs are available at http://127.0.0.1:8000/docs. The `memory`
backend needs no credentials and keeps files in RAM, so they are lost when the
server stops.

## Connect a real provider (OCI Object Storage)

1. Create a private bucket in the OCI Console under
   Storage > Object Storage > Buckets.
2. Note the **namespace** from the bucket's details page, and your
   **region identifier** (for example `us-ashburn-1`).
3. Generate S3 credentials under Profile > your user > **Customer secret keys** >
   Generate secret key. The secret is shown only once, so copy it immediately.
   The access key is listed after the key is created.
4. Make sure that user is allowed to use the bucket. A customer secret key acts
   with the permissions of the user who owns it. Tenancy administrators already
   have access. Any other user needs to be in a group with this policy:

   ```text
   Allow group <group> to read buckets in compartment <compartment> where target.bucket.name = '<bucket>'
   Allow group <group> to manage objects in compartment <compartment> where target.bucket.name = '<bucket>'
   ```

   The service reads, writes, lists, and deletes objects in that one bucket. It
   never creates or deletes buckets.
5. Copy `.env.example` to `.env` and fill in the values:

   ```bash
   cp .env.example .env
   # STORAGE_BACKEND=s3
   # S3_ENDPOINT=https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
   # S3_REGION=<region>
   # S3_BUCKET=<bucket name>
   # S3_ACCESS_KEY=<access key>
   # S3_SECRET_KEY=<secret key>
   ```

6. Start the server with the S3 backend:

   ```bash
   uv run --env-file .env uvicorn storage_service.main:create_app --factory --reload
   ```

Garage, MinIO, and AWS S3 use the same settings with a different endpoint,
region, and keys. See `.env.example` for all available settings, and
[docs/PROVIDERS.md](docs/PROVIDERS.md) for what the team has verified on each
provider.

## Try it

Example requests with curl, run from an empty folder while the server is running.
Expected status codes are in the comments. The first lines create two small sample
files, and the last line removes them along with the downloaded copy.

```bash
B=http://127.0.0.1:8000
printf 'not really a cat' > cat.jpg                         # sample files
printf 'another cat' > other.jpg

curl -F "file=@cat.jpg" $B/files/photos/cat.jpg             # create  -> 201
curl -F "file=@cat.jpg" $B/files/photos/cat.jpg             # again   -> 409
curl $B/metadata/photos/cat.jpg                             # info    -> 200
curl -o back.jpg $B/files/photos/cat.jpg                    # download
cmp cat.jpg back.jpg && echo "identical"
curl "$B/files?prefix=photos/&limit=10"                     # list    -> 200
curl -X PUT -F "file=@other.jpg" $B/files/photos/cat.jpg    # replace -> 200
curl -i -X DELETE $B/files/photos/cat.jpg                   # delete  -> 204
rm cat.jpg other.jpg back.jpg                               # clean up
```

The same steps in Windows `cmd.exe`:

```bat
set B=http://127.0.0.1:8000
echo not really a cat> cat.jpg
echo another cat> other.jpg

curl.exe -F "file=@cat.jpg" %B%/files/photos/cat.jpg            & rem create: 201
curl.exe -F "file=@cat.jpg" %B%/files/photos/cat.jpg            & rem again: 409
curl.exe %B%/metadata/photos/cat.jpg                            & rem info: 200
curl.exe -o back.jpg %B%/files/photos/cat.jpg                   & rem download
fc /b cat.jpg back.jpg                                          & rem "no differences"
curl.exe "%B%/files?prefix=photos/&limit=10"                    & rem list
curl.exe -X PUT -F "file=@other.jpg" %B%/files/photos/cat.jpg   & rem replace: 200
curl.exe -i -X DELETE %B%/files/photos/cat.jpg                  & rem delete: 204
del cat.jpg other.jpg back.jpg                                  & rem clean up
```

Add `-i` to any command to show the status code and response headers.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/files/{key}` | Create a file (form field `file`) |
| `PUT` | `/files/{key}` | Replace an existing file |
| `GET` | `/files/{key}` | Download a file (streamed) |
| `DELETE` | `/files/{key}` | Delete a file |
| `GET` | `/metadata/{key}` | Get file info as JSON |
| `GET` | `/files` | List files: `prefix`, `limit` (1 to 1000), `cursor` |

The key rules, response fields, statuses, and errors are in
[docs/API.md](docs/API.md).

Metadata's complete contract and example are in
[docs/API.md](docs/API.md#metadata); verification is recorded in
[TESTING.md](TESTING.md#metadata).

## Tests

```bash
uv run pytest                                        # fast tests: no network, no credentials
uv run --env-file .env pytest -m provider            # only the tests that use your real bucket
uv run ruff check . && uv run ruff format --check .  # lint and formatting
uv run mypy                                          # type check (strict on src/)
```

CI runs the lint, format, type, and fast test checks on every pull request,
every push to `main`, and every release tag. All of them must pass before a
merge or a release. CI has no provider credentials, so the `provider` tests
never run there. Run them yourself before a release.

[TESTING.md](TESTING.md) explains how the provider tests are selected and cleaned
up, the test layout and fixtures, and what each operation's tests check.

## Clean up

* Stop the server with Ctrl+C. With the `memory` backend, this also deletes
  every stored file.
* Files uploaded to a real bucket stay there until you delete them, either
  with `curl -X DELETE $B/files/<key>` or in the OCI Console. The provider
  tests remove their own files. If a test run is interrupted, delete anything
  left under `contract-tests/` or `api-tests/`.
* If the server stops during a large upload, the bucket can keep an unfinished
  multipart upload. Remove it in the OCI Console under the bucket's
  **Multipart uploads**.
* When you no longer need provider access, delete `.env`, then delete the
  customer secret key in the OCI Console (Profile > your user > Customer secret
  keys). Delete the bucket too if it was only for this project. It must be empty
  first.
* `rm -rf .venv` removes the local environment. `uv sync` recreates it.

## Design notes

* **Layers.** The layers, the provider boundary, and how the backend is wired in
  are explained in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
* **No database.** The provider is the single source of truth. S3 already
  stores each object's size, content type, ETag, and modification time, and a
  separate database would be a second copy that can fall out of sync. We plan
  to revisit this if we add search, sharing, or access history.
* **Streaming.** Downloads are streamed from the provider in 1 MiB chunks.
  FastAPI saves each upload to a temporary file, which is then sent to the
  provider in 8 MB parts (multipart upload for large files). Memory use stays
  flat regardless of file size.
* **Content type.** The server sets the content type from the key's extension
  and ignores the type sent by the client. Downloads are served as attachments
  with `X-Content-Type-Options: nosniff`.

## Known limitations

* Ambiguous S3 HEAD misses require an extra bucket check and bucket-read
  permissions. See [Bucket checks](docs/API.md#bucket-checks) for error behavior
  and concurrency limitations.
* Uploads are written to a temporary file before being sent to the provider.
  The server needs free temp space equal to the upload size, and the size limit
  is only checked after the upload finishes. On Fedora, `/tmp` is stored in RAM,
  so set `TMPDIR=/var/tmp`. In production, a reverse proxy should limit request
  size.
* Create, replace, and delete first check whether the file exists, then act,
  using two separate provider calls. If two clients write to the same key at
  the same time, both can pass the check and the last write wins.
* Listings do not include content types, because the S3 list call does not
  return them.
* Backups and redundancy are handled by the storage provider.

## Contributing

- Open an issue using the [bug report](.github/ISSUE_TEMPLATE/bug_report.md) or [feature request](.github/ISSUE_TEMPLATE/feature_request.md) template.
- Link every pull request to an issue and complete the [PR template](.github/pull_request_template.md) checklist.
- Read [AGENTS.md](AGENTS.md) for the code map, architecture rules, and check commands.
- Read [CONTRIBUTING.md](CONTRIBUTING.md) for how the team works: task ownership,
  review and merge rules, versioning, releases, and fixing a bad release.

## License

MIT. See [LICENSE](LICENSE).
