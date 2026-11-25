# **DESIGN: Document Storage vertical adopts one shared API**

| Title | Teams 1, 3 and 6 adopt the shared Document Storage API |
| :---- | :---- |
| **Authors** | Consolidated by Faizal Rahman (Team 6\) from the three teams' design inputs |
| **Team and vertical** | Document Storage. Team 1 (Dropbox): Dayana, Annie, Shini. Team 3 (Dropbox): John Ashik, Shreyas Kaldate, Zesan Rahman, Jing Qian, Victor Wang. Team 6 (S3-compatible, verified on OCI Object Storage): Faizal Rahman, Debasmith Mandal, Vikram Markali, Darsh Shani, Prateek Saxena |
| **Coordinator** | Dayana (Team 1\) |
| **Implementation contacts** | Yashwanth (Team 1), Jing Qian (Team 3), Debasmith Mandal (Team 6\) |
| **Reviewers** | Whole design: a Team 6 teammate, TBD. Contract-facing parts (sections 3, 5 and 6): one reviewer each from Team 1 and Team 3, TBD |
| **Status** | In review, Milestone 2 (Design Document) |
| **Last updated** | Nov 4, 2026 |
| **Decision memo** | [Shared Document Storage API memo, Oct 28, 2026](https://docs.google.com/document/d/1K9U8uO-FVbeu0PGlWpr_frJ6YQmoHXdz/edit) |
| **Shared contract** | [Dayana20/ospsd26-cloud-storage](https://github.com/Dayana20/ospsd26-cloud-storage), tag 0.1.0. That tag holds the course template, not storage code. Until a storage tag exists, this document follows the memo and the proposals and conformance suite draft in the shared repository |
| **Implementation work** | Team 1: [Dayana20/sandbox](https://github.com/Dayana20/sandbox). Team 3: [Shreyas191/OSPSD-Team-3](https://github.com/Shreyas191/OSPSD-Team-3). Team 6: [FaizalJnu/OSPSD-TEAM-6](https://github.com/FaizalJnu/OSPSD-TEAM-6) |

**How to read this document.** The memo and the shared repository are the authoritative contract. This document summarizes only what each team needs in order to build to it, and how. Each rule is labelled:

* **Agreed**: in the memo's decision list, or confirmed by every team that responded to the shared proposal.

* **Proposed**: written down in a shared proposal or a team design, but not yet confirmed by all three teams.

* **Open**: no agreed proposal yet. Section 8 lists every open question.

Evidence is labelled **Observed** (someone ran it; who and when are given), **Planned** (not built), or **Assumed** (taken from provider documentation, not yet run).

## **1\. Context, goals, and non-goals**

### **Context**

A consumer wants to upload, read, move, list and delete documents without caring which service stores them. Three teams each run a FastAPI document store: Teams 1 and 3 on Dropbox, Team 6 on any S3-compatible provider (verified on OCI Object Storage, AWS S3 and Google Cloud Storage). All three can upload, download, read metadata and delete, but a caller has to write different code for each. Some differences cause silent data loss rather than an error.

### **Incompatibilities today**

| Behavior | Team 1 | Team 3 | Team 6 | What a caller must change, or can lose |
| :---- | :---- | :---- | :---- | :---- |
| Create | POST /files (file, path) → 201; never overwrites (409) | POST /files/upload (file, remote\_path, overwrite) → 200 | POST /files/{key} → 201; 409 if taken | Three request shapes for one operation |
| Replace | Not available | Same upload route with overwrite=true; creates the file if missing | PUT /files/{key}; 404 if missing | A caller written for Team 3 gets 409 on Team 1, and creates files where Team 6 would return 404 |
| Delete a folder | 400 | Deletes the folder and everything in it | No folders: deletes one key | A caller that relies on recursive delete leaves data behind on Team 1 and Team 6 |
| Path form | /docs/report.pdf in ?path=; rejects a missing leading / | Same as Team 1, but rejects with 422 | docs/report.pdf in the URL; rejects a leading / | A path valid on one service is rejected on another |
| List | Not available | GET /folders/list?path=: plain array, one level, includes folders | GET /files?prefix=\&limit=\&cursor=: {files, next\_cursor}, every depth | Two incompatible shapes, and nothing on Team 1 |
| Move | PATCH /files?path= with {"new\_path"} | POST /files/move with from\_path, to\_path | Not available (S3 has no move) |  |
| File info | id, name, path, size, modified\_at (no timezone) | Adds is\_folder; modified with no timezone | key, size, content\_type, etag, last\_modified (UTC, Z) | Field names and timestamp formats differ |
| Error body | {"error": {"code", "message"}} | Same as Team 1 | {"error": "\<Type\>", "detail"} | A generic error handler breaks on Team 6 |
| Bad input | 400 invalid\_request | 422 invalid\_input | 400 InvalidInput | Same mistake, different status |
| Upload limit | 150 MiB, 400 above it | 150 MB per Dropbox docs (unit unverified) | 1 GiB, 413 above it |  |

Sources: the memo's comparison of the three services, and the three design inputs.

### **Goals (observable)**

* **One workflow, three services.** A consumer runs this workflow against each service with the shared request shapes, changing only the base URL and credentials: create, metadata, download and compare bytes, list the folder, move, metadata at the new path, delete, metadata returns 404\. It is the workflow test in the shared conformance suite.

* **Conformance.** Each service passes the shared conformance suite against its real provider before tagging a release, with every proposed marker removed once its rule is agreed.

* **One error model.** Every error the application produces uses {"error": {"code", "message"}} and the code table in section 5\. Consumers branch on the status and the code, never the message.

* **Nothing disappears silently.** Every existing route or field that is not in the common core is either kept as a documented extension or its removal is recorded in section 6 with migration instructions.

### **Non-goals**

* **Moving data between providers.** A path or id refers to a file in one service's storage. Switching services does not bring the files along.

* **Choosing a bucket or app folder in requests.** Each deployment serves one Dropbox app folder or one bucket, set by its credentials. A consumer switches storage by changing the base URL and credentials.

* **Hiding provider differences we cannot remove.** Letter case and folders behave differently on Dropbox and S3 (section 3). The contract states these limits instead of promising behavior a provider cannot give.

* **Requiring every provider feature.** Extensions stay with one service and a consumer must not depend on them: Team 1's Redis metadata cache and Idempotency-Key uploads; Team 3's rename, copy, create-folder and search routes, folder move, and 503 service\_busy overload protection; Team 6's etag and content\_type fields and its 1 GiB upload limit.

* **Standardizing authentication.** Each service keeps its own provider credentials. None of the three authenticates API callers; deployments restrict access.

* **Changing providers during a running request.**

## **2\. Proposed architecture and request flow**

### **Common shape**

All three services keep their existing layering. Routes depend only on a provider-independent interface; one adapter per provider is the only code that imports the provider SDK. The shared Python package (Planned, Python ≥ 3.12, no provider SDK) will hold the models and errors each service uses at that boundary.

flowchart LR  
    caller\["Consumer\<br/\>(HTTP)"\]  
    routes\["Routes\<br/\>shared HTTP contract"\]  
    rules\["Rules\<br/\>paths, create vs replace, limits"\]  
    iface\["Provider-independent interface"\]  
    pkg\["Shared package\<br/\>models \+ errors (planned)"\]  
    dbx\["Dropbox adapter\<br/\>Teams 1 and 3"\]  
    s3\["S3 adapter\<br/\>Team 6"\]  
    caller \--\> routes \--\> rules \--\> iface  
    routes \-. uses .-\> pkg  
    rules \-. uses .-\> pkg  
    dbx \-. implements .-\> iface  
    s3 \-. implements .-\> iface

### **Components per team**

| Layer | Team 1 | Team 3 | Team 6 |
| :---- | :---- | :---- | :---- |
| HTTP routes | app/api/routes/ | cloud\_storage\_service (FastAPI routes) | src/storage\_service/routers/ (one module per operation) |
| Rules and path handling | app/validation.py (clean\_up\_path planned) | Routes and client; clean\_up\_path planned | service.py (validate\_key, create vs replace, size limit) |
| Interface | app/providers/base.py (DocumentStorage) | cloud\_storage\_client\_api (Client, File), to be replaced by the shared package | storage/base.py (StorageClient) |
| Provider adapter | app/providers/dropbox/ (DropboxStorage, error\_mapping.py) | dropbox\_client\_impl (DropboxClient) | storage/s3.py (S3Storage, the only module importing boto3) |
| Error → HTTP | app/main.py, app/errors.py | SharedErrorRoute, plus app-level 404/405/500 handlers (planned) | routers/error\_handlers.py |
| Test backend | Fake storage | FakeStorageClient | storage/memory.py, tests/fakes.py (FakeStorage) |

**Who creates and closes the provider client.**

* **Team 1:** get\_dropbox\_client() builds one client from .env the first time a request needs it and caches it with functools.cache. The app starts without credentials; a missing credential is not cached, so fixing .env and retrying works. Nothing closes the client.

* **Team 3:** the app's lifespan calls build\_storage\_client() once at startup and stores it on app.state. Missing credentials stop the app from starting.

* **Team 6:** create\_app() calls build\_service(load\_settings()) at startup; build\_storage is the only code that picks a backend (STORAGE\_BACKEND=s3 or memory). Missing S3\_\* settings raise ConfigError and stop the app from starting. One boto3 client lives as long as the app, with path-style addressing, standard retry mode (3 attempts), and 5 s connect and 60 s read timeouts.

**State.** No service keeps file state of its own: the Dropbox app folder or the bucket is the only copy. Team 1's optional Redis cache and idempotency records are extensions outside the contract.

### **Interface changes for the shared operations**

| Team | Change |
| :---- | :---- |
| Team 1 | DocumentStorage gains replace, list and health; delete accepts folders |
| Team 3 | Replace the local Client contract with the shared package; DropboxClient gains check\_health(), a revision-checked replace, and the new metadata model |
| Team 6 (Planned) | StorageClient gains copy(src, dst) (CopyObject), delete\_many(keys) (DeleteObjects, up to 1000 keys a call), check\_health() (HeadBucket), and a delimiter argument on list\_files so one page returns direct children and folder prefixes. InMemoryStorage implements the same methods and tests/test\_storage\_contract.py checks both backends. Routes and the shared path never reach storage/: service.py turns /docs/report.pdf into the key docs/report.pdf |

### **Request traces**

**Team 1, success: PUT /files (replace). Observed** Nov 4, 2026 against real Dropbox, by Team 1's integration test tests/integration/test\_replace\_dropbox.py.

1. The route parses form fields file and path; clean\_up\_path normalizes the path. An invalid path returns 400 and Dropbox is not called.

2. DropboxStorage.replace calls files\_get\_metadata(path) to read the current rev (Dropbox call 1).

3. It calls files\_upload(content, path, mode=WriteMode.update(rev), autorename=False, strict\_conflict=True) (Dropbox call 2).

4. to\_file\_resource() converts the result; the route returns 200 with the file info. No log line on success; every response carries X-Request-ID.

On a missing path, step 2 raises a not-found ApiError, which becomes FileNotFoundError, one dropbox\_error log line and one request\_failed line, and 404 not\_found. Nothing is created.

**Team 3, success and 404: GET /files/metadata?path=/Docs/spec.pdf.** DropboxClient.get\_metadata() makes one files\_get\_metadata call and wraps the result in a DropboxFile. On a missing path, \_translate\_get\_metadata\_error() raises FileNotFoundError; SharedErrorRoute maps it to 404 not\_found and writes one structured failure log. No Dropbox type leaves the adapter. Full trace in Team 3's design.

**Team 6, success: GET /files/metadata?path=docs/report.pdf. Planned.** The same provider work runs today behind GET /metadata/docs/report.pdf and is Observed on OCI.

1. FastAPI matches /files/metadata in routers/metadata.py and passes the path query parameter.

2. service.py normalizes it to /docs/report.pdf and derives the key docs/report.pdf. A path that breaks the path rule returns 400 invalid\_request before any provider call.

3. S3Storage.stat calls head\_object(Bucket, Key); \_info\_from\_response builds a FileInfo.

4. The route returns 200 with {"id": null, "name": "report.pdf", "path": "/docs/report.pdf", "size": …, "modified\_at": "…Z", "etag": "…"}.

**Team 6, expected failure: the same request for a missing file. Planned.**

1. head\_object fails with a bare 404\. A HEAD response has no body, so S3 cannot say whether the key or the bucket is missing.

2. stat calls head\_bucket. If the bucket is missing it raises ProviderError (502 provider\_error); if access is denied, AccessDenied (403). Observed on OCI by Faizal Rahman, Oct 21, 2026: before this check, a missing bucket was reported as "file not found".

3. The bucket is fine, so the service checks whether the path is a folder: list\_objects\_v2(Prefix="docs/report.pdf/", MaxKeys=1) (Planned). If anything is under it, the answer is 422 invalid\_operation (metadata is for files).

4. Otherwise error\_handlers.py returns 404 {"error": {"code": "not\_found", "message": "No file or folder exists at '/docs/report.pdf'"}} and writes one request\_failed JSON log line with storage\_call="stat" and provider\_code="404". The provider's own message never reaches the response.

## **3\. API and data model**

### **Routes**

Every file or folder is named by a path query parameter (or form field for uploads). Success statuses below are **Agreed** unless marked.

| Operation | Shared route and success | Agreement | Team 1 change | Team 3 change | Team 6 change |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Health (API) | GET /health → 200 {"status": "ok"}, no provider call | Agreed | None | New | New |
| Health (provider) | GET /health/provider → 200 {"status": "ok"}; 503 in the shared body if the provider is unreachable or not configured. Makes one lightweight provider call | Agreed | New | New: users\_get\_current\_account() | New: head\_bucket |
| Create | POST /files, multipart file, path → 201 file info. Existing file → 409 conflict, nothing overwritten | Route Agreed; 409 Proposed | Code names only | POST /files/upload → POST /files | POST /files/{key} → POST /files |
| Replace | PUT /files, same fields → 200 file info. Missing file → 404, nothing created | Agreed | New (in review) | Must stop creating missing files (Decision 1\) | PUT /files/{key} → PUT /files |
| Download | GET /files/download?path= → 200, exact bytes, Content-Disposition: attachment | Proposed | None | None | GET /files/{key} → shared route |
| Metadata | GET /files/metadata?path= → 200 file info | Proposed | None (timezone, see below) | Drop is\_folder; modified → modified\_at | GET /metadata/{key} → shared route; new file info |
| List | GET /files?path=\<folder\> → 200 JSON array of the folder's direct children (files and folders), sorted by path, every provider page fetched by the service. Missing folder → 404 | Meaning Agreed; entry shape Proposed | New | /folders/list → GET /files; add type, sort | Paged, every-depth list → one-level full list |
| Move | PATCH /files?path=\<from\>, JSON {"new\_path": "\<to\>"} → 200 file info at the new path. Files only. Never overwrites (409) | Proposed. Team 1 agreed; Team 3 has not answered | Case-only rename and folder source: 400 → 422 | POST /files/move → PATCH | New: copy, then delete |
| Delete | DELETE /files?path= → 204, no body. A folder is deleted with everything in it. Missing → 404 | Agreed | Add recursive folder delete | None | Add folder delete |

### **Paths**

* **Agreed:** the service accepts a path with or without a leading / and returns it in canonical form, /a/b/c. Callers use the path in the response, which can differ from what they sent.

* **Agreed:** empty paths and . or .. segments are rejected with 400 invalid\_request.

* **Proposed** (conformance reference app, Team 6 today): empty segments (a//b) and a trailing / are rejected with 400, not cleaned up. Team 3's plan strips them instead (Open question 1).

* **Proposed:** at most 1024 bytes as UTF-8, counting the leading / (the reference app's limit; S3 allows 1024-byte keys). Teams 1 and 3 have not confirmed Dropbox's limit (Open question 1).

* **Team 6 today, Proposed for everyone:** reject ASCII control characters (0–31 and 127).

* **Root:** ?path=/ is valid only for List. Other operations reject it; the status (400 or 422\) is Open question 13\.

* **Letter case:** Dropbox treats /A.pdf and /a.pdf as one file; S3 treats them as two. The contract does not hide this. Consumers must not create paths that differ only in case, and a case-only move returns 422 (Proposed).

* **Team 6 mapping:** the S3 key is the canonical path without its leading /. Existing objects keep their keys, so no stored data moves.

### **File info object**

Returned by create, replace, metadata and move, and (with type) by list.

| Field | Type | Meaning | Status |
| :---- | :---- | :---- | :---- |
| id | string or null | The provider's identifier. Opaque: never parse or build one. Dropbox ids survive move and replace. S3 has no identifier that survives a move, so S3 services return null rather than invent one | null on S3 Proposed; Team 1 agreed |
| name | string | Last path segment, for example report.pdf | Agreed |
| path | string | Canonical path (see Paths) | Agreed |
| size | integer, or null for folders | Size in bytes | Agreed |
| modified\_at | string, or null for folders | When the file last changed: ISO 8601 in UTC ending in Z. The number of fractional-second digits varies, so parse it instead of comparing strings | Field Agreed; UTC Z Proposed. Team 6 sends Z today; Team 1 (Observed Nov 4\) and Team 3 send no timezone |
| etag | string, optional | Fingerprint that changes when the contents change | Optional extension (memo). Team 6 sends it; Team 3 plans it |
| type | "file" or "folder" | List entries only | Proposed |

**Proposed rule:** consumers ignore fields they do not know, so a service can send documented extension fields (etag, Team 6's content\_type) without breaking a client built for another service (Open question 17).

**Mapping current fields to the shared model.** Team 3's is\_folder is dropped (list's type replaces it). Team 6's key and last\_modified become path and modified\_at. Team 6 proposes keeping content\_type as a documented extension, because its download sets Content-Type from it.

### **Representative request and response**

**Team 1, Observed** Nov 4, 2026 against real Dropbox (path shortened). The timezone is missing; the Proposed rule adds Z.

PUT /files  
Content-Type: multipart/form-data  
file=\<bytes\>, path=/docs/report.pdf  
   
200 OK  
{"id": "id:QqRAUO3-OU4AAAAAAAAAVA", "name": "report.pdf", "path": "/docs/report.pdf", "size": 22, "modified\_at": "2026-11-04T16:35:07"}

**Team 6, the same file before and after migration. Illustrative expected response, not yet observed.** The current response is from Team 6's in-memory backend (docs/API.md).

// Today: GET /metadata/photos/2026/cat.jpg  
{"key": "photos/2026/cat.jpg", "size": 17, "content\_type": "image/jpeg",  
 "etag": "08a83d6686281a5a292732435b21f83a", "last\_modified": "2026-10-14T00:20:31.589428Z"}  
   
// Shared: GET /files/metadata?path=photos/2026/cat.jpg  
{"id": null, "name": "cat.jpg", "path": "/photos/2026/cat.jpg", "size": 17,  
 "modified\_at": "2026-10-14T00:20:31.589428Z",  
 "etag": "08a83d6686281a5a292732435b21f83a", "content\_type": "image/jpeg"}

### **Information loss and limits**

* **Upload size.** Every service accepts files up to 150 MiB (157,286,400 bytes), Dropbox's documented limit for one files\_upload call (per Team 3, from the Dropbox SDK docs). Team 6 accepts up to 1 GiB as an extension, so a consumer that relies on more than 150 MiB is tied to Team 6\. Status above the limit: 413 file\_too\_large Proposed; Teams 1 and 3 return 400 today (Open question 10).

* **Timestamps.** OCI reports times in whole seconds, so a create and a replace in the same second show the same modified\_at (Team 6 provider runs). Only etag tells those versions apart, and only Team 6 sends it today.

* **Folders on S3.** S3 has no folders, only keys containing /. A folder exists while at least one key is under it. So on Team 6 an empty folder cannot exist, listing it returns 404 rather than 200 \[\], and deleting a folder's last file removes the folder. Dropbox keeps empty folders. The conformance suite does not test empty folders.

* **A file where a folder is expected.** Dropbox refuses to create /a.pdf/b.txt when /a.pdf is a file, and the reference app returns 422\. S3 accepts both keys. Enforcing the rule on S3 costs one HEAD per parent segment (Open question 16).

* **Replace race on S3.** Dropbox refuses a replace if the file changed between the two calls. Team 6's replace does not, yet (Decision 1, Open question 15).

* **Folder delete and move on S3 are not all-or-nothing** (section 5).

## **4\. Alternatives and tradeoffs**

### **Decision 1: how Replace avoids overwriting someone else's change**

| Option | Provider calls | Missing file | Changed by someone else between the calls | Used by |
| :---- | :---- | :---- | :---- | :---- |
| A. Dropbox files\_upload with WriteMode.overwrite | 1 | Created, breaking the 404 rule | Overwritten without an error | Team 3's in-progress replace |
| B. Dropbox files\_get\_metadata, then files\_upload with WriteMode.update(rev) | 2 | 404, nothing created | Refused: 409 conflict | **Chosen** by Team 1 (Observed live) and Team 3 (Planned) |
| C. S3 HeadObject, then PutObject | 2, plus a HeadObject to read back the file info | 404 | Overwritten: last write wins | Team 6 today; **chosen for the first tag** |
| D. S3 HeadObject, then PutObject with If-Match: \<etag\> | Same as C | 404 | Refused with 412, mapped to 409 | Team 6 candidate. **Assumed** from AWS documentation; not run on OCI or Google Cloud Storage |
| E. The consumer sends the version it last read (If-Match header) | 1 | 404 | Refused even if it changed minutes earlier | Needs a version field every service returns; only Team 6 sends etag |

**Why.** B is the only Dropbox option that meets both memo rules (404 for a missing file, no silent overwrite) without a new field; its extra call is the one the 404 rule needs anyway. For Team 6, D would give the same guarantee as B, but whether OCI honours a conditional PutObject is unverified, and multipart uploads need the condition on the completing call. Team 6 ships C, documents the race (as its README does today), and runs D against OCI before deciding.

**Cost.** Two calls per replace instead of one. Team 3 notes that a file deleted between the two Dropbox calls can be recreated, because Dropbox always writes when no file exists (Assumed from Dropbox docs).

**Revisit if** the vertical adds a version field every service returns (then E), or OCI honours If-Match (then Team 6 moves to D).

### **Decision 2: path in the query string, not in the URL**

**Chosen:** ?path= for every operation (Teams 1 and 3 already do this). **Alternative:** Team 6's key-in-URL routes (/files/{key}).

Only one team changes instead of two, and a path containing / needs no special route matching. The cost falls on Team 6: every route changes.

**Team 6 sub-decision: remove the current routes or keep them as compatibility aliases.** Team 6 removes them in its next release and documents the migration in docs/API.md. Aliases would not keep old callers working:

* GET /files/{key:path} overlaps GET /files/download and GET /files/metadata. A file whose key is download or metadata would become unreachable through whichever route loses.

* Every alias would answer errors in the new body, so a caller that reads error as a string breaks anyway.

* The only known callers are Team 6's own tests and README examples. The memo tells other verticals not to build against a storage service before the contract is tagged (Assumed: nobody does).

Team 3 made the same choice for the same reasons.

### **Decision 3: normalize paths instead of rejecting them**

**Chosen (Agreed):** add a missing leading / instead of returning 400\. A Team 6-style path (docs/report.pdf) then works on Teams 1 and 3, and a Teams 1/3-style path works on Team 6\. **Cost:** the returned path can differ from the request, so callers must use the path in the response. **Revisit if** the contract requires paths to be returned exactly as sent.

### **Decision 4: where the shared error body is produced**

FastAPI answers unknown routes (404 {"detail": "Not Found"}), wrong methods (405) and unexpected exceptions (500 plain text) before any route code runs. Team 3 observed this on Nov 3, and Team 6 documents the same gap. A consumer that branches on 404 would read a mistyped route as a missing file.

**Chosen (Proposed):** each service registers app-level handlers so these also use the shared body, with codes route\_not\_found, method\_not\_allowed and internal\_error. Team 6 already converts FastAPI's validation errors to 400 this way and adds the remaining three. Team 3 keeps SharedErrorRoute for route errors and adds the three handlers.

### **Decision 5: Move on S3 is copy, then delete**

S3 has no move or rename. **Chosen (Proposed):** CopyObject (up to 5 GB per call per AWS docs, above Team 6's 1 GiB upload limit), then DeleteObject on the original. **Alternatives:** leaving Move out on S3 breaks the shared workflow; copying without deleting violates "nothing remains at the old path". **Cost:** not all-or-nothing. If the delete fails or times out after the copy, the original may or may not still exist, and the service returns 502 (section 5). Folder move stays a Team 3 extension because on S3 it would be one copy and one delete per key.

### **Decision 6: List returns everything in one response**

**Agreed** in the memo: the service fetches every provider page, so the consumer never handles cursors. **Cost:** response size and provider calls grow with the folder (S3 returns at most 1000 keys per call per AWS docs). Team 6 lists with Delimiter="/", so calls grow with the folder's direct children, not its whole subtree. Team 6's existing cursor paging is the obvious shape if the vertical adds an optional cursor (Open question 6).

## **5\. Failure behavior and operational concerns**

### **Error codes**

Every application error uses {"error": {"code": "…", "message": "…"}}. Consumers branch on the status and the code. Messages are for people and carry no provider details.

The table is **Proposed** by Team 6 (Darsh, error clause owner) in the shared repository. Dayana (Team 1\) agreed to 409 for an occupied destination, 422 for agreed restrictions, and 502 for provider failures. Team 3 has not responded, but its design adopts this table. The conformance suite tests 400, 404, 409, 422 and the route/method codes.

| Status | Code | Meaning | Team 1 today | Team 3 today | Team 6 today |
| :---- | :---- | :---- | :---- | :---- | :---- |
| 400 | invalid\_request | Missing field, malformed path, invalid JSON or multipart | invalid\_request | 422 invalid\_input | InvalidInput |
| 403 | permission\_denied | The provider refused the service's credentials or permissions | permission\_denied | 403 (code not stated; target permission\_denied) | AccessDenied |
| 404 | not\_found | Nothing exists at the path, **in storage the service can reach** | not\_found | not\_found | FileNotFound |
| 409 | conflict | Create or move destination is occupied, or a revision check refused a stale write | conflict | conflict | FileAlreadyExists |
| 413 | file\_too\_large | Upload above the accepted size | 400 invalid\_request | Not stated (its design plans 400\) | FileTooLarge |
| 422 | invalid\_operation | Valid input for an operation the contract forbids: move to the same or a case-only path, a folder where a file is required | 400 | 422 (mixed with bad input) | — |
| 502 | provider\_error | Any other provider failure, a missing bucket or app folder, or a known partial move or folder delete | provider\_error | provider\_failure | ProviderError |
| 503 | provider\_unavailable | Provider unreachable or timed out | provider\_not\_configured only | provider\_unavailable, service\_busy | ProviderUnavailable |
| 404 / 405 / 500 | route\_not\_found / method\_not\_allowed / internal\_error | No such route; wrong method (with Allow); unexpected failure | — | FastAPI body | FastAPI body |

Kept as service-specific 503 codes, both rejected before any provider call: Team 1's provider\_not\_configured and Team 3's service\_busy.

**Team 1's design proposes renaming invalid\_request to invalid\_input and provider\_error to provider\_failure.** That is the opposite direction from the shared proposal, the conformance suite, and Team 3's plan. Under the shared proposal Team 1 renames nothing; Team 3 renames those two codes (Open question 4).

### **Uncertain writes, partial operations and retries**

* **404 means only "not here".** A missing bucket or app folder is 502 provider\_error, never 404 (Proposed). Otherwise a consumer that re-creates "missing" files writes into nothing, or reports data loss that did not happen.

* **A 502 or 503 after create, replace, move or delete does not prove nothing changed** (Proposed; all three teams already give this advice). The caller checks metadata at every affected path before retrying, and for move, at both paths.

* **Known partial composite operations return 502** (Proposed), even when the step that failed was a timeout or a permission error: the caller needs to know the operation was partial more than why.

  * *Move on S3:* the copy succeeded, but deleting the original failed or timed out.

  * *Folder delete on S3:* many DeleteObjects calls. DeleteObjects can answer 200 while listing keys it did not delete, so Team 6 treats a non-empty Errors list as a partial delete (Assumed from AWS docs).

  * *Folder delete on Dropbox:* one files\_delete\_v2 call. Whether a failed call can leave a folder partly deleted is not documented; Dropbox can refuse very large folders with a "too many files" error (Teams 1 and 3, Assumed).

* **Throttling and transient provider 5xx** stay 502 for the first tag. Team 6 has proposed 503 for these, so 502 does not always mean a configuration problem.

* **Retries.** No service retries an operation at the application level: after a 502 or 503 the write may already have happened, so a blind retry could create a duplicate, overwrite a newer change, or delete a file re-created since. Team 6's boto3 client does retry individual provider calls inside one request (standard mode, 3 attempts), before the service reports an error.

* **Downloads.** Once a download's headers are sent, a provider failure can only cut the body off. The service logs the interruption and does not append JSON or claim a 500 (Proposed). Team 6 documents this today.

### **Logging and data exposure**

|  | Team 1 | Team 3 | Team 6 |
| :---- | :---- | :---- | :---- |
| On failure | One dropbox\_error line (operation, error type, Dropbox's error, Dropbox request id) and one request\_failed line (operation, code, status, provider involved, X-Request-ID) | Structured warning: operation, status, code, provider-failure flag, reason | One JSON request\_failed line: operation, status, code, message, provider\_involved, storage\_call, provider\_code, write\_outcome (not\_attempted or unknown) |
| File paths in logs | Never | Possible, in reasons and messages | Yes, in the message |
| Never logged | Tokens, file contents, Dropbox's free-text messages; the access log is turned off (\--no-access-log) | File contents, rejected request values | Credentials, the provider's message, stack traces for expected failures |

**Shared minimum (Proposed):** never log credentials, file contents or the provider's free-text message, and never return provider details to the caller. Whether paths may be logged differs between teams and is not part of the contract.

### **Configuration and credentials**

|  | Team 1 | Team 3 | Team 6 |
| :---- | :---- | :---- | :---- |
| Settings | DROPBOX\_APP\_KEY, DROPBOX\_APP\_SECRET, DROPBOX\_REFRESH\_TOKEN (optional DROPBOX\_ACCESS\_TOKEN), optional REDIS\_URL | DROPBOX\_APP\_KEY, DROPBOX\_APP\_SECRET, DROPBOX\_REFRESH\_TOKEN, MAX\_IN\_FLIGHT\_REQUESTS | STORAGE\_BACKEND, S3\_ENDPOINT, S3\_REGION, S3\_BUCKET, S3\_ACCESS\_KEY, S3\_SECRET\_KEY, MAX\_UPLOAD\_BYTES |
| Missing credentials | App starts; file routes return 503 provider\_not\_configured | App does not start | App does not start (ConfigError) |

All three read credentials from the environment (.env locally, never committed) and never bake them into an image. Live tests in every team write under a unique folder or prefix and delete it afterwards, even when a test fails.

### **Cost of each operation (provider calls)**

| Operation | Team 1 (Dropbox) | Team 3 (Dropbox) | Team 6 today | Team 6 planned |
| :---- | :---- | :---- | :---- | :---- |
| Create | 1 files\_upload | 1 files\_upload (add mode, strict\_conflict) | HeadObject (404) \+ HeadBucket \+ upload \+ HeadObject \= 4\. Uploads over 8 MiB become multipart: 1 create, 1 per 8 MiB part, 1 complete | Same |
| Replace | 2 | 2 (Planned; 1 in the current in-progress version) | HeadObject \+ upload \+ HeadObject \= 3 | Same (D adds a condition, not a call) |
| Download | Not stated | Not stated | 1 GetObject, streamed | Same |
| Metadata | Not stated | 1 files\_get\_metadata | 1 HeadObject; \+1 HeadBucket on a miss | \+1 ListObjectsV2 on a miss, to detect a folder |
| Move | 2 (files\_get\_metadata, files\_move\_v2) | Not stated | — | About 5: HeadObject source, HeadObject destination (+HeadBucket), CopyObject, DeleteObject, HeadObject new path |
| Delete (file) | 2 (files\_get\_metadata, files\_delete\_v2) | Not stated | HeadObject \+ DeleteObject \= 2 | Same |
| Delete (folder) | 2 (files\_delete\_v2 deletes the folder in one call) | Not stated | — | HeadObject \+ HeadBucket \+ 1 ListObjectsV2 and 1 DeleteObjects per 1000 keys |
| List | files\_list\_folder \+ 1 files\_list\_folder\_continue per extra page | Same | 1 ListObjectsV2 per page of up to limit | 1 ListObjectsV2 (Delimiter="/") per 1000 direct children |
| Provider health | 1 (call not named in Team 1's design) | 1 users\_get\_current\_account | — | 1 HeadBucket |

### **Deployment tools and hosting (for Milestone 3\)**

All three teams assume a stateless container, credentials from a secret store, one app folder or bucket per deployment, and liveness checks on GET /health only, so a provider outage never restarts the container.

* **Team 1:** hosting not decided; owner to be named, decision by Nov 7\.

* **Team 3 (Proposed):** Docker image on Google Cloud Run (test and demo services), Google Secret Manager, OpenTofu, CircleCI deploys through workload identity federation, OpenTelemetry to Grafana Cloud. Teardown Dec 18, 2026\.

* **Team 6:** not decided (Open; owner TBD, needed before Milestone 3 work starts).

## **6\. Migration and coordination plan**

### **Shared package revision**

The services pin a tag, never a branch. The only tag, 0.1.0, holds the course template, so no team can pin the storage contract yet. Until the coordinator tags one, every team works to the memo and the shared proposals, and records the revision it read. Team 6 has asked who owns the storage package's setup, name, layout and Python support (Open question 11).

**Python.** The memo fixes the shared package at Python 3.12. Team 1 documents 3.10, Team 3 runs 3.11, and Team 6 requires 3.13. The package should declare requires-python \= "\>=3.12", so Team 6 can depend on it without downgrading. Teams 1 and 3 move to 3.12.

### **Milestone 2 checkpoint**

| Requirement | Team 1 | Team 3 | Team 6 |
| :---- | :---- | :---- | :---- |
| Depends on a tagged revision of the shared package | Blocked: no storage tag exists | Blocked: no storage tag exists | Blocked: no storage tag exists |
| One common operation end to end against the real provider | Replace on Dropbox, Observed Nov 4 | Not reported | Not yet through the shared routes. The same provider operations run today on OCI through Team 6's current routes |
| Remaining work opened as issues with owners and dependencies | Team 1's design, section 6 | Team 3's design, work breakdown | Work breakdown below; issues to be opened from it |

### **What changes, per team**

**Team 1** (from Team 1's design)

| Area | Change | Effect on existing callers |
| :---- | :---- | :---- |
| Routes | Add PUT /files, GET /files, GET /health/provider | None (additive) |
| Delete | Folders deleted recursively instead of 400 | A caller that relied on the 400 now deletes data. In release notes |
| Paths | Add a missing leading / instead of rejecting | A request that returned 400 now succeeds |
| Move | Case-only rename and folder source: 400 → 422 (agreed by Yashwanth) | Callers branching on 400 for these cases change |
| Errors | Under the shared proposal, no code renames. Add 413 file\_too\_large if agreed | Callers checking 400 for oversized uploads change |
| modified\_at | Add UTC Z | Callers parsing a naive timestamp change |
| Python | 3.12 (.python-version, CI, requirements.txt) | None |

**Team 3** (from Team 3's design)

| Area | Change | Effect on existing callers |
| :---- | :---- | :---- |
| Routes | POST /files/upload → POST /files \+ PUT /files; POST /files/move → PATCH /files; /folders/list → GET /files; add health routes. No aliases | Breaking for every existing caller. Released as v0.2.0 with release notes |
| Replace | Revision-checked replace (Decision 1, option B); 404 for a missing file | A replace that used to create a file now returns 404 |
| Metadata | Drop is\_folder; modified → modified\_at in UTC Z; optional etag | Breaking for field readers |
| Errors | Bad input 422 → 400 invalid\_request; invalid\_input/provider\_failure → shared codes; 404/405/500 handlers | Breaking for callers branching on 422 |
| Extensions kept | Rename, copy, create folder, search, folder move, 503 service\_busy | None |
| Python | 3.11 → 3.12; replace local cloud\_storage\_client\_api with the tagged package | None |

**Team 6** (this document)

| Area | Change | Effect on existing callers |
| :---- | :---- | :---- |
| Routes | Key-in-URL routes → shared ?path= routes; current routes removed (Decision 2\) | Breaking: every caller changes URLs. Migration table in docs/API.md |
| Paths | Accept /docs/a.pdf and docs/a.pdf; return the canonical form; the key is the path without its leading / | Stored objects unchanged; no data migration |
| File info | key, last\_modified → id (null), name, path, modified\_at; etag and content\_type kept as extensions | Breaking for field readers |
| Errors | {"error", "detail"} → {"error": {"code", "message"}} with the shared codes; handlers for unknown route, wrong method, unexpected failure | Breaking for callers reading error as a string |
| List | Paged every-depth list (prefix, limit, cursor) → one-level full list with type | Breaking. The paged list is removed unless Open question 6 adds an optional cursor |
| Delete | DELETE on a folder deletes every key under it | **Behavior change:** a request that returned 404 for a prefix now deletes data. In release notes |
| Move | New (Decision 5\) | Additive |
| Health | New GET /health, GET /health/provider | Additive |
| Upload limit | Unchanged at 1 GiB, 413 above | None |
| Version | Released as v0.3.0 (pyproject.toml is at 0.2.0) |  |
| Tests, examples, docs | Update every operation's test file, the README examples, docs/API.md, docs/ARCHITECTURE.md and TESTING.md | None |

### **Team 6 work breakdown**

Owners follow the memo's clause owners and Team 6's current operation owners. **To be confirmed at the next Team 6 meeting.** Target for all items: Milestone 3 (Nov 11, 2026).

| Work | Owner | Depends on | Verification |
| :---- | :---- | :---- | :---- |
| Error body, code table, 404/405/500 handlers | Darsh | Error codes agreed | Updated tests/test\_failures.py, tests/test\_invalid\_input.py |
| Path normalization, path-to-key mapping, ?path= routes | Faizal | Open question 1 | tests/test\_service.py; conformance path tests |
| Create and Replace on the shared routes | Debasmith | Paths | tests/test\_upload.py; conformance create and replace tests |
| Download and Metadata routes, new file info model | Vikram (Download), Darsh (Metadata) | Paths | tests/test\_download.py, tests/test\_metadata.py; one OCI run each |
| Move (copy, then delete) and a recorded OCI run | Vikram | Move agreed | Stubbed partial-failure test (copy succeeds, delete fails → 502); OCI run in TESTING.md |
| One-level full List with type | Prateek | List shape agreed, Open question 6 | Stubbed multi-page test; OCI run with more than 1000 keys |
| Folder delete (list \+ DeleteObjects) | Faizal | Open question 7 | Stubbed DeleteObjects with a non-empty Errors list → 502; OCI run with a nested folder |
| Health routes (HeadBucket) | TBD | — | Fake and stubbed missing-bucket tests |
| Run conformance against Team 6 on OCI | Prateek | All of the above, a storage tag | Recorded run in TESTING.md |

**Early end-to-end step.** Before the rest of the work merges, Team 6 runs the shared workflow test against its service on OCI as soon as the path mapping and the create, metadata and delete routes are in. That exposes a wrong path mapping or file info shape before Move, List and folder Delete are built on it.

Team 1's and Team 3's work breakdowns are in their own designs.

### **If the contract changes after implementation starts**

1. Whoever finds the problem opens an issue on the shared repository with the defect and its consequence, and does not patch the contract alone.

2. They announce it in the \#document-storage Slack channel. The affected consumers are the other two storage teams and any team in another vertical that calls a storage service.

3. A breaking change needs sign-off from all three implementation contacts (Yashwanth, Jing Qian, Debasmith Mandal) and a new tag from the coordinator.

4. Each team adopts the new tag when ready. A change reaches a team only when it moves its pin.

## **7\. Testing**

### **Layers in every team**

| Layer | What it shows | Team 1 | Team 3 | Team 6 |
| :---- | :---- | :---- | :---- | :---- |
| Fast, controlled storage | Routes accept the shared shapes and return the shared body | tests/ with fake storage | src/cloud\_storage\_service/tests/ (82 route tests) | tests/test\_\*.py with InMemoryStorage and FakeStorage |
| Provider translation, no network | Provider answers and errors become the documented results | Mocked Dropbox | Mocked SDK in src/dropbox\_client\_impl/tests/ | botocore Stubber |
| Real provider | Behavior we depend on | tests/integration/ under /integration-tests/ | tests/integration/, unique scratch folders | pytest \-m provider, unique api-tests/ prefixes |
| Conformance | The three services behave the same | Shared suite | Shared suite | Shared suite |

Fast tests need no network or credentials in any team.

### **Shared conformance suite**

Drafted by Prateek (Team 6\) in the shared repository. **Observed:** its 54 tests pass against the in-memory reference app, both in-process and over HTTP (Nov 4).

* Tests use only HTTP, so the same tests run against any service. By default they run against the reference app, so CI needs no credentials. A team points them at its own service with CONFORMANCE\_BASE\_URL.

* **Fixtures:** each test works in its own /conformance-\<random\> folder and deletes it at the end.

* One file per operation, plus a workflow test: create, metadata, download and compare bytes, list, move, metadata at the new path, delete, metadata returns 404\. The workflow's operation logic is the same for every service.

* Rules not yet agreed are marked @pytest.mark.proposed and can be skipped with \-m "not proposed": 409 for an existing file, the download and metadata routes, UTC timestamps, the list shape and type, move, and the route/method error codes. When a rule is agreed, its marker is removed.

* **Example of a mismatch it catches:** a replace on a missing path must return 404\. Team 3's in-progress replace creates the file instead, so the missing-file replace test would fail against it (expected from the code; not run).

**Not in the shared suite**, so each team keeps these in its own repository: provider errors (403, 502, 503), because a shared test cannot make a real provider fail on demand; the upload limit; empty folders (S3 has none); lists longer than one provider page (too slow against a real service); and letter case.

No team has run the suite against its own service yet.

### **Guarantees mapped to checks**

| Guarantee | Team 1 | Team 3 | Team 6 |
| :---- | :---- | :---- | :---- |
| Create never overwrites, even identical bytes | test\_upload.py; live test\_upload\_dropbox.py | Live test\_repeating\_an\_identical\_upload\_is\_409 | tests/test\_upload.py; OCI runs recorded in TESTING.md |
| Replace never creates | test\_replace.py; live test\_replace\_dropbox.py (Observed) | New live test\_replace\_missing\_file\_is\_404 (Planned) | tests/test\_upload.py (exists for the current replace route) |
| Replace refuses a stale write | Live test\_replace\_dropbox.py | New live test\_replace\_refuses\_stale\_revision (Planned) | Not guaranteed (Decision 1); OCI If-Match run Planned |
| Move never overwrites; partial move → 502 | test\_update.py; live | Live test\_missing\_source\_and\_conflict | Planned: stubbed copy-then-failed-delete, OCI run |
| Delete removes a folder and its contents | Planned: nested-folder live test | Live test\_delete\_folder\_removes\_contents | Planned: stubbed partial DeleteObjects, OCI run |
| List returns every page, sorted, one level | Planned: mocked has\_more=True, live multi-page folder | Fast pagination tests; new live test\_list\_is\_sorted\_and\_typed | Planned: stubbed multi-page, OCI folder with more than 1000 keys |
| modified\_at is UTC with Z | Not yet (Observed without timezone) | New test\_modified\_at\_is\_utc\_with\_z | Existing file info tests |
| Missing bucket or app folder is not 404 | — | — | tests/test\_bucket\_errors.py; OCI (Observed Oct 21\) |
| Every error uses the shared body | test\_storage\_foundation.py | Route failure tests; new test\_unknown\_route\_uses\_shared\_error\_body | tests/test\_failures.py, tests/test\_invalid\_input.py (to be updated) |
| Failures are logged without secrets | test\_dropbox\_error\_logging.py | Route failure tests | tests/test\_failures.py |

### **Concerns and how they stand**

| Concern | Disposition | Owner | Resolve by |
| :---- | :---- | :---- | :---- |
| No storage tag, so no team can depend on the shared package | Deferred; blocks the Milestone 2 dependency requirement for all three teams | Dayana | Before Milestone 3 work starts |
| Upload limit and partial folder delete are tested only with mocks or stubs | Accepted: real uploads of 150 MiB per run are too slow, and providers cannot be made to fail on demand | Each team | — |
| Stale-write refusal is unverified on OCI | Deferred | Debasmith | OCI run before Milestone 3 |
| No team has run conformance against its own service | Deferred | Each implementation contact | Milestone 3 (required) |

### **Review**

| Document | Reviewer | Scope | Status on Nov 4 |
| :---- | :---- | :---- | :---- |
| Team 1 design | Annie, Shini (internal); Darsh (Team 6, external) | Whole design; API and migration sections | Team 1 marks its design Final |
| Team 3 design | Victor Wang (internal); Darsh (Team 6, external) | Whole design; contract-facing parts | Not started |
| This document | TBD (Team 6 teammate); one reviewer each from Teams 1 and 3 | Whole design; sections 3, 5 and 6 | Not started |

Each substantive comment gets a disposition: a change with a link, an answer, or a reasoned decision to keep the approach. Resolving a thread alone is not a disposition.

| \# | Comment and reviewer | Disposition | Link |
| :---- | :---- | :---- | :---- |
| — | No comments yet | — | — |

**Risks we propose to accept** (reviewers confirm or reject each):

* On S3, Move and folder Delete are not all-or-nothing; a failure returns 502 and the caller checks before retrying.

* Team 6's Replace can overwrite a concurrent change until conditional writes are verified on OCI.

* Dropbox and S3 differ on letter case and on empty folders; the contract documents both and does not work around them.

* Upload limits above 150 MiB and partial folder deletes are tested only with mocks or stubs, not against real providers.

**Scope of approval.** Approval accepts this plan at the reviewed revision. It does not show that the implementation is correct; the conformance suite and each team's live tests do that.

## **9\. Actions**

| Task | Owner | Output | Depends on | Target checkpoint |
| :---- | :---- | :---- | :---- | :---- |
| Name the storage package owner and publish the first storage tag | Dayana (coordinator) | Tag on the shared repository | Open question 11 | Before Milestone 3 work starts |
| Confirm the error codes, 409, missing-storage and uncertain-write rules | Jing (Team 3), Yashwanth (Team 1\) | Responses on the shared proposal | — | Before the first storage tag |
| Confirm Move, id null on S3, and case-only 422 | Jing (Team 3\) | Response on the shared proposal | — | Before the first storage tag |
| Resolve new open questions 13, 14, 16, 17 | Owners in section 8 | Contract text | — | Before the first storage tag |
| Review the conformance suite and run it against each service | Each implementation contact | List of failing tests per service | Storage tag | Milestone 3 (Nov 11\) |
| Run conditional PutObject against OCI | Debasmith (Team 6\) | Result in docs/PROVIDERS.md | — | Milestone 3 (Nov 11\) |
| Team 3 changes its replace to the revision-checked version | Zesan (Team 3\) | Updated replace | — | Nov 8 (Team 3's target) |
| Team 6 confirms owners and opens issues for the work breakdown in section 6 | Team 6 | Issues with owners and dependencies | — | Next Team 6 meeting |
| Team 6 decides on hosting | TBD (Team 6\) | Section 5 update | — | Before Milestone 3 work starts |
| Review this document | Reviewers above | Comments and dispositions | — | Before implementation merges |

## **Appendix A: sources**

* Shared Document Storage API memo, Oct 28, 2026 (Provisional; approved by Yashwanth, Jing and Debasmith on Oct 28).

* Team 1 design document, status Final, Nov 3, 2026, and Team 1's repository.

* Team 3 design document draft, status In review, Nov 4, 2026, and Team 3's repository.

* The shared repository: tag 0.1.0, the shared proposals for health, list, errors and move, and the conformance suite draft.

* Team 6's repository: docs/API.md, docs/ARCHITECTURE.md, docs/PROVIDERS.md, src/storage\_service/.

## **Appendix B: points to correct in the source designs**

Found while consolidating. They do not change the decisions above but should be fixed in the original documents.

* **Team 1:** the error table proposes renaming invalid\_request → invalid\_input and provider\_error → provider\_failure, the opposite of the shared proposal and the conformance suite (Open question 4).

* **Team 1:** the route table still says "TODO final route" for download and metadata, while Decision 2 keeps the current routes.

* **Team 1:** two "VERIFY" notes remain in a document marked Final (the modified\_at timezone and the 150 MB vs MiB limit).

* **Team 1:** the provider health cost names the call as health\_provide; the actual Dropbox call is not named.

* **Team 1:** replace returns 400 for a folder; the reference app and the move proposal use 422 for folder misuse (Open question 14).

* **Team 3:** clean\_up\_path strips trailing slashes and empty segments, but the reference app rejects them with 400 (Open question 1).

* **Team 3:** delete of ?path=/ returns 422, but the reference app returns 400 (Open question 13).

* **Team 3:** the failure section lists uploads over 150 MiB as 400, while Team 3's own open questions propose 413\.

