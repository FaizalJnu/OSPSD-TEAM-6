# New sections for the team design document (Milestone 2)

Draft by Faizal, 2026-11-25. Paste into the shared design document after section 8.
Sections marked "(owner to confirm)" describe teammates' merged code; each owner should
read theirs before it goes in. Section 8.8 is empty in the shared document, so a draft
for Vikram is at the end.

Update the header too: Status → "Working (HW3 Milestone 2)"; Last updated → 2026-11-25;
add `product/docs/BRIEF.md`, `product/docs/READINESS.md` and
`interface/GETTING_STARTED.md` to Relevant links; remove "(Planned; not yet in the
repository)" from the product/ link.

---

# 9. The product (Milestone 2)

Meeting Prep is a meeting prep agent for student project leads. The fixed workflow of
sections 1 to 3 is still the only way a change reaches a provider; Milestone 2 adds the
people and the judgment around it. The brief (`product/docs/BRIEF.md`) gives the user,
the scenarios and the scope.

## 9.1 Components

| Component | What it does | Code | Owner |
|---|---|---|---|
| Interface | Web pages (FastAPI, Jinja, HTMX): sign-in, chat, proposal card with approve and reject, the hand-run workflow, provider connections. Calls only our two services | `interface/` | Prateek |
| Agent service | Conversations, the model loop, four tools, proposals and approvals (section 8) | `product/src/meeting_prep/agent/` | Vikram |
| API service | Sign-in and sessions, per-user reads, the execute endpoint, provider connections, and the fixed workflow of sections 1 to 3. Stateless: every request reads what it needs from the database | `product/src/meeting_prep/api/` | Darsh (sign-in, reads, execute); Faizal (connections) |
| Database | Users, sessions, sign-in challenges, provider connections, conversations, messages, proposals, approvals, outcomes, agent runs. Postgres in deployment, SQLite in tests; Alembic migrations 0001 to 0004, and 0005 for connections | `product/src/meeting_prep/db/` | Each table's owner |
| Model | `openai/gpt-oss-120b` on Groq's free tier, behind our own `ModelClient` (section 8.3) | `agent/model.py` | Vikram |
| Verticals | Our storage (section 1.5), Team 4's Trello package, Team 5's Google Calendar package, each built per user from that user's connection | `adapters/`, `factories.py`, `api/providers.py` | Darsh (adapters), Faizal (registry, connections) |

## 9.2 How they connect

```text
browser ──► interface ──(user's session token)──► agent service ──(same token)──► API service
                │                                       │                             │
                └───────────────(same token)────────────┼─────────────────────────────┤
                                                        ▼                             ▼
                                                   Groq model          database, our storage,
                                                                       Trello and Google
                                                                       (as this user)
```

The agent service holds no provider credentials. It shares the database, but the
provider tokens there are encrypted with a key that only the API service has.
Everything the agent learns about a user's providers comes from the API, as that user.

# 10. One scenario traced: identity, context, approval, execution, verification

Scenario 1, "Prepare Friday's sprint review at 3 pm from our open issues".

1. **Identity.** The user signs in with Google (section 11). The API stores a session
   and sets an HttpOnly cookie. Each later request carries the session token; the agent
   and the API each look it up in the database and take the user ID from that row only.
   A user ID in a body, a query or a model argument is never used.
2. **Context.** The interface sends the message to the agent with the session token.
   The agent loads the conversation by its ID and the session's user, so another
   user's conversation ID returns 404. The model calls `list_open_issues` and
   `list_upcoming_events`; each tool calls the API with the same token. The API builds
   that user's Trello and Calendar clients from their own connections (section 12) and
   returns the data, which the agent passes to the model wrapped as untrusted content.
3. **Approval.** The model calls `propose_review_meeting`. The agent validates the
   arguments, stores the proposal (exact actions, user, hash), and the interface shows
   the card. The user approves; the agent stores the approval against that proposal ID,
   its hash and the user.
4. **Execution.** The agent calls the API's execute endpoint with the approval ID, the
   hash and the session token. The API reads the proposal and approval from the
   database, checks the user, the hash and the status again, and runs the fixed
   workflow: run record and agenda under the user's own storage prefix
   (`/users/<user ID>/`), the Trello card on the user's chosen list with the user's
   token, the event with the user's Google credentials. Terminal outcomes are saved.
5. **Verification.** Each outcome comes from the provider's answer (its ID), never from
   the model. The agent reports the stored outcomes, and the interface shows **Done**,
   **Failed** or **Not sure** for each. Approving again after a failure reuses the
   same run ID, so it finishes what is missing and creates nothing twice (section 2.2).

Where the model's discretion ends: it chooses the title, the time from the user's
words, and the agenda items. Code decides who the user is, which providers and tools
exist, whether arguments are valid, whether an approval matches, and the order and
retries of every write.

# 11. Sign-in and sessions (Darsh to confirm)

**Choice: "Continue with Google"** (OpenID Connect, authorization code with PKCE S256,
a nonce, and a one-use state bound to the browser by a cookie; scope `openid email`).
Our users already have Google accounts because the calendar is Google's, and it uses
the Google Cloud project we already run. **Alternative considered: passkeys.** They
avoid a third-party identity provider, but every user would set up one more credential,
and we would own recovery for a lost device.

* The API validates Google's ID token, checks the nonce, and maps Google's stable
  subject to our own user ID. Accounts are never merged by email address.
* **Session:** an opaque random token. Only its SHA-256 digest is stored. Cookie:
  HttpOnly, SameSite=Lax, and Secure with the `__Host-` prefix over HTTPS. Lifetime 8
  hours. Sign-in challenges expire after 10 minutes and work once.
* **Sign-out** deletes the session row, so the token stops working in both services at
  once: both read the same table on every request.
* **Lost device:** the stolen session works until it expires (at most 8 hours) or the
  user signs out on that device. Limitation: there is no "sign out everywhere" yet.
* **Recovery** is delegated to Google: a user who can sign in to Google gets back the
  same account.

# 12. Provider connections (Faizal)

Status: Planned; implementation started 2026-11-25. Signing in does not connect
anything: a session says who the user is, and a connection lets our backend act in one
of their provider accounts.

## 12.1 What each vertical needs

| Vertical | How the user connects | Scope | Stored |
|---|---|---|---|
| Google Calendar | OAuth 2.0 authorization code with PKCE (S256) and a one-use state, through our Google Cloud project's web client | `calendar.events`, plus `openid email` to show which account is connected | Account email, scopes, encrypted access and refresh tokens, expiry, status |
| Trello | Trello's OAuth 1.0a flow (Trello does not offer OAuth 2.0). Our app key identifies the product; the user approves access on Trello's own page, then picks the list where review cards go | `read,write`, expiring after 30 days | Trello username, encrypted token, expiry, chosen board and list, status |
| Document storage | Nothing to connect. Each user gets a private prefix, `/users/<user ID>/`, in our own bucket | n/a | n/a |

We never ask for a provider password, and nothing falls back to the team's test
accounts: a user without a connection gets `connection_required`, naming the provider
to connect.

## 12.2 Flow

1. `GET /v1/connections/{provider}/start` (signed in). The API creates a one-use
   challenge bound to this user and this session: the state's digest, the PKCE
   verifier (Google) or the request token's secret (Trello), and a 10-minute expiry.
   It redirects to the provider.
2. The provider redirects back to `/v1/connections/{provider}/callback`. The API
   accepts it only if the challenge exists, has not expired, and belongs to the same
   user and session that started it. It deletes the challenge before exchanging the
   code, so a replayed callback fails.
3. The API exchanges the code (with the PKCE verifier) for tokens, encrypts them, and
   saves the connection. For Trello, the user then picks a list from their own boards;
   the API accepts only a list that their token can see.
4. `GET /v1/connections` lists each vertical: connected account, status (`connected`
   or `needs_attention`), and the chosen list. It never returns a token.

## 12.3 Tokens

* Encrypted with a key that lives only in the API service's environment, never in the
  database, the repository, or the image. A database copy alone reveals no token.
* Tokens stay in the API service. The agent and the model never see them; tools return
  provider data only.
* **Refresh (Google):** when the access token has expired, the API refreshes it while
  holding a lock on that connection's row, and saves the replacement before using it,
  so two concurrent requests do not both refresh. If Google answers `invalid_grant`
  (revoked, or expired after 7 days in testing mode), the connection becomes
  `needs_attention` and the user sees "Reconnect Google Calendar".
* **Trello** tokens do not refresh; after 30 days the connection becomes
  `needs_attention`.

## 12.4 Building the partner clients per user

* **Trello:** Team 4's provider takes the key and token as constructor arguments since
  `team-4-issue-tracker-trello-v1.1.0`, so the API builds one per request from the
  user's connection.
* **Calendar:** Team 5's package builds a client only from a token file. Our pull
  request to Team 5 adds a `credentials` argument and an upcoming-events read. Until
  they release it, we install their package from our pull request's exact commit.

## 12.5 Disconnect, sign-out, reconnect

| Action | What it ends | What stays |
|---|---|---|
| Sign out | The session | Connections, conversations, proposals |
| Disconnect a provider | New work through that connection: the stored tokens are deleted, and access is revoked at the provider (Google's revoke endpoint; Trello's token delete) | The account, the session, other connections, conversations |
| Connection expired or revoked | Work through that connection, until the user reconnects | Everything else |

A proposal approved before a disconnect does not run: execute resolves the connection
at the moment it runs, finds none, returns `connection_required`, and calls no
provider. The approval is kept, so after reconnecting the user approves again and the
run continues under the same run ID.

## 12.6 Tests (Planned)

Two test users: each connects, and neither can use the other's connection; a mismatched
or replayed state stores nothing; a stored token is not readable without the key;
refresh saves the replacement token; `invalid_grant` turns into `needs_attention`;
disconnect deletes the tokens, calls the provider's revoke, and stops an approved
proposal from writing; reconnect then approve completes the run. Each test also sends
a valid request as a control.

# 13. User isolation (Darsh to confirm)

* Every table row that belongs to a user carries the user ID, and every query filters
  by the session's user. Another user's conversation, proposal, approval or connection
  ID returns 404, the same as an ID that does not exist.
* Storage paths are always prefixed with `/users/<user ID>/` by the API; a path from
  a request or the model cannot leave that prefix.
* Provider clients are built per request from the requesting user's connections only.
* The one shared query is the model budget's token count, which returns only times
  and counts (section 8.7).

# 14. Threat model: rows to add to section 3.4

| Resource | Attack | Enforcement | Test and valid control |
|---|---|---|---|
| Provider connection | Send a victim a callback link carrying the attacker's code, or replay an old callback | One-use state bound to the user and session that started it; PKCE verifier; challenge deleted before the exchange | A mismatched or replayed state stores nothing. The user's own flow stores the connection |
| Stored provider tokens | Read the database or a backup | Tokens encrypted with a key held only in the API's environment | The row holds no plaintext token. With the key, the API's client works |
| Another user's provider account | Pass another user's list ID, or call for data without a connection | Connections are found by the session's user only; a Trello list must be visible to the user's own token; no fallback to a shared account | User A cannot set user B's list and gets `connection_required` without a connection. A's request with A's connection succeeds |
| Approved write after disconnect | Approve, disconnect, and let the execution run anyway | Execute resolves the connection when it runs | Zero provider calls after disconnect. Reconnect, approve again, and it completes once |
| Tokens in model context or logs | Prompt the agent to reveal credentials; read logs | Tokens never leave the API; callback query strings kept out of access logs | Inspect prompts, run records and logs in the test run: no token or code appears |

# 15. Deploying the product (Debasmith to fill)

Status on 2026-11-25: the storage service deploys from `main` and `dev`; the meeting
services are not deployed yet. To record here: host names, how the interface, agent and
API share one origin (the session cookie is host-only, so all three must be reachable
under `PUBLIC_ORIGIN`), the database host, where secrets and the token encryption key
live, the deploy pipeline and smoke check, and the kill switch.

---

# Draft for 8.8 Code versus model decisions (Vikram to check)

| Decided by the model | Decided by code |
|---|---|
| Reading the request: which meeting, which day and time, how long | Who the user is (from the session) |
| Whether to ask a clarifying question | Which tools exist and what each may do |
| The meeting title | Validating every tool argument before it runs |
| Which open issues go on the agenda, and in what order | Requiring an approval of the exact proposal before any write |
| How to summarise what happened | The order of the writes, retries, and what happens on a failure |
| | Limits on steps, time, tokens and requests |
| | The outcomes reported to the user (from the providers' answers) |

The model can be wrong about anything in the left column, and the user sees and can
reject it on the proposal card. Nothing in the right column depends on the model.

# Revision notes, 2026-11-25 (to add above the 2026-11-23 notes)

Added sections 9 to 15 for Milestone 2: the product's components, one scenario traced
from identity to verification, sign-in and sessions, provider connections, user
isolation, threat-model rows for connections, and the product's deployment (to fill).
Drafted 8.8.
