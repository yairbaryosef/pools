# Pool Server Data Flows

The default local persistence target for every flow is SQLite. Repository adapters use explicit relational tables, parameterized queries, and primitive string identifiers; the browser never accesses SQLite directly.

## 1. Google sign-in

```text
browser -> /auth/google/start -> Google authorization
Google callback(code,state) -> verify state + PKCE + issuer + nonce
code -> Google token endpoint -> verify ID token claims
verified (issuer, subject, email) -> upsert user -> create hashed session
session cookie -> browser redirect -> authenticated API request
```

Email is an account attribute for display and invitation matching. The immutable Google issuer and subject identify the account.

## 2. Pool group creation and entry

```text
authenticated user -> POST pool group -> group + admin membership transaction
admin -> add member by verified email -> membership transaction
member -> list groups -> only active memberships returned
member -> enter group -> group membership checked server-side
```

The client cannot choose an admin role or establish membership using a group header.

## 3. Pool lifecycle

```text
admin creates -> draft
admin edits question/options -> draft
admin opens -> open; members may answer
member submits one option -> answer receipt; has_answered=true
admin closes -> closed; aggregate results become visible
```

Every transition checks group membership, actor role, current state, and row ownership. Invalid transitions are conflicts and do not create success audit events.

## 4. Answer submission

1. Authenticate the session and resolve active membership.
2. Resolve the pool by both group ID and pool ID; return generic 404 if inaccessible.
3. Lock or atomically validate that the pool is `open`.
4. Validate the option belongs to this pool.
5. Insert `(pool_id, user_id)` exactly once.
6. Write an audit event without exposing the selected option in ordinary logs.
7. Commit and return a non-sensitive receipt.

## 5. Results

Results are calculated from committed answers only after the pool is `closed`. Before closure, the API returns `POOL_NOT_CLOSED` and no counts. Aggregate results are visible to active group members; individual respondent identity is never returned.
