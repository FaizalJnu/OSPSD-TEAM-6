# Issue (open first; the PR closes it)

Title: [Feature]: Store provider connections and build each user's providers from them

## Problem / Motivation
A signed-in user can read documents, but the API cannot reach their own Trello or
Google Calendar: `USER_PROVIDERS=disconnected` leaves the tracker and calendar
unavailable, and nothing may fall back to the team's test accounts. Each user's
provider access has to be stored safely and used only for that user.

## Proposed Solution
- Tables for provider connections and the one-use challenges that create them (migration 0005).
- Tokens encrypted with a key that lives only in the API service's environment.
- A store with every query scoped to one user, and a Google refresh that runs one at a
  time and saves the replacement token before use.
- `USER_PROVIDERS=connections`: each user's Trello comes from their own token and chosen
  list (Team 4 v1.1.0 takes them as arguments).

## Acceptance Criteria
- [ ] No plaintext token in the database; a token copied into another user's row does not open
- [ ] User A's request never uses User B's connection or the team's test account
- [ ] A challenge works once, for the same user, session and provider, before it expires
- [ ] An expiring Google token is renewed once, even with two requests at the same time; a revoked grant marks the connection as needing attention
- [ ] Migrations upgrade and downgrade on SQLite and Postgres

## Additional Context
Follow-up issues: the OAuth flows and `/v1/connections` endpoints (Google: code with
PKCE; Trello: OAuth 1.0a), the calendar builder once Team 5's credentials change is
pinned, and the interface's connections screen (Prateek).

---

# Pull request

Title: Store provider connections and build each user's providers from them

## Which issue does this PR close?
Closes #

## Problem and resulting behavior
The user API could not reach a signed-in user's own Trello or Google Calendar.
With `USER_PROVIDERS=connections` it now builds each user's Trello from that user's
stored connection, and returns `503` "Connect your issue tracker first." to a user
without one. It never uses the team's test account.

## Approach and why
- **Encrypted, not hashed:** the API must recover tokens to call the provider. Fernet,
  key from `CONNECTION_TOKEN_KEY`, kept out of the database. Each value is sealed with
  its user, provider and column, so a ciphertext copied into another row fails to open.
  Several comma-separated keys allow rotation.
- **One row per user and provider:** reconnecting replaces the tokens and clears
  "needs attention".
- **Challenges** keep only the state's SHA-256 and are bound to the user, the session and
  the provider; a mismatch leaves the real user's challenge usable.
- **Refresh** holds an in-process lock and a row lock, rereads the row, and saves the
  new token before returning it, so two requests renew once. Google's `invalid_grant`
  marks the connection as needing attention; Google being unreachable keeps the stored
  token for that request.
- **Calendar** stays unavailable in this mode until Team 5's package takes credentials;
  the resolver takes the builder as an argument so it plugs in without changes.
- New direct dependency: `cryptography` (already installed through google-auth; now
  declared because we import it). Team 4 pin moved to v1.1.0 for its constructor arguments.

## What changed
- `db/tables/connections.py`, migration `0005`: `provider_connections`, `connection_challenges`
- `token_cipher.py`: sealing and opening tokens with the key from the environment
- `db/connection_store.py`: connections and challenges, scoped by user; refresh
- `api/provider_tokens.py`: renews a Google access token; errors carry no response body
- `api/providers.py`: `connections` mode and `ConnectionResolver`; existing modes unchanged
- `api/user_api.py`: builds the store when the mode is `connections`
- `factories.py`: `build_user_tracker`; the demo's Trello builder passes its settings in
- `pyproject.toml`, `uv.lock`: `cryptography`; Team 4 v1.1.0
- `.env.example`, `README.md`: the new settings and modes

## How it was verified
- `uv run ruff check .`, `ruff format --check`, `mypy` (strict, src and tests): clean
- `uv run pytest`: 475 passed (39 new in `tests/test_connections.py`)
- `uv run pytest -m postgres` against Postgres 17: 3 passed (migration 0005 up, down, schema match)
- Breakage checks: removing the session binding, the refresh lock, or the row binding of
  ciphertexts each makes a test fail.

## Status
- What works: storage and use of connections; Trello per user.
- What remains: OAuth flows and `/v1/connections` endpoints (Faizal); calendar builder
  after Team 5's change is pinned (Faizal); connections screen (Prateek).
- Blocked on: the Google web client and redirect URI; Team 5's credentials change.

## AI assistance
Written with the help of Claude Code. I reviewed every line and can explain it.
