# Project Plan

**Status**: Approved
**Created**: 2026-11-25
**Mode**: NEW

**2026-11-26 temporary event override**: The user approved server-checked
`FAMILY_ACCESS_CODE` with Supabase anonymous authentication, name/username profile
upsert, and existing auth cookies. No phone collection, Twilio, or Turnstile in
the active flow. Preserve the PostgreSQL schema/RLS/RPC actor model. README.md
documents current setup and limitations; phone-OTP requirements below describe
the longer-term design, not today's prerequisites.

---

## 1. Project Overview

**Goal**: Build thxou: a lean Python web app for link-only Yes/No prediction contests, complete ballots, progressive result resolution, and private participant leaderboards. The project is designed so that every module is independently testable.

**App Type**: Full-stack SSR

**API Login**: Yes

**Mode**: NEW

**Deployment Plan**: No deployment plan found. Deploy one Flask application on Vercel, with PostgreSQL and authentication on Supabase. No Azure resources.

**Requirements baseline**: The user's confirmed decisions in the 2026-11-25 request supersede older `needs_input` and inferred defaults in `.azure/requirements.json`. This document records the final proposed requirements; no further product questions are blocking. Architectural defaults below remain subject to plan approval.

### Confirmed product rules

- Profiles contain a name, unique username, and private phone number.
- Every contest has a creator, creator-defined Yes/No questions, one creator-set deadline, and a generated non-guessable stable URL.
- Contests are link-only: no public discovery or search. A link permits the entry flow, not access to standings.
- A participant joins by successfully submitting one complete ballot before the deadline. Merely visiting a link does not join.
- There is one ballot per user per contest. The entire ballot can be revised until the deadline; partial submissions are rejected.
- The creator may participate through the same ballot flow and is subject to the same deadline.
- Questions can be added, edited, reordered, or deleted only before the first successful participant submission, including the creator's own submission.
- The creator resolves questions over time. Each correct answer earns one point; unresolved questions and incorrect answers earn zero.
- Scores update after each resolution. Ties share rank. Standings are visible only to participants and the creator.
- Sign-in uses Supabase Auth phone OTP and a configured SMS provider.

### Lean defaults and lifecycle

- States are **draft → open → closed/resolving → completed**. Only publication is explicitly stored; the deadline and resolved-question count determine subsequent states. No scheduler is needed.
- Drafts are creator-only. Publishing requires a future deadline and 1–30 questions. Published links remain the same through completion.
- Contest title: 1–120 characters; optional description: at most 1,000; question text: 1–300. All are plain text.
- Before anyone joins, the creator may edit title, description, deadline, timezone, and questions. Freeze all of them on first join to avoid changing the bargain after entry.
- Resolution is allowed only at or after the deadline. There is no early locking or early resolution.
- Each result is final once recorded; confirmation explicitly warns the creator. Same-value retries succeed without duplicate work; attempts to change a result return conflict. Result corrections, voiding questions, and reopening are excluded from MVP.
- Completion means every question has a result, even if there are no participants. A contest with unresolved questions remains resolving indefinitely.
- Shared ranking uses competition ranks: `1, 1, 3`, not `1, 1, 2`. Alphabetical username ordering stabilizes display within ties without breaking ties.
- Start with a small-group limit of 100 participants per contest and 20 noncompleted contests per creator. These are configurable guardrails, not paid tiers. Revisions do not consume another seat.
- No self-service contest deletion or leaving after publication/joining. This prevents bypassing question locks and preserves shared URLs.

### Explicit MVP exclusions

Public discovery; invitations or access allowlists; teams; comments/chat; money, prizes, betting, payments; question types beyond Yes/No; partial saved ballots; per-question deadlines; answer changes after close; late entry; manual score adjustments; result corrections/appeals; automated outcomes; background jobs; push/email/SMS contest notifications; WebSockets or Supabase Realtime; uploads/avatars; social sign-in; administrative UI; custom domains as a prerequisite; export; offline mode; native apps; phone-number changes and self-service account deletion/recovery.

Provide a manual operator contact for account/privacy requests. Phone-only authentication is inappropriate for valuable prizes because phone numbers can be reassigned or compromised.

---

## 2. Backend — Flask

| Component | Technology |
|-----------|-----------|
| **Language** | Python |
| **Runtime** | CPython |
| **Framework** | Flask |
| **Package Manager** | pip |
| **Test Runner** | pytest |
| **Mocking Library** | unittest.mock and HTTPX MockTransport |
| **Test Command** | `.venv\Scripts\python -m pytest` |
| **Orchestration** | docker-compose |

**Architecture decision**: One Flask WSGI application renders Jinja templates, handles forms, and exposes one leaderboard JSON endpoint. Small same-origin JavaScript handles refresh and form enhancement. There is no SPA, separate frontend deployment, Node production runtime, worker, or persistent server process.

Flask is simpler here than an API-first FastAPI/SPA split and avoids Django's additional authentication/admin machinery. Vercel runs the application as a stateless Python Function. Use its Flask framework support and a root `app.py` exposing `app`; do not run Gunicorn or Flask's development server in production.

**Data access decision**: Flask uses HTTPX to call Supabase Auth and the PostgreSQL Data API over HTTPS. Forward the verified user's access token explicitly to PostgREST; use SQL RPCs for transactional writes. This avoids direct PostgreSQL connections, serverless connection exhaustion, an ORM, and an additional pool configuration. Database constraints and migrations remain ordinary PostgreSQL.

- Create a request-local authenticated API wrapper; never put a user's token into a shared mutable client.
- Prefer parameterized PostgREST filters/RPC arguments; never build SQL from user input.
- All writes described below execute in database transactions. Browser code does not write database tables directly.
- Use finite HTTP timeouts, for example 3 seconds to connect and 10 seconds overall. Return recoverable 503 errors on dependency failure; never claim a ballot was saved without confirmed success.
- No local files, SQLite, in-memory sessions, queues, or in-process rate limits as durable state. Instances may disappear after any request.
- Template routes, authentication adapter, application rules, and persistence adapter are separate testable modules, not separate deployed services.

### Authentication, privacy, and authorization

- Use Supabase Auth phone OTP with **Twilio** as the initial supported SMS-provider default. Provider account, sender registration, permitted destination countries, and budget are deployment prerequisites, not unresolved architecture choices.
- Normalize phone numbers to E.164 with a country selector and server validation. Supabase Auth owns the verified phone and OTP lifecycle. Never store OTPs or duplicate phone numbers in contest/profile tables.
- The profile page composes the user's own `auth.users` identity phone with their profile record. Display a masked phone by default. Other users see only name and username, never phone, email, auth metadata, or tokens.
- Use Supabase's server-side OTP verification and user-validation endpoints. Verify the current user before protected requests; never trust browser-supplied user IDs or an unverified JWT payload.
- Store access/refresh tokens in separate Secure, HttpOnly, SameSite=Lax, Path=/ cookies without a Domain attribute; use the `__Host-` prefix in HTTPS environments. Tokens never go into URLs or localStorage. Use documented refresh/rotation behavior, serialize refresh in a browser tab, and test concurrent refresh within Supabase's reuse interval. Supabase remains the session authority.
- On expired access, refresh through the server and replace cookies; on invalid/revoked refresh, clear cookies and require OTP again. Logout revokes the current Supabase session and clears both cookies. Do not promise instant revocation of already-issued JWTs; select a short supported access-token lifetime.
- Require CSRF tokens and same-origin Origin/Referer validation for every state-changing request, including OTP request/verification and logout. Redirect targets must be allowlisted relative paths.
- Enable RLS on every exposed application table. Grant no anonymous table access and no direct table mutation privileges to normal authenticated clients. Enforce writes only through authorized RPCs; hiding buttons or restricting Flask routes is not sufficient.
- RPCs derive the actor from `auth.uid()`, reject missing identities, and enforce ownership, membership, lifecycle, and validation again in PostgreSQL.
- Where elevated RPC privileges are necessary, use tightly scoped `SECURITY DEFINER` functions, a fixed safe search path, schema-qualified references, a non-login owner, no dynamic SQL, and revoke default PUBLIC/anonymous execution. Grant only required functions to `authenticated`. Keep internal membership helpers out of exposed API schemas.
- An authenticated user with a published contest UUID can call a narrow invitation RPC returning title, deadline, creator name/username, questions, and entry availability. It returns no participant list, ballots, or leaderboard. It does not support listing contests by arbitrary filters.
- Draft data belongs only to its creator. The home page lists only contests created or joined by the viewer.
- Participants read their own ballot only; creators cannot inspect other users' individual picks, even after closing. A joined participant or creator can read aggregate standings and resolved results. Other profiles are projected only as part of these authorized responses; there is no profile directory.
- Nonmembers cannot get results, scores, or participant identities by calling PostgREST/RPCs directly. Use private/no-store cache headers on authenticated HTML and JSON.
- Escape all user content with Jinja autoescaping; enforce length limits; set CSP, `frame-ancestors 'none'`, `nosniff`, and `Referrer-Policy: no-referrer`. Use `noindex, nofollow`, no public sitemap, and no third-party analytics on contest links. A UUID link is not a substitute for authorization.
- Logs must redact OTPs, tokens, cookies, authorization headers, full phone numbers, and ballot bodies. Do not log complete invitation URLs. Record request IDs, error classes, and safe operational counters only.

### SMS abuse and cost controls

- Enable Supabase Auth CAPTCHA protection, using Cloudflare Turnstile on the send-code flow; enforce it at Supabase's public Auth endpoint, not only Flask, so direct calls cannot bypass it.
- Configure Supabase's supported OTP send cooldown and verification limits: start with at least 60 seconds between sends to the same phone, a short supported OTP expiry (target 5 minutes), and finite verification attempts. Verify the provider's current supported settings before launch.
- Use Supabase's native SMS-send and verification rate limits, with a conservative project-wide send allowance sized for the gathering. Confirm whether each configured limit is per phone, IP, or project; do not assume it covers all three.
- When proxying Auth calls, configure Supabase's supported end-user-IP forwarding only if it is available safely for the chosen key/configuration. Trust only Vercel-validated forwarding information. Test the observed limiting behavior; do not assume Supabase automatically sees the visitor rather than the function's egress IP.
- A Vercel WAF rule on OTP routes is optional defense in depth, not the main boundary: clients can reach Supabase Auth directly. CAPTCHA, provider-level destination restrictions, fraud protection, Supabase Auth limits, and billing controls must also bound that path.
- Allow only explicitly configured launch countries. Enable Twilio fraud protection where supported, a daily usage alert, and a tested provider/account sending cutoff or operator kill switch. An alert alone is not a hard spending cap.
- Use generic send/verification responses to avoid account enumeration; keep resend countdowns helpful without confirming whether an account exists.
- Use managed enforcement rather than building a separate throttle datastore or rate-limit service. Never rely on per-process memory for limits. Do not send real SMS in CI or arbitrary Vercel previews.

### PostgreSQL schema

All timestamps are `timestamptz`. Application UUID primary keys use cryptographically random UUIDv4 values generated in PostgreSQL. No sequential contest IDs or mutable slugs.

| Table | Essential columns and constraints |
|-------|-----------------------------------|
| `auth.users` (Supabase-managed) | Identity UUID, verified phone, authentication/session metadata. Never expose through application APIs. |
| `profiles` | `user_id` PK/FK to auth identity; `name`; normalized lowercase `username` with UNIQUE constraint; `created_at`, `updated_at`. Username: 3–24 ASCII letters/digits/underscore, starts with a letter, reserved names rejected. Name: 1–80 characters. Phone is intentionally absent. |
| `contests` | `id` UUID PK; `creator_id` FK profiles; `title`, optional `description`; `deadline_at`; `creator_timezone` IANA name; nullable `published_at`, nullable `first_joined_at`; timestamps. Creator and ID immutable. Profile required before creation. |
| `questions` | `id` UUID PK; `contest_id` FK; `position`; `text`; UNIQUE `(contest_id, position)` and `(contest_id, id)`. At least one question on publication. No result column exposed to invitation readers. |
| `ballots` | Composite PK `(contest_id, user_id)`; FKs to contest/profile; `submitted_at`, `updated_at`; positive integer `version`. This row is also membership; no separate join table. |
| `answers` | `contest_id`, `user_id`, `question_id`, non-null boolean `choice`; PK `(contest_id, user_id, question_id)`; composite FKs to ballot and `(contest_id, question_id)` in questions. |
| `question_results` | `question_id` PK; `contest_id`; non-null boolean `correct_answer`; `resolved_by`; `resolved_at`; composite FK to the question in that contest. Absent row means unresolved; `false` means No, not unresolved. Resolver must be creator, enforced in RPC. |

Indexes: creator + creation date on contests; user + contest on ballots for “My contests”; contest + position on questions; contest-scoped answer/result indexes for aggregate scoring. Validate query plans with the configured maximum contest size.

No stored score/rank columns, leaderboard cache, uploaded files, or datastore beyond Supabase PostgreSQL. Avoid database cascading deletes that silently erase contest history; manual privacy deletion must explicitly preserve or anonymize required historical records.

### Transactional rules and concurrency

All contest-mutating RPCs first lock the same contest row (`FOR UPDATE`) so question edits, first join, deadline checks, ballot revisions, and resolution cannot race.

1. **Edit/publish**: verify creator, lock contest, require `first_joined_at IS NULL`, validate all fields, then commit changes together. Question deletion/reordering never leaves a published contest with zero questions.
2. **Submit/revise**: lock contest; check publication, complete profile, capacity on first entry, and database wall-clock time **after acquiring the lock**. Accept only when `clock_timestamp() < deadline_at`; request arrival time and transaction-start `now()` do not grant a grace period.
3. Require exactly one boolean answer for every current question and no foreign/duplicate question IDs. Atomically insert membership plus all answers, or replace all answers on revision. Set `first_joined_at` once and never clear it.
4. Revisions carry an expected ballot `version`; reject stale concurrent edits with 409. If an identical payload is retried after an ambiguous successful response, return the already-saved ballot without changing scores, membership, or version. A different stale payload is a conflict. No new write is allowed at/after deadline.
5. **Resolve**: verify creator, lock contest, require database time at/after deadline, verify question belongs to contest, and insert one immutable result. All resolution writes are serialized; repeated identical values are idempotent and conflicting values return 409.
6. **Leaderboard**: authorize joined participant or creator, then use one SQL statement/snapshot: begin from every ballot; left join answers/results; sum matching resolved booleans; use `RANK() OVER (ORDER BY score DESC)`. Preserve zero-score entrants and return resolved count, total questions, phase, and database `as_of` time consistently.

### UTC and creator-local time

- Capture a local deadline and an IANA timezone, defaulted from the creator's browser but explicitly displayed and editable before first join.
- Resolve that pair server-side with Python `zoneinfo`; reject nonexistent DST times. For ambiguous times require selection of the intended UTC offset in the deadline form rather than silently guessing.
- Store the resulting instant in `deadline_at` and the IANA name separately. Store all events as UTC instants and return ISO 8601 UTC values in machine responses.
- Display deadlines and resolution times in the stored creator timezone for everyone, labeled with zone and offset. An optional viewer-local secondary timestamp is not required.
- Deadline equality is closed. A displayed countdown is informational; PostgreSQL decides whether a write is permitted.

---

## 3. Frontend — Web App

| Component | Technology |
|-----------|-----------|
| **Language** | JavaScript |
| **Framework** | Server-rendered Jinja HTML with progressive enhancement |
| **Package Manager** | pip for shared app; vendored pinned Pico.css, no Node build |
| **Test Runner** | pytest with Playwright Python |
| **Mocking Library** | unittest.mock and Playwright route interception |
| **Test Command** | `.venv\Scripts\python -m pytest tests/e2e` |

**Live behavior**: An authorized open leaderboard polls its same-origin JSON endpoint every 5 seconds while the tab is visible. Refresh immediately on return to the tab and after the creator resolves a result. Under healthy dependencies, another viewer sees a committed result within 10 seconds. This is near-live polling, not a WebSocket guarantee.

Stop polling on completion or sign-out; back off on failures, show the last successful timestamp and “Updates paused—retry,” and never replace a valid score with zero on error. Keep semantic table markup and announce refreshed standings politely without moving keyboard focus. With JavaScript disabled, manual page refresh works.

---

## 4. Services Required

| Azure Service | Role in App | Environment Variable | Default Value (Local) | Classification |
|---------------|-------------|----------------------|-----------------------|----------------|
| None — Vercel Python Functions | Flask HTML/forms/JSON and static assets | `APP_BASE_URL`, `APP_ENV`, `FLASK_SECRET_KEY` | `http://localhost:5000`, `development`, secret supplied locally | Essential |
| None — Supabase PostgreSQL Data API | Profiles, contests, ballots, transactional RPCs | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Separate nonproduction project; no hardcoded credentials | Essential |
| None — Supabase Auth | Phone verification, managed abuse limits, and sessions | Same Supabase project | Nonproduction Auth configuration | Essential |
| None — Twilio | Deliver Supabase phone OTP | Provider secrets configured in Supabase, not browser/Vercel source | Approved test-phone configuration | Essential for new sign-ins |
| None — Cloudflare Turnstile | OTP bot challenge | `TURNSTILE_SITE_KEY`; secret in Supabase Auth settings | Registered local/test configuration | Essential for public OTP sending |

The service-table heading is a planning-view label; **no Azure deployment is proposed**. Polling is an enhancement: manual refresh works if browser polling fails. Auth, PostgreSQL, and the Python host fail closed. SMS outages prevent new sign-ins, but existing valid sessions may continue.

### Deployment configuration

- Use one Vercel project linked to `sansbacon/thxou`, repository root as project root, Flask framework detection, root `app.py`, and a pinned `requirements.txt`. Target CPython 3.12, declare a matching `requires-python` range in `pyproject.toml`, and verify Vercel supports that version at implementation time.
- Include templates and vendored static assets in the deployment bundle. Use Vercel's native Flask routing; do not add a catch-all rewrite or custom build command unless a deployment smoke test demonstrates a need.
- Configure function region close to Supabase. Keep requests short; no live socket servers, cron jobs, background threads, or local durable storage. Function timeout must exceed the application's bounded dependency timeout within the selected Vercel plan's supported limits.
- Set the canonical stable production origin via `APP_BASE_URL`; generate share links as `/c/<uuid>`. Never generate links from an untrusted Host header or a transient preview URL. Preserve the project/domain and database IDs across releases.
- Set environment variables separately for Development, Preview, and Production. A preview must never use the production database or SMS credentials. Use a nonproduction Supabase project and configured test phones; disable real OTP sending for untrusted previews.
- No Supabase service-role key is needed in the deployed application. The normal publishable key is not an authorization secret; RLS and user tokens are the boundary.
- Keep `FLASK_SECRET_KEY` strong and stable across deployments, load all secrets from host secret settings, and commit only variable names/placeholders in a later `.env.example`. Set allowed hosts and correctly configure trusted proxy handling for Vercel.
- Configure Supabase Auth site URL, allowed origins/redirects, phone provider, CAPTCHA, OTP limits, and token lifetimes per environment. Use approved test phone fixtures only in nonproduction.
- Apply versioned SQL migrations through a trusted operator/CI step using a separate migration credential before traffic reaches code that needs them. Do not migrate during function import or every deployment request.
- The app uses HTTPS Data API access, so no runtime PostgreSQL DSN or client pool is required. If migration tooling cannot use the direct Supabase connection, use the dashboard-provided session-pooler endpoint with TLS and certificate verification; never put a migration-owner credential into the app.
- Enable an appropriate Supabase backup policy and test restoration before public launch. Paid backup/PITR, quotas, SMS sender approval, and provider pricing must be checked against selected account plans, not assumed free.
- Add a non-sensitive health check and deployment smoke checks: root page/static assets, sign-in configuration, database schema readiness, protected-route denial, private cache headers, stable contest URL, and an authorized leaderboard read. Do not send real SMS on routine health checks.
- Operational signals: dependency latency/errors, failed ballot/resolution writes, blocked OTP sends, provider cost alerts. Use short log retention and no sensitive request bodies.
- Deploy backward-compatible migrations first; retain the previous Vercel deployment for application rollback. Destructive schema changes require a separate reviewed migration.

---

## 5. Prerequisites

Inventory scanned on 2026-11-25. No packages were installed and no services started. Double-check every ❓ item before implementation; a sandbox probe cannot prove absence.

### Run

| Tool | Service(s) | Installed | Version |
|------|------------|-----------|---------|
| CPython 3.12 with venv | api, web | ❓ | PATH resolves Windows Store alias, not a working interpreter; alternative standard locations unconfirmed |
| pip in selected Python | api, web | ❓ | Unconfirmed; verify using the selected interpreter |
| Git | * | ✅ | 2.56.1.windows.1 |

Vercel and Supabase dashboards/accounts plus a configured SMS provider are external prerequisites. Their CLIs are optional for dashboard-based deployment and are not confirmed installed. Use a separate hosted Supabase development project for the simplest local setup; do not require local Docker for MVP.

### Debug

| Tool | Service(s) | Installed | Version |
|------|------------|-----------|---------|
| Microsoft Edge | web | ✅ | 158.0.4370.33 |
| `ms-python.python` | api | ✅ | 2026.10.0 |
| `ms-python.debugpy` | api | ✅ | 2026.6.0 |

The orchestration metadata does not require generating Docker files: no local emulators are planned. Playwright and its browser binaries are future test dependencies, not claimed installed. Future local commands use the project `.venv`; run Flask locally only during implementation, never during this planning task.

---

## 6. Design System & UI

**Component Library**: Pico.css

**Style Direction**: A friendly, compact gathering scoreboard: warm paper surfaces, cranberry actions, amber result accents, generous tap targets, and a readable leaderboard. Mobile-first single-column pages, not an administrative dashboard.

**Typography**: system-ui, Segoe UI, sans-serif

### Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `primary` | `#8B2439` | Create contest, save ballot, active navigation |
| `accent` | `#A65B00` | Resolved-question and deadline highlights |
| `surface` | `#FFF9F1` | Contest and ballot page background |
| `text` | `#29221F` | Questions, entrant names, scores |
| `muted` | `#6C6059` | Timezone labels, update timestamps, helper text |
| `border` | `#D6C7BA` | Ballot groups and leaderboard dividers |

### Pages

| Page | Route | Purpose | Layout |
|------|-------|---------|--------|
| My Contests | `/` | Landing/sign-in prompt, or created/joined contests | `header, nav, hero, card-list, actions` |
| Phone Sign-in | `/sign-in` | Request and verify OTP in one flow | `header, main, form` |
| My Profile | `/profile` | Name, unique username, private verified phone | `header, nav, form` |
| Contest Editor | `/contests/new` | Create a draft; same template at `/c/<id>/edit` edits/publishes it | `header, nav, form, action-bar` |
| Contest | `/c/<id>` | Invitation, full ballot, own saved picks, and resolved-question status by role | `header, nav, main, form, actions` |
| Standings | `/c/<id>/leaderboard` | Authorized live ranks; creator's result-resolution controls | `header, nav, table, form, actions` |

The editor is hidden/disabled after first join, with a server-enforced explanation. Standings controls show only to the creator and only after closing. Empty, loading, saved, expired, unauthorized, and retry/error states must be designed explicitly. Yes/No controls are radio groups with labels and keyboard support, never preselected predictions.

### Sample Content

Illustrative design/test fixtures only; do not seed production or replace real application data with mock records.

- **My Contests**: “Thanksgiving Table Predictions” — open, 3 questions; “Dessert Forecast” — resolving, 1/3 resolved; “Weekend Watch Party” — completed, 3/3 resolved.
- **Phone Sign-in**: country selector, phone field, “Send code”; subsequent one-time-code field, “Verify code,” and disabled resend countdown. Never show another user's phone.
- **My Profile**: name “Avery Chen”; username `avery`; masked own phone ending `0101`; duplicate-username inline error.
- **Contest Editor**: title “Thanksgiving Table Predictions”; deadline November 26, 2026, 3:00 PM `America/New_York` (UTC−05:00); optional description “Make your picks before dinner.”
- **Contest questions**: “Will dinner begin before 5 PM?” — Avery: Yes; “Will someone bring a second pie?” — Avery: Yes; “Will the game go to overtime?” — Avery: No. At entry, all start unanswered.
- **Standings**, after Q1=Yes and Q2=No: Avery `Yes/Yes/No` → 1 point, rank 1; Morgan `No/No/Yes` → 1 point, rank 1; Jordan `No/Yes/No` → 0 points, rank 3. Q3 is unresolved. Only aggregate scores, not these fixture ballots, are visible to other users.
- **States**: My Contests has a “No joined contests yet” section; Phone Sign-in demonstrates a generic invalid/expired code banner; Standings has an initial skeleton and a separate last-updated/retry state.

---

## 7. Project Structure

Proposed files only; none of these application files are created by this planning task.

```text
thxou/
  app.py                    # Vercel-discoverable Flask app
  pyproject.toml            # Python compatibility and test settings
  requirements.txt          # Pinned runtime dependencies
  requirements-dev.txt      # pytest and Playwright
  .env.example              # Names/placeholders, never credentials
  thxou/
    config.py
    auth.py                 # Supabase Auth and secure session cookies
    routes.py               # HTML/forms/leaderboard endpoint
    services.py             # Testable application policies
    supabase_gateway.py     # Explicit request-scoped user credentials
    validation.py           # Input, usernames, local deadline validation
    templates/
    static/
      pico.min.css
      app.css
      app.js
  supabase/
    migrations/             # Schema, grants/RLS, and atomic RPCs
  tests/
    unit/
    integration/            # Real PostgreSQL/RLS/concurrency checks
    e2e/
  .azure/
    requirements.json
    project-plan.md
```

Do not add `vercel.json` unless Vercel defaults cannot express a verified requirement. No database seed data, infrastructure provisioning, deployment configuration files, migrations, or application code are generated at this stage.

---

## 8. Route Definitions

HTML forms use POST/redirect/GET on success. Validation errors re-render accessible forms; JSON failures use a stable error code and safe message. UI requests redirect to sign-in when needed; the polling endpoint returns 401 rather than HTML.

| # | Method | Path | Description | Request Body | Response Body | Status Codes |
|---|--------|------|-------------|--------------|---------------|--------------|
| 1 | GET | `/api/health` | Non-sensitive readiness | — | `{status}` | 200, 503 |
| 2 | GET | `/` | Landing or own contest list | — | HTML | 200, 503 |
| 3 | GET | `/sign-in` | Phone/OTP form; preserve validated local return path | — | HTML | 200 |
| 4 | POST | `/auth/otp/request` | CAPTCHA-checked, throttled OTP send | phone, captcha token, CSRF | Generic response/form | 200, 400, 429, 503 |
| 5 | POST | `/auth/otp/verify` | Verify code; set secure session cookies | phone, code, CSRF | Redirect or form errors | 303, 400, 429, 503 |
| 6 | POST | `/auth/refresh` | Rotate session via Supabase | CSRF | Empty success or safe error | 204, 401, 403, 503 |
| 7 | POST | `/auth/logout` | Revoke current session and clear cookies | CSRF | Redirect | 303 |
| 8 | GET | `/profile` | Own profile and private phone | — | HTML | 200, 303 |
| 9 | POST | `/profile` | Complete/update own name and username | name, username, CSRF | Redirect or errors | 303, 400, 409 |
| 10 | GET | `/contests/new` | Creator form | — | HTML | 200, 303 |
| 11 | POST | `/contests` | Create draft with initial questions | title, description, local deadline, timezone/offset, questions, CSRF | Redirect to stable contest URL | 303, 400, 409 |
| 12 | GET | `/c/<id>` | Sign-in gate, then authorized invitation/ballot view | — | HTML | 200, 303, 404 |
| 13 | GET | `/c/<id>/edit` | Creator editor before first join | — | HTML | 200, 303, 404, 409 |
| 14 | POST | `/c/<id>/edit` | Atomic metadata/question edit before first join | complete edited contest, CSRF | Redirect or errors | 303, 400, 404, 409 |
| 15 | POST | `/c/<id>/publish` | Publish a valid draft | CSRF | Redirect | 303, 400, 404, 409 |
| 16 | POST | `/c/<id>/ballot` | Join or revise complete ballot | question/boolean pairs, expected version, CSRF | Redirect or errors | 303, 400, 404, 409 |
| 17 | GET | `/c/<id>/leaderboard` | Joined users/creator only | — | HTML | 200, 303, 403, 404 |
| 18 | GET | `/api/contests/<id>/leaderboard` | Authorized polling | — | `{phase, resolved_count, question_count, as_of, standings:[{name,username,score,rank}]}` | 200, 401, 403, 404, 503 |
| 19 | POST | `/c/<id>/questions/<question_id>/resolve` | Creator's final Yes/No resolution after deadline | correct_answer, confirmation, CSRF | Redirect or errors | 303, 400, 404, 409 |

Profile completion is required before creating/submitting, not before viewing an invitation. A syntactically valid but nonexistent ID and an inaccessible draft both return 404. A known published contest may return 403 for nonmember standings. Authorization failures must never contain protected data.

Corresponding database RPCs cover own profile update, own contest list, invitation lookup, own ballot lookup, draft creation/edit/publication, atomic ballot submission, result resolution, and authorized leaderboard reads. These are the same authorization boundary even when invoked outside Flask.

### Testable acceptance criteria

1. **OTP/session**: In a nonproduction Auth project, valid OTP establishes a server-managed session; wrong, expired, replayed, and excessive attempts fail; cookies have the documented flags; refresh/rotation and logout behave correctly. Protected requests with forged/expired credentials fail.
2. **SMS controls**: Missing/invalid CAPTCHA fails both through Flask and direct Supabase Auth. Managed send/verification limits remain effective across function instances; their phone/IP/project scope is verified. Destination restrictions and a provider cutoff are exercised without paid CI messages. No secret/phone/OTP appears in logs.
3. **Profile privacy**: Two concurrent attempts to claim `avery`/`Avery` yield one winner. Other users cannot read the winner's phone via HTML, JSON, table queries, or RPCs.
4. **Stable link**: Publishing produces one UUIDv4 URL; edits permitted before first join and later resolution/redeployment do not change it. No public list/search exposes it. Visiting does not create membership.
5. **Full ballot**: Missing, duplicate, extra, nonboolean, or foreign-contest answers fail atomically. A successful submission creates one ballot with exactly the contest's questions. Retries do not add another participant.
6. **Revision**: Before deadline, a full replacement succeeds; stale differing versions return 409 and preserve the winner. At deadline equality and afterward, new entries and revisions fail, even if the HTTP request arrived earlier.
7. **First join race**: Concurrent edit and first submission serialize. Either the edit commits first and the ballot must match the new question set, or entry commits first and all edits fail. Creator participation also freezes questions.
8. **Deadline/timezone**: A New York 3 PM November 26 deadline stores 20:00 UTC; a summer equivalent accounts for DST. Nonexistent local times fail; ambiguous local times require an offset; a different viewer timezone does not alter the stored instant or creator-local display.
9. **Permissions**: A noncreator cannot edit/publish/resolve using another ID. An authenticated link visitor cannot access standings or other ballots. Joined users can read standings but only their own picks. The nonparticipating creator can read standings and resolve but has no leaderboard row.
10. **Resolution**: Before closing, resolution fails. After closing, creator resolution succeeds once; same-value retries are safe, different-value retries fail, and `No` is scored as a resolved boolean rather than missing data.
11. **Scoring**: All entrants appear, including zero scores. The sample fixtures produce ranks `1,1,3`; when Q3=No, scores become `2,1,1` with ranks `1,2,2`. Repeated reads never double-count a result; all unresolved gives tied zero scores.
12. **Live standings**: Under healthy dependencies, a result committed in one browser appears in another authorized visible tab within 10 seconds. Hidden tabs stop polling; reconnection refreshes; failures display stale status without losing saved ballots or scores.
13. **Direct database/API abuse**: Integration tests use real Supabase authenticated/anonymous credentials, not only mocked Flask authorization. Anonymous table/RPC calls fail; authenticated arbitrary table reads/writes and unauthorized RPC calls fail. No service-role bypass is used by test subjects.
14. **Capacity and outages**: Concurrent last-seat entries cannot exceed the cap; existing participants can still revise. A database outage yields a safe retry error, never a partial ballot or false success. Health checks and logs contain no sensitive data.
15. **Deployment and UX**: Vercel smoke tests verify deep links, bundled templates/static files, isolated preview configuration, private no-store responses, keyboard/mobile forms, clear UTC-offset labels, and usable manual refresh without JavaScript.

Unit tests cover validation, time conversion, response mapping, and scoring examples. Database integration tests prove grants/RLS, atomicity, races, and aggregation in a disposable Supabase environment. Playwright tests cover the end-to-end user journeys with nonproduction Auth fixtures. No tests have been executed during planning.

---

## 9. Next Steps

1. Review and explicitly approve this plan, including the proposed Flask/Data API architecture, five-second polling, immutable results, and small-group limits. Status remains **Planning** until approval.
2. This task is planning only: do not scaffold, implement, deploy, send SMS, provision services, or run a server as part of finalizing the document.
3. After approval and an implementation hand-off, generate the proposed app, versioned schema/RPC/RLS migrations, and tests; integrate against nonproduction Supabase without seed data.
4. Verify the acceptance criteria, including direct Data API authorization and concurrency tests, before configuring production Vercel/Supabase/Twilio.
5. Before public launch, review provider configuration, SMS cost cutoff, privacy/support process, backup restoration, and deployment smoke checks. Human review and validation are required; this is a design, not a claim of implemented security or deployment readiness.
