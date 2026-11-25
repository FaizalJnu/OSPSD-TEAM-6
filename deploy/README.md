# Deploying the storage service

Owner: Debasmith. Tear down after the course ends (Dec 9, 2026); see
[Teardown](#teardown).

## How a deploy works

```text
push to main or dev
  -> GitHub Actions (.github/workflows/deploy-storage.yml)
       test:   uv run pytest (in-memory storage, no credentials)
       build:  Dockerfile -> ghcr.io/faizaljnu/ospsd-team-6/storage:sha-<commit>
       deploy: Portainer API sets IMAGE_TAG_<BRANCH>=sha-<commit> on the stack
               Portainer pulls that image and recreates only that branch's container
       smoke:  deploy/smoke-check.sh <url>  (health, provider, upload, download, delete)
```

| Branch | URL | Container | Stack variable | Bucket variable |
|---|---|---|---|---|
| `main` | https://ds.packapunch.xyz | `team6-storage-api` | `IMAGE_TAG_MAIN` | `S3_BUCKET_MAIN` |
| `dev` | https://ds-dev.packapunch.xyz | `team6-storage-api-dev` | `IMAGE_TAG_DEV` | `S3_BUCKET_DEV` |

Both containers live in one Portainer stack, `ospsd-documentstorage` (stack ID 7 on midpoint). Pull requests
run the tests, build the image without publishing it, and validate the stack file.
They never receive deployment credentials.

The server holds no source code. It runs only images that GitHub built and tested.
Provider keys live in Portainer's stack variables, and the Portainer token lives in
GitHub's repository secrets. Neither is in the repository or the image.

## Which commit is running?

- In Portainer, the stack variable `IMAGE_TAG_MAIN` or `IMAGE_TAG_DEV` is
  `sha-<commit>`.
- On the server: `docker inspect team6-storage-api --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'`
- On GitHub, the Deployments page lists each deploy with its commit and run.

## Run the smoke check by hand

```bash
deploy/smoke-check.sh https://ds-dev.packapunch.xyz
```

It writes one file under `smoke-check/`, reads it back, deletes it, and deletes it
again on exit if a step failed.

## Roll back

Open the last good run of **Deploy storage service** for that branch and re-run its
`deploy` job. It points the branch's container back at that run's image, then runs
the smoke check again. Alternatively, in Portainer, set `IMAGE_TAG_<BRANCH>` to an
older `sha-<commit>` and choose **Update the stack**.

A rollback restores code and configuration. It does not undo files a faulty release
already wrote to, changed in, or deleted from the bucket.

## Add a branch

A deployed branch needs a name that also works as a hostname: lowercase letters,
digits and hyphens. For a branch named `staging`, which serves
https://ds-staging.packapunch.xyz:

1. Add `staging` to `on.push.branches` in `.github/workflows/deploy-storage.yml`.
2. In `deploy/storage-stack.yml`, copy the `storage-dev` block as `storage-staging`,
   with `IMAGE_TAG_STAGING`, `S3_BUCKET_STAGING`, its own container name, router and
   service names, and host `ds-staging.packapunch.xyz`. Paste the new file into the
   Portainer stack and set the two new variables.
3. Add a DNS record for `ds-staging`.

## One-time setup

Done once by hand. Everything after this is automatic.

1. **DNS (Cloudflare):** A records for `ds` and `ds-dev` pointing to the server,
   proxied, with SSL mode Full (strict).
2. **Image visibility:** after the first push builds the image, set the `storage`
   package on GitHub to public, or add `ghcr.io` as a registry in Portainer with a
   read-only token.
3. **Portainer stack** `ospsd-documentstorage`: paste `deploy/storage-stack.yml`
   into Editor and set these variables:

   | Variable | Value |
   |---|---|
   | `IMAGE_TAG_MAIN` | `main`, or `dev` until main has been deployed once |
   | `IMAGE_TAG_DEV` | `dev` |
   | `S3_ENDPOINT`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | OCI customer secret key and endpoint (see the root `README.md`) |
   | `S3_BUCKET_MAIN`, `S3_BUCKET_DEV` | one bucket each; dev's is disposable |

   The stack ID is in the address bar when the stack is open (`.../stacks/<id>?...`),
   and the endpoint ID is the number after `#!/`.
4. **Portainer access token:** My account > Access tokens. It controls every
   container on the server, so keep it only in GitHub's secrets.
5. **GitHub repository secrets** (Settings > Secrets and variables > Actions; only
   the repository owner can add them): `PORTAINER_URL`, `PORTAINER_TOKEN`,
   `PORTAINER_ENDPOINT_ID`, `PORTAINER_STORAGE_STACK_ID`.

## Teardown

1. Delete the Portainer stack `ospsd-documentstorage`.
2. Delete the `ds` and `ds-dev` DNS records.
3. Revoke the Portainer access token and delete the four repository secrets.
4. Delete the `storage` package from GitHub's packages.

Teardown leaves the OCI buckets and their keys, which other teams' conformance runs
and our provider tests also use. Delete them separately when nobody needs them.
