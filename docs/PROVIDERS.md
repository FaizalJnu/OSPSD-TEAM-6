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
* **Until FIX-1 is merged:** OCI rejects every upload. In your `.env`, uncomment the
  two `AWS_*_CHECKSUM_*` lines at the end of `.env.example`. See
  [FIX-1](../fixesRequired.md#fix-1-oci-rejects-every-upload). Remove this note once
  FIX-1 is merged.
* **Known bugs:** see [fixesRequired.md](../fixesRequired.md).

## AWS S3

| Field | Value |
|---|---|
| Endpoint format (`S3_ENDPOINT`) | |
| Region value (`S3_REGION`) | |
| How to get keys | |
| Contract-test result | |
| Quirks | |

## Google Cloud Storage

| Field | Value |
|---|---|
| Endpoint format (`S3_ENDPOINT`) | |
| Region value (`S3_REGION`) | |
| How to get keys | |
| Contract-test result | |
| Quirks | |

## Cloudflare R2

| Field | Value |
|---|---|
| Endpoint format (`S3_ENDPOINT`) | |
| Region value (`S3_REGION`) | |
| How to get keys | |
| Contract-test result | |
| Quirks | |

## Local MinIO or Garage

Useful for development without a cloud account. A run against a local server does not
count as real-provider verification for an operation.

| Field | Value |
|---|---|
| Endpoint format (`S3_ENDPOINT`) | |
| Region value (`S3_REGION`) | |
| How to get keys | |
| Contract-test result | |
| Quirks | |
