DOCUMENT STORAGE  |  TEAMS 1, 3 AND 6

DESIGN: Document Storage vertical
adopts one shared API

| **Item** | **Details** |
| --- | --- |
| Authors | Consolidated by Faizal Rahman from the three teams’ design inputs (November 4 and 11, 2026). Team 6 implementation status and Section 10 (infrastructure) by Debasmith Mandal, November 12, 2026. |
| Teams | Team 1: Dropbox. Team 3: Dropbox. Team 6: S3-compatible storage, verified on OCI, AWS S3 and Google Cloud Storage. |
| Coordinator / contacts | Dayana / Yashwanth (Team 1), Jing Qian (Team 3), Debasmith Mandal (Team 6). |
| Contract baseline | cloud-storage-api 0.3.1 (tag commit 664afc9, published November 11), pinned by Team 6 through #92. 0.3.x adds the agreed streaming methods as new, non-abstract methods; 0.2.0 (commit 8309ac4) is unchanged and remains Team 1’s pin. The package’s own version field still reads 0.2.0 at tags 0.3.0 and 0.3.1; a corrected follow-up release has been requested. |
| Status | In review (November 12 revision). Implementation evidence and unresolved contract decisions are recorded separately below; Section 10 is Planned except where marked Observed. |
| Reviewers | Whole design: review requested from Faizal Rahman on November 12, 2026; pending, with comments to be answered on the pull request. Contract-facing parts: Team 1 and Team 3 implementation contacts. |
| References | October 28 decision memo; shared repository and issues (https://github.com/Dayana20/ospsd26-cloud-storage); Team 6 implementation pull requests listed in Section 6; each team’s design and implementation records. |

Labels: Published = defined in a tagged package; Agreed = an explicitly recorded decision with the relevant scope; Proposed/Open = requires a decision. Silence does not establish cross-team agreement. Evidence is Observed, Reported, Planned or Assumed. Historical evidence retains its original date.

# 1. Context, goals and non-goals

The three FastAPI services expose different upload, path, metadata, list and error conventions. The shared contract lets consumers use the same HTTP workflow while each service keeps its provider implementation.

## Goals

One workflow: create → metadata → download and compare bytes → list → move → metadata → delete → confirm 404.

One error envelope and stable codes; shared metadata fields and canonical paths.

Conformance against each service and real provider before release; documented migration for changed routes and fields.

## Non-goals

No cross-provider data migration, per-request bucket selection, provider switching during a request, or common credential provisioning. Redis/idempotency, extra Dropbox operations, content_type and higher upload limits remain documented service extensions.

Historical baseline (November 4): Team 6 used key-in-URL routes, flat errors and paged recursive listing; Teams 1 and 3 differed on replace, folders, validation and timestamps. Those comparisons are historical, not a claim about current deployments.

# 2. Architecture and request flow

Dependency direction remains HTTP → service rules → provider-independent interface → adapter. Provider SDKs stay inside adapters; application wiring selects the backend.

Target architecture. Current adoption varies by team; shared streaming integration remains planned.

| **Boundary** | **Teams 1 / 3** | **Team 6** |
| --- | --- | --- |
| HTTP and rules | app/api/routes and validation / cloud_storage_service | routers/ and service.py |
| Current local interface | DocumentStorage / cloud_storage_client_api.Client | storage/base.py: StorageClient |
| Provider adapter | DropboxStorage / DropboxClient | storage/s3.py: S3Storage; boto3 only here |
| Test doubles | Fake storage / FakeStorageClient | InMemoryStorage and FakeStorage |

## Shared interface and streaming

Published 0.2.0: DocumentStorage, FileInfo and typed storage errors; Python ≥3.12, no provider SDK dependency. Team 6 adopted the shared errors and FileInfo in #81 (merged).

Published 0.3.0 and 0.3.1 (November 11): the agreed streaming extension. Team 6 adopted 0.3.1 in #92 (merged) through storage_service/shared_storage.py, an adapter that implements the full tagged DocumentStorage interface over Team 6’s S3 storage.

Agreed additive extension: stream-based Create/Replace and open_download(path) are NEW, non-abstract methods. Existing bytes methods and signatures remain unchanged; 0.2.0 is untouched.

Callers own upload streams. Adapters read from the current position and never close them. Team 6 overrides the new methods with real streaming.

open_download returns a closeable object usable in a with block. Initial lookup/open errors occur when called, before returning the object. Later read failures may still occur during iteration.

Published in 0.3.x: the download object exposes the file’s shared FileInfo with its chunks, and close is idempotent; content_type stays a Team 6 extension. Team 6 sends downloads to the caller in 64 KiB chunks, so memory use does not grow with file size. The legacy bytes download is the only path that assembles a whole file and is capped at 150 MiB. Upload-limit enforcement stays in the service (Darsh’s proposal in the November 11 thread).

## Client lifecycle and traces

Team 1 caches a lazily created Dropbox client. Team 3 builds one in application lifespan. Team 6 builds one storage client at startup; missing S3 settings prevent startup. File state lives in the provider; Team 1’s optional Redis state is an extension.

Team 6 metadata: normalize path → derive key → HeadObject → convert to shared FileInfo. An ambiguous HEAD 404 triggers HeadBucket before classifying a miss. Missing bucket: 502; explicit denial: 403; unreachable provider: 503. Folder-metadata semantics remain open (Section 8).

Team 6 download (success): GET /files/download?path=/docs/a.pdf → path normalized and validated → open_download(path) on the shared adapter → S3 GetObject, opened eagerly → headers set from the download’s FileInfo (Content-Length, Content-Disposition, ETag) → 200 streamed in 64 KiB chunks → stream closed on completion, error, cancellation or client disconnect.

Team 6 download (expected failure): the same request for a missing path → GetObject reports a missing key → open_download raises the shared not-found error before any header is sent → the app-level handler returns 404 {"error":{"code":"not_found",...}} and writes one request_failed log line. A provider failure after the 200 headers instead cuts the body short and is logged; no JSON is appended.

# 3. API and data model

## Shared HTTP target

Routes below describe the target contract. Adoption and remaining proposed rules are tracked separately; they are not a claim that every service or deployed revision already implements them.

| **Operation** | **Route / input** | **Success and key behavior** |
| --- | --- | --- |
| API health | GET /health | 200 {"status":"ok"}; no provider call. Not yet served by Team 6 (Section 6). |
| Provider health | GET /health/provider | One lightweight provider check; provider-health failure policy must be consistent with configuration/startup behavior. |
| Create | POST /files; multipart file, path | 201 shared file info; occupied destination → 409, no overwrite. Team 6 still serves POST /files/{key} (Section 6). |
| Replace | PUT /files; multipart file, path | 200 shared file info; missing target → 404. Concurrency limitations are documented. |
| Download | GET /files/download?path= | 200 exact bytes; streamed; attachment disposition. Route tracked in shared #8. |
| Metadata | GET /files/metadata?path= | 200 shared file info. Route tracked in shared #8; folder semantics remain open. |
| List | GET /files?path=<folder> | 200 array of direct children, sorted by path; service fetches all provider pages. Route tracked in shared #10. |
| Move | PATCH /files?path=<from>; JSON {"new_path":"<to>"} | 200 info at destination; file-only; no overwrite. Shared #5 records confirmations/restrictions. |
| Delete | DELETE /files?path= | 204, empty body; recursive for folders; absent path → 404. Root rejection status remains open. |

## Paths

Accept with or without leading /. Return the canonical leading-slash form; Team 6 removes that slash to obtain the stored S3 key. Existing objects do not move.

Empty paths and . or .. segments return 400 invalid_request. Team 6 also rejects empty segments, trailing slashes and ASCII control characters.

Team 6’s canonical-path limit is 1024 UTF-8 bytes including the leading slash. Cross-provider path limits/normalization need explicit confirmation.

List accepts root /. Root behavior for other operations, including metadata, must be explicit. Proposed root Delete: 422 invalid_operation with no writes; Team 6 currently rejects it with 400.

Dropbox is case-insensitive; S3 is case-sensitive. File-only Move proposes 422 for same canonical path, case-only rename and folder sources; occupied destinations remain 409.

## Upload size

Portable baseline: 150 MiB (157,286,400 bytes). Team 6’s configured 1 GiB limit is a documented extension; consumers relying on larger uploads are not portable. The document does not impose a new global 150 MiB maximum. Oversized uploads use 413 file_too_large; current adoption must be recorded per service.

Team 6 spools uploads and checks size before storage writes. Proposed streaming enforcement stays in the service; unknown-length inputs need counting/spooling before provider writes if rejection must leave storage unchanged. A counting wrapper during an active upload alone cannot provide that guarantee.

## Shared FileInfo (0.2.0)

Create, Replace, Metadata and Move return the shared fields; List also identifies entry kind. Preserve the distinction between a nullable field and an optional extension.

| **Field** | **Type** | **Meaning** |
| --- | --- | --- |
| id | string │ null | Opaque provider ID; S3 returns null. IDs are not portable across providers. |
| name | string | Last path segment. |
| path | string | Canonical absolute path. |
| size | integer │ null | Bytes; null for folders. |
| modified_at | string │ null | ISO 8601 UTC ending in Z; null for folders. Parse timestamps rather than comparing formatting. |
| etag | string │ null | Shared opaque fingerprint. Do not assume MD5 or infer atomicity/concurrency guarantees from its presence. |
| type | string │ null | "file" / "folder" on List entries; null outside listing. |
| content_type | Team 6 extension | Retained metadata/download information; not required by the shared interface. |

## Illustrative metadata response

```http
GET /files/metadata?path=photos/2026/cat.jpg
200 OK
{
  "id": null,
  "name": "cat.jpg",
  "path": "/photos/2026/cat.jpg",
  "size": 17,
  "modified_at": "2026-10-14T00:20:31.589428Z",
  "etag": "08a83d6686281a5a292732435b21f83a",
  "type": null,
  "content_type": "image/jpeg"
}
```

The example illustrates the shape. Separate live OCI evidence for #81 is recorded in Section 7. Legacy Team 6 key and last_modified fields map to path and modified_at; the legacy /metadata/{key} route is removed by #81.

## Provider differences and open kind rules

S3 has keys rather than persistent folders. A virtual folder disappears with its last object; Dropbox can retain empty folders. Shared tests currently exclude empty folders.

S3 can hold a file and keys beneath the same prefix. Current Team 6 Delete removes only the exact file when both coexist. A cross-provider policy remains open.

Folder metadata must be resolved consistently: the shared FileInfo can describe folders, while the earlier design proposed file-only metadata. #81 does not implement a folder probe or a 422 folder-metadata rule.

Proposed extension rule: consumers ignore documented unknown fields. Confirm the rule rather than assuming package adoption alone settles it.

ETag can distinguish changes when timestamp precision does not. It is now a shared field, not a Team 6-only extension.

# 4. Alternatives and tradeoffs

| **Decision** | **Chosen / current approach** | **Alternative and consequence** |
| --- | --- | --- |
| Replace on Dropbox | Read metadata/revision, then WriteMode.update(rev). Current Team 3 dev includes revision-checked replace; Team 1 recorded a live Replace path. | Single-call overwrite can create missing files and overwrite changes. A file deleted between the two calls may still be recreated; evidence and contract treatment remain explicit. |
| Replace on S3 | Existence check, upload, then metadata readback. Current Team 6 can overwrite a concurrent change. | Conditional writes with ETag/If-Match need provider and multipart verification. Presence of shared etag does not prove this guarantee. |
| Path in query | Use shared ?path= routes and upload form path. Document removal of old routes. | Compatibility aliases add overlap and cannot preserve old error-envelope consumers. Team 6 #84 removed keyed Download; #81 removes legacy Metadata. |
| Path normalization | Add missing leading slash; preserve the canonical path in responses. | Rejecting relative spelling prevents portability. Empty-segment/trailing-slash handling still needs consistent agreement. |
| Error envelope | App-level handlers cover validation, unknown routes, methods and unexpected failures. | Route-only handling leaves framework errors inconsistent. Team 3 may retain SharedErrorRoute plus app-level handlers. |
| Move on S3 | Copy then delete; file-only, no overwrite. Report unconfirmed source deletion after a later failure. | Omitting Move breaks the common workflow. Folder Move remains an extension; composite operations are not atomic. |
| List | Target: direct children, sorted, with all provider pages fetched by the service. | Response size/provider calls grow with folder size. Optional consumer cursors require a separate agreed extension. |
| Streaming | Add non-abstract methods; preserve bytes signatures and existing adapters. | Changing bytes signatures or making stream methods abstract is breaking and requires sign-off. Compatibility defaults do not prove Team 6’s streaming implementation. |

## Guarantee boundaries

Replace’s missing-target behavior and stale-write behavior are separate guarantees. State which concurrent-delete/change windows are verified.

No-overwrite checks followed by unconditional writes do not prove race-free conflict handling.

An interface update does not demonstrate adapter adoption, conformance or live-provider correctness. Record each separately.

# 5. Failure behavior and operations

Every application-generated JSON error uses the same envelope. Consumers use status and code; messages are safe explanations, not stable identifiers or raw provider text.

```json
{"error":{"code":"not_found","message":"No entry exists at the requested path"}}
```

| **HTTP** | **Code** | **Meaning** |
| --- | --- | --- |
| 400 | invalid_request | Malformed input, invalid path or missing required fields. |
| 403 | permission_denied | Provider explicitly refuses credentials or access. |
| 404 | not_found | Entry absent in accessible, functioning storage. |
| 409 | conflict | Occupied destination or refused stale write. |
| 413 | file_too_large | Upload exceeds the service’s documented limit. |
| 422 | invalid_operation | An agreed semantic restriction; exact wrong-kind/root cases remain open. |
| 502 | provider_error | Other provider failure, missing configured storage or confirmed partial composite operation. |
| 503 | provider_unavailable | Provider connection failure or timeout. |
| 404 | route_not_found | Unknown application route; separate from an absent stored entry. |
| 405 | method_not_allowed | Unsupported method; accurate Allow lists accepted methods. |
| 500 | internal_error | Unexpected service failure; fixed safe message. |

The eight storage-error classes are published in 0.2.0. Framework-code policy and operation-specific restrictions require the recorded cross-team decisions. Service extensions retain 503 provider_not_configured and service_busy for pre-provider rejection. Team 6 implements the nested envelope and framework mappings in #81; merge/deployment status is separate.

## Uncertain writes and partial operations

Missing configured storage is not entry-level 404. Explicit denial stays 403; other missing-storage/configuration failures are 502.

A write returning 502/503 may already have changed storage. Check affected state before retrying; for Move inspect both source and destination.

Confirmed copy followed by failed/timed-out deletion: 502; source deletion is unconfirmed, not guaranteed absent or present.

Folder Delete: listing failure causes no writes. The first batch failing as a whole retains its failure classification, with uncertain outcome. Later-batch failure or reported failed keys returns 502 because deletion is partial/unconfirmed.

Retain throttling/transient provider-5xx at 502 initially unless the affected owners agree otherwise.

No application-level blind write retries. SDK retries are separate: Team 6 uses standard mode, max_attempts=3 (up to four total attempts per SDK call).

After download headers are sent, later failures interrupt the body and produce truthful logs; never append JSON or claim a replacement error status was sent.

## Logging, configuration and exposure

| **Area** | **Team 1** | **Team 3** | **Team 6** |
| --- | --- | --- | --- |
| Failure logging | Dropbox diagnostic + request_failed, with request ID. | Structured operation/status/code/provider-failure reason. | JSON request_failed; flat error/detail contain shared code/safe message. Also storage_call, provider_code and write_outcome. |
| Sensitive data | No tokens, file contents or raw provider messages; access log disabled. | No file contents/rejected request values. Audit provider detail and path handling. | No credentials, raw provider messages or expected-error tracebacks. Paths can occur in safe messages. |
| Configuration | Dropbox app key/secret/refresh token; optional access token and Redis. | Dropbox credentials; concurrency setting. | STORAGE_BACKEND; S3_ENDPOINT, S3_REGION, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY; MAX_UPLOAD_BYTES. |
| Missing credentials | Lazy configuration; provider_not_configured when applicable. | Startup fails. | Startup fails with ConfigError. |

Credentials come from protected environment settings/secrets, never source control, images, example responses or logs. No common caller-authentication scheme is defined; provider credentials do not authenticate API consumers.

## Provider-call costs

| **Operation** | **Team 6 call pattern** |
| --- | --- |
| Create / Replace | Existence check + upload + metadata readback. An ambiguous miss adds HeadBucket. Multipart upload adds initiation, parts and completion calls. |
| Metadata / Download | HeadObject / GetObject; an ambiguous metadata miss adds HeadBucket. Download reads lazily. |
| Delete file / folder | HeadObject + DeleteObject for a file. Folder: confirm absence of file, list all pages, then DeleteObjects batches of up to 1000 keys. |
| Move / List / Health target | Copy/delete plus checks; direct-child List uses delimiter and provider pagination; provider health uses one lightweight check. Adoption remains owner-tracked. |

## Deployment and observability

Team 6: Debasmith reported a live Docker deployment at https://ds.packapunch.xyz on November 10, with OCI operation/error tests and a 200 MB upload. Observed November 11: after redeploying dev at dd19ff9, the container log shows cloud-storage-api 0.3.1 (664afc9) installed, and the deployed OpenAPI schema lists /files, /files/{key}, /files/metadata and /files/download, with the legacy /metadata/{key} route gone. That revision therefore includes #81, #84 and #92. The deployment is still manual; Section 10 replaces it.

Traefik normalizes // and .. in URL paths before the application; the hosted key-rule cases can return 404 rather than the local application’s 400. Record edge and local results separately.

Observability is Planned, with Debasmith as owner: Section 10 records the design. Treat it as planned until the dashboard, logs and traces are verified.

Team 3’s Cloud Run/OpenTofu/Secret Manager/CircleCI/Grafana plan remains its proposed deployment design unless its owners provide completion evidence. Team 1 confirms its current deployment separately.

Use API liveness independently of provider readiness; a provider outage should not cause liveness restart loops. Confirm provider-health behavior for startup-failure configurations.

# 6. Migration and coordination

Pin shared packages to immutable tags and record the resolved commit in the lockfile. Shared 0.2.0 requires Python ≥3.12; Team 6 uses ≥3.13. Teams 1 and 3 verify their own Python/CI migration.

| **Area** | **Team 6 status / migration** | **Consumer impact** |
| --- | --- | --- |
| Paths | #79 merged: leading-slash normalization and path-to-key mapping. | Stored keys unchanged; no object migration. |
| Download | #84 merged: GET /files/download?path= replaces keyed GET. | Callers update URL and path parameter. |
| Folder Delete | #83 merged: recursive deletion; exact file wins if file/prefix coexist. | A former prefix miss can now delete a subtree; document in release notes. |
| Errors / Metadata | #81 merged: nested errors and GET /files/metadata?path= with shared FileInfo. | Breaking error envelope and metadata route/fields; legacy Metadata removed. |
| List | #87 merged: one folder level with every provider page fetched (storage layer). #90 merged: GET /files?path= in the shared format. #74 merged: a cursor sent with another prefix returns 400. | Callers move from ?prefix= paging to the direct-child list. |
| Create / Replace | Not migrated. routers/upload.py still serves POST /files/{key} and PUT /files/{key}, and docs/API.md documents them. Owner Debasmith; issue to be opened. | Every shared conformance test that creates a file depends on this change. |
| Move | #88 merged: PATCH /files?path= as copy then delete. Live OCI run recorded in TESTING.md (Vikram, November 11). | New operation; preserves safe error and uncertain-write rules. |
| Health | Not served over HTTP. check_health exists in service.py and in the shared adapter; GET /health and GET /health/provider are not routed. Owner to be named. | Required by the shared contract, the conformance suite and the Level 1 health endpoint. |
| Streaming adoption | #92 merged: pins 0.3.1 and implements the full tagged interface with real streaming overrides (shared_storage.py). Evidence in Section 7. | Existing bytes consumers remain compatible. |
| Limits / release | 1 GiB Team 6 extension retained. Inspected project version is 0.1.0; do not claim a future service release exists. | Service release versions and shared-package tags are distinct. |

## Owned work

| **Work** | **Owner / dependency** |
| --- | --- |
| Error envelope, framework handlers, Metadata/FileInfo | Darsh; #81 merged; live metadata verification recorded. |
| Shared streaming adoption | Darsh; #92 merged. |
| Download / Move | Vikram; #84 and #88 merged; live Move run recorded. |
| Create / Replace and adapter coordination | Debasmith with shared-package owner; resolve stream API and complete required adapter methods. |
| Path mapping / folder Delete | Faizal; #79 / #83 merged. |
| Direct-child List / conformance | Prateek; #87, #90 and #74 merged; shared conformance suite in shared PR #6 (open). |
| Infrastructure (Milestone 3 Levels 1 to 4) | Debasmith; design in Section 10; coordinate shared metric names with Dayana (shared #2). |
| Health routes | Owner to be named. |

## Contract change process

Record the defect/proposal in a shared issue and announce it in the Document Storage Slack channel. Breaking changes require all three implementation contacts’ sign-off and a new coordinator tag. Additive changes still document ownership, semantics and verification. Teams adopt by changing their pins; do not rewrite published tags.

# 7. Testing and evidence

| **Layer** | **Purpose / execution** |
| --- | --- |
| Fast application tests | HTTP/rules over memory and controlled fakes. No credentials or network. |
| Provider translation | Mocked Dropbox / botocore Stubber. Verify error classification, partial writes, pagination and resource cleanup without network. |
| Live provider | Real operations in unique scratch folders/prefixes; cleanup limited to that run’s data. |
| HTTP conformance | Same tests against reference app or service URL. Shared PR #6 remains open; record exact revision, selected markers, failures and cleanup. |

## Verified Team 6 evidence

Shared streaming adoption (#92), November 11: 314 fast tests passed with 25 provider tests deselected; Ruff and mypy passed. Live OCI selection: 2 passed, 34 deselected; the tagged-interface round trip uses a 9 MiB multipart upload and an incremental download hash, then Replace, Metadata, direct-child List, Move, Health and Delete. Both fixtures cleaned up and independent listings confirmed the scratch prefixes empty. Details in TESTING.md.

Move (#88), November 11: live OCI Move test 1 passed (Vikram); size, etag and content type unchanged after the move.

PR #81 head c0c1dcf, based on dev 3d32071: 263 fast tests passed; 20 provider tests deselected. Ruff lint/format and mypy passed. All 37 generated OpenAPI error descriptions use shared codes. Three shared-exception partial-delete regression cases failed before correction and pass afterward.

Live OCI metadata test: 1 passed. It checks shared fields, canonical path, null S3 ID, UTC timestamp, ETag, content type, downloaded bytes and consistency with listing. Fixture cleanup completed; an independent listing confirmed the scratch prefix was empty. This is metadata-path evidence, not a full conformance/deployment result.

## Conformance status

At shared PR #6 revision a8bd832 (still open), the reference app serves cloud_storage_api.DocumentStorage and includes the 0.3.1 streaming changes. Error codes, FileInfo fields (including etag/type) and UTC timestamps follow 0.2.0. The List tests are no longer marked proposed, following shared #10. Proposed markers remain for Download/Metadata routes (#8), Move (#5), and route/method error distinctions (#4). The author reports 55 of 55 tests passing against the reference app, in process and over HTTP.

Team 6 real-service result: not yet run. Expected, not observed: most tests fail against Team 6 today, because ten of the eleven test files create a file with POST /files or call the health routes, and Team 6 serves neither yet. Debasmith, as implementation contact, records the actual result on shared PR #6 and in TESTING.md, then again after Create/Replace and Health migrate.

```bash
# Reference app
uv run pytest conformance/tests --no-cov
# Service under test
CONFORMANCE_BASE_URL=<test-service> uv run pytest conformance/tests --no-cov
# Only rules without proposed markers
uv run pytest conformance/tests --no-cov -m "not proposed"
```

The suite author reported 54 reference-app tests passing on November 4 and 55 at the current revision. Treat both as dated evidence, not a fresh run. Each implementation contact records its current real-service result; avoid an undated claim that no team has run it.

## Remaining acceptance checks

Streams: bounded reads, caller-owned input stays open, lazy download, eager initial errors, idempotent close and cleanup on exhaustion/failure/disconnect.

Operations: no overwrite, missing Replace target, kind/root restrictions after agreement, direct-child List across all provider pages, partial Move/Delete, and accurate 405 Allow.

Keep controlled provider-failure tests locally: shared live HTTP tests cannot reliably induce 403/502/503 or late failures. Empty folders, case behavior, upload boundaries and large pagination need explicit coverage/limitations.

Release gates: green CI on the exact submitted head, human review, and the repository’s squash-merge process. Record review/CI status separately from local test results.

# 8. Open questions and decision register

Retain the source document’s question IDs so existing references remain meaningful. Close an item only with a decision link and the affected owners’ confirmation; package publication alone does not settle every HTTP rule.

| **ID** | **Question / remaining decision** | **Owner / next step** |
| --- | --- | --- |
| 1 | Cross-provider path limit, trailing slash, empty segments and control characters. | Path owners and implementation contacts; align contract and tests. |
| 3 | Occupied/stale-write conflict meaning: 409 is defined in 0.2.0; exact operation enforcement and races need evidence. | Operation owners; record behavior and limitations. |
| 4 | Base errors published in 0.2.0; finish framework-code policy, missing storage and provider classifications. | Darsh with implementation contacts; update shared #4. |
| 6 | List response and any optional consumer paging extension. | Prateek, Jing, Yashwanth; shared #10. |
| 7 | Partial folder Delete semantics and provider limits. | Delete owners; retain confirmed-partial 502 and truthful uncertainty. |
| 10 | 150 MiB portable baseline / Team 6 1 GiB extension; size-error adoption and stream enforcement. | Upload owners and Dayana; confirm service-layer enforcement and oversized-write guarantees. |
| 11 | Resolved: 0.3.0 and 0.3.1 published November 11; Team 6 adopted 0.3.1 in #92. Remaining: correct the package version field in a follow-up release. | Dayana. |
| 13 | Root behavior: proposed Delete 422 with no writes; Team 6 currently returns 400. Clarify Metadata/root separately. | Darsh and path/Delete/Metadata owners. |
| 14 | Wrong-kind operations and folder Metadata: shared model supports folders; earlier file-only trace conflicts. | Operation owners; resolve scope and statuses before implementing the proposed 422 cases. |
| 15 | Conditional S3 Replace and concurrent-deletion behavior on Dropbox. | Debasmith / Replace owners; controlled and live-provider evidence. |
| 16 | S3 file/prefix coexistence and file parents; current Delete is file-first. | Implementation contacts and operation owners; explicit cross-provider policy. |
| 17 | Consumers ignoring unknown extension fields. | Coordinator and consumers; record extensibility rule. |
| S1 | Download object: chunks/close/context manager agreed; shared FileInfo requested; content_type remains an extension. | Dayana and Debasmith/Darsh; confirm metadata and eager-open/late-failure semantics. |
| S2 | Resolved for Team 6: shared_storage.py implements the existing abstract bytes methods and overrides the stream methods; tests in tests/test_shared_storage.py. | Closed by #92; Teams 1 and 3 track their own adoption. |
| I1 | Which branch deploys the demo environment: dev or release tags on main. | Debasmith and Faizal; decide before Level 2. |
| I2 | How graders open the Grafana dashboard without the admin login. | Debasmith; test a read-only anonymous view or shared dashboard links. |
| I3 | Shared operation names for metrics, so consumers compare the same names across services. | Vertical; shared #2. |

# 9. Actions and review record

| **Action** | **Owner** | **Completion evidence** |
| --- | --- | --- |
| Finish #81 integration | Darsh | Done: merged into dev; deployed in dd19ff9 (Section 5). |
| Migrate Create / Replace to POST /files and PUT /files | Debasmith | Pull request with tests; docs/API.md updated; live OCI run in TESTING.md. |
| Serve GET /health and GET /health/provider | Owner to be named | Routes over the existing check_health; liveness never calls the provider. |
| Run the conformance suite against Team 6 | Debasmith with Prateek | Revision, markers, failures and cleanup recorded on shared PR #6 and in TESTING.md. |
| Infrastructure Levels 1 to 4 | Debasmith | Evidence listed in Section 10.8. |
| Record remaining error/kind/root decisions | Darsh + affected contacts | Shared #4 decisions and corresponding conformance expectations. |
| Publish additive streaming API | Dayana | Done: tags 0.3.0 and 0.3.1. Package version field to be corrected in a follow-up release. |
| Adopt streaming interface | Darsh | Done: #92 merged, with tests and live OCI evidence (Section 7). |
| Complete missing operations / conformance | Operation owners / Prateek | Owner-linked PRs; current revision’s service-level conformance results and cleanup. |
| Verify deployed revision and monitoring | Debasmith / Dayana | Deployment revision, edge behavior, metrics/dashboard evidence and named operational owners. |
| Refresh Team 1/3 source designs | Respective owners | Use actual package API, current Replace implementation, shared fields/codes, units, and decision links. |
| Record design review dispositions | Faizal + named reviewers | Reviewer, scope, comment, change/answer/accepted risk, link. Retain original dated review records. |

## Review scope and accepted risks

Whole-design review and contract-facing review are recorded separately. Review accepts the described design at a stated revision; tests and provider runs establish implementation evidence. The historical November 4 review records remain historical and should not be silently presented as current.

S3 Move and folder Delete are not atomic. Failed writes can have uncertain outcomes.

Team 6 Replace currently has a concurrent-writer race until conditional-write behavior is verified and adopted.

Empty folders and letter case differ across providers. Keep those differences explicit.

Debasmith’s reported 200 MB upload is deployment evidence; it does not replace exact 150 MiB/1 GiB boundary tests or prove the portable limit on all services.

# 10. Infrastructure and operations (Team 6, Milestone 3)

Owner: Debasmith Mandal. Status: the service is deployed and running (Observed, 10.1). The Milestone 3 work that makes the deployment reproducible, automated and observable (Levels 1 to 4) is Planned and tracked in 10.8. This section covers Team 6’s own infrastructure; teams in the vertical share conventions (conformance checks, operation names), not accounts, deployments or state.

## 10.1 Current deployment (Observed, November 11)

| **Aspect** | **Today** |
| --- | --- |
| Host | Oracle Cloud Always Free Ampere (ARM64) VM in Amsterdam, shared with other personal services |
| Runtime | Docker container defined as a Portainer stack, published by Traefik with TLS at https://ds.packapunch.xyz |
| Code | A git checkout of dev, bind-mounted into the container; uv installs the locked dependencies at container start |
| Deploy | Manual: git pull on the host, then a container restart |
| Configuration and secrets | Environment variables in Portainer, including the OCI customer secret key |
| Health | No HTTP health route (Section 6) |
| Startup validation | config.load_settings raises ConfigError naming a missing setting, never its value |
| Telemetry | One JSON request_failed line per failed request; no metrics, traces or alerts |

Gaps against Milestone 3: no built artifact (the container runs source from a folder), infrastructure not in version control, no plan step or shared state, no pipeline, and no telemetry beyond failure logs. If the host were lost, only Debasmith could rebuild the service. The levels below close these gaps in order, because each depends on the one before it.

## 10.2 Tool choices, owners, cost and teardown

| **Concern** | **Choice** | **Reason** | **Account owner** | **Expected cost** | **Status** |
| --- | --- | --- | --- | --- | --- |
| Hosting | Existing OCI Ampere VM with Docker and Traefik | Already serves the API with TLS; no new account | Debasmith | $0 (Always Free shape) | In use |
| Artifact | Docker image from a Dockerfile in the repository, pushed to GitHub Container Registry | Image identified by commit SHA and digest | Repository owner; pushed by CI | $0 expected (private-repository storage allowance to confirm) | Planned |
| Infrastructure as code | OpenTofu with the Docker provider (container, network, Traefik labels) and the OCI provider (data bucket) | Plan before apply, repeatable applies, and a destroy that matches the description | Debasmith | $0 | Planned |
| Infrastructure state | OpenTofu S3 backend on a separate private OCI bucket, versioned | Shared and protected rather than on one machine | Debasmith | $0 expected (Always Free storage) | Planned |
| Delivery | Extend the existing CI (lint, format, type and fast tests on every pull request) with infrastructure checks, an image build and a deploy job | One place to see a change from review to deployment | Repository owner | $0 expected | CI checks in use; deployment Planned |
| Telemetry | OpenTelemetry SDK in the service; Collector, Prometheus, Loki, Tempo and Grafana on Debasmith’s Mumbai OCI VM | Vendor-neutral instrumentation; the backend can change without code changes | Debasmith | $0 (existing VM) | Planned (next step) |
| Alerting | Grafana alerting to the team Slack channel or email | Reaches a person, with dashboard and runbook links | Debasmith | $0 | Planned |

Teardown date: the end of the course, after HW3, which builds on this service and its pipeline. The exact date is to be agreed by the team; until then, resources not needed by the running service are removed as soon as they are replaced.

Alternatives considered: a Portainer stack updated from Git was rejected because it has no preview step and keeps state on one host. Grafana Cloud’s free tier would mean less to operate, but its limits and retention are outside our control; the instrumentation is the same either way, so the choice can be revisited.

## 10.3 Level 1: run it somewhere else

- Artifact: a multi-stage Dockerfile installs dependencies with uv sync --locked, runs as a non-root user, and is built for linux/arm64. It holds code and locked dependencies only, no credentials or bucket names. The commit SHA is recorded as an image label and a RELEASE variable, so the running service can report its release.
- Infrastructure: an infra/ folder with two OpenTofu workspaces, staging (disposable, ds-staging.packapunch.xyz) and demo (ds.packapunch.xyz). Images are pinned by digest, so a second apply with unchanged inputs reports no changes. Portainer becomes view-only for this service, because edits there would drift from the code.
- Configuration and secrets: non-secret settings are committed per workspace. The OCI customer secret key lives in CI environment secrets and reaches the container at apply time. The Docker provider records container environment in state, so state stays in the private state bucket and never in the repository or CI artifacts.
- Health: GET /health is liveness and never calls the provider; the Docker health check and Traefik use it. GET /health/provider is readiness and is used by the smoke check and the dashboard, not by the restart policy, so an OCI outage shows as "not ready" instead of a restart loop.
- Teardown: tofu destroy removes the containers, their routing and the data bucket. It intentionally leaves the VM, Docker, Traefik, the wildcard DNS record and certificate (shared with other services) and the state bucket, which is deleted by hand last.
- Manual one-time steps, documented in infra/README.md: create the OCI customer secret key and the state bucket, install Docker on a fresh host, add the CI secrets.

## 10.4 Level 2: ship through a pipeline

| **Trigger** | **Checks and actions** |
| --- | --- |
| Every pull request | Existing lint, format, type and fast tests; the shared conformance suite against the in-memory reference app; tofu fmt, validate and plan when infra/ changes. No deployment credentials. |
| Merge to dev | Build the image once, tag it with the commit SHA, deploy it to staging, run the smoke check. |
| Release tag on main | Deploy the digest already built for that commit to demo, run the smoke check, mark the release successful only if it passes. |

The smoke check exercises the shared API against the real provider through the public URL (provider health, create, metadata, download with a byte comparison, list, move, delete) under a unique /smoke/<sha>/ prefix that it deletes afterwards. Deploys share one concurrency group and queue rather than cancel. Rollback is a manually started run that applies the previous known-good digest and repeats the smoke check; it restores code and configuration, not provider writes, which are traced through request logs by operation, path prefix and release.

Proposed runner: a self-hosted runner on the Amsterdam VM, under its own user, that runs only the deploy workflow. It builds natively for ARM and needs no inbound SSH. Accepted risk: anyone who can merge to dev can run code on that host; the repository is private and limited to the five team members. Alternative: hosted runners deploying over SSH, which needs port 22 open to CI and an emulated ARM build.

## 10.5 Level 3: observe the internals

- Traces: OpenTelemetry’s FastAPI instrumentation in main.py for server spans, and its botocore instrumentation for a separate span per S3 call. The provider span needs no change to storage/s3.py, so boto3 still appears only there.
- Metrics per shared operation: request count, error count by error category, and latency histograms with successes and failures separated. Saturation: requests in flight against the concurrency limit uvicorn is started with.
- Logs: the existing request_failed line becomes one JSON line for every request, adding release, trace_id, outcome and duration_ms.
- Never recorded: credentials, authorization headers, file contents, request or response bodies, or provider error text. Metric labels are limited to operation, outcome, status class and release; never paths or file names.
- Telemetry failure: exports are asynchronous with bounded queues and drop data when full, so a telemetry outage never fails, slows or retries a storage request.
- Dashboard: the four golden signals per shared operation with the deployed release visible; no traffic is shown as its own state, using the probe in 10.6. Telemetry between the two VMs travels over a private WireGuard tunnel.

## 10.6 Level 4: make a promise (Download)

Download is the operation Team 6 proposed for the vertical (shared #8) and the one consumers rely on to get their data back.

| **SLI** | **Eligible events** | **Good events** |
| --- | --- | --- |
| Availability | GET /files/download requests reaching the service, excluding caller errors (400, 404) | 200 responses whose body was sent completely |
| Latency | Successful downloads | Headers sent within the threshold (time to first byte) |

Time to first byte is used because total time grows with file size. Provider failures (502, 503) count against availability, since consumers experience them either way. The SLI cannot see requests that never reach the service (DNS, TLS, proxy or host failures); the external probe partly covers this.

Starting proposal, to be confirmed after one week of measured traffic: availability 99% and latency 95% under 500 ms to first byte, both over a rolling 7 days. At 2,000 eligible downloads a week, 99% allows 20 bad requests. A synthetic probe downloads a known test file every minute, so there is always traffic. The alert fires when availability over 15 minutes falls below target with a minimum request count, treats missing data as its own alert, reaches Slack or email with dashboard and runbook links, and resolves when the condition clears. Error budget policy: when a budget is spent, merges to dev are limited to reliability fixes until it recovers, and the next team update records the cause.

## 10.7 Risks and limits

- No caller authentication: anyone with the URL can write to the demo bucket. Mitigated by test-only data, upload limits and teardown at the end of the course; adding authentication would be a contract change.
- Shared host: other services run on the same VM; a container memory limit bounds this service.
- One account owner for hosting and telemetry, mitigated by the documentation and the Level 1 verification by a teammate.

## 10.8 Verification and evidence

| **Level** | **Verification** | **Status** |
| --- | --- | --- |
| 1 | A teammate who did not write infra/ provisions from a fresh checkout, reaches the shared API, repeats the plan, and tears down; their questions are recorded as documentation gaps. The deployed service passes the conformance suite. | Not started; conformance blocked on Create/Replace and Health |
| 2 | A working release, then a deliberately broken one to staging that the smoke check stops; the previous revision restored and verified. | Not started |
| 3 | One success, one provider failure and one invalid request, each traced from the dashboard to its log entry and trace by a teammate; one log entry and one trace checked for sensitive values. | Not started |
| 4 | Each SLI’s numerator, denominator, window and current value over a recorded run; the alert caused in staging, received and resolved. | Not started |

# Sources

October 28 shared Document Storage memo; original consolidated design prepared by Faizal Rahman (November 4).

Shared package 0.2.0: https://github.com/Dayana20/ospsd26-cloud-storage/tree/0.2.0

Error rules #4; Move #5; conformance PR #6; route/List discussions #8 and #10 in the shared repository.

Shared package 0.3.1: https://github.com/Dayana20/ospsd26-cloud-storage/tree/0.3.1

Team 6 implementation/evidence: merged #74, #79, #81, #83, #84, #87, #88, #90 and #92 in https://github.com/FaizalJnu/OSPSD-TEAM-6; live evidence in TESTING.md.

Team 1 design PR: https://github.com/Dayana20/sandbox/pull/32

Team 3 design revision: 96376ed; current dev inspected at 25adaa7.

Dayana’s November 11 streaming agreement and Darsh’s review of shared PR #12; Debasmith’s November 10 deployment report and November 11 redeploy check.

HW2 handout, Milestone 3 and Levels 1 to 4, for Section 10.

Updated November 11, 2026  •