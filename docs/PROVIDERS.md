# Storage providers

The service reaches every provider through the S3 API, in
`src/storage_service/storage/s3.py`. Switching providers only changes the `S3_*`
settings in `.env` (see `.env.example`). This page records, for each provider, how to
fill in those settings and what happened when someone ran the provider tests against
it.

Only record what you ran yourself. An empty field means nobody on the team has
verified it yet.

## Adding a provider

1. Create a private bucket used only for this project.
2. Create keys that can only read, write, list, and delete objects in that bucket.
3. Run `cp .env.example .env`, then set `STORAGE_BACKEND=s3` and the `S3_*` settings.
   Never commit `.env`, and never paste keys into issues, pull requests, or chat.
4. Run `uv run --env-file .env pytest -m provider`. Every test should pass.
5. Fill in the provider's section below. For the contract-test result, give your name,
   the date, the commit (`git rev-parse --short HEAD`), and pytest's summary line, for
   example `7 passed`.
6. If a test fails, open a bug issue with the output (keys and account names removed),
   and link it under Quirks.

## OCI Object Storage

The provider the README documents.

* **Setup:** follow
  [Connect a real provider (OCI Object Storage)](../README.md#connect-a-real-provider-oci-object-storage)
  in the README. It covers the endpoint, region, keys, and bucket policy.
* **Known bugs:** see [fixesRequired.md](../fixesRequired.md).

## AWS S3

| Field | Value |
|---|---|
| Endpoint format (`S3_ENDPOINT`) | `https://s3.<region>.amazonaws.com` |
| Region value (`S3_REGION`) | The bucket's region, for example `us-east-1` |
| How to get keys | An IAM user with an access key, limited by policy to the one bucket: `s3:ListBucket` on the bucket, and `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on its objects. Without `s3:ListBucket`, AWS answers a request for a missing key with 403, so the service reports `AccessDenied` instead of `FileNotFound`. |
| Contract-test result | Tested: `uv run --env-file .env pytest -m provider` passed against an AWS S3 test bucket. |
| Quirks | None recorded. |

## Google Cloud Storage

| Field | Value |
|---|---|
| Endpoint format (`S3_ENDPOINT`) | `https://storage.googleapis.com` |
| Region value (`S3_REGION`) | `auto` |
| How to get keys | An HMAC key for a service account (Cloud Storage > Settings > Interoperability). The service account needs to read, write, list, and delete objects in the one bucket, and to read the bucket itself, which the service checks after a missing file. |
| Contract-test result | Tested: `uv run --env-file .env pytest -m provider` passed against a Google Cloud Storage test bucket. |
| Quirks | None recorded. |
