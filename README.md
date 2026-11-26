# thxou
Thanksgiving over/under contest

## Private event setup (temporary shared-code mode)

1. Apply migrations with a trusted database migration credential (never a
   browser key or service-role key in this app):
   - **Existing database where `0001_initial.sql` is already applied:** apply
     `supabase/migrations/0002_event_ready.sql` once through the Supabase SQL
     Editor or your normal migration runner.
   - **Fresh database:** apply `0001_initial.sql`; it includes the same current
     function definitions. Then mark/apply `0002_event_ready.sql` according to
     your runner (it is idempotent and safe to run after `0001`).
   The migration replaces RPC functions and grants only. It creates no users,
   contests, ballots, results, seed data, or secrets.
2. In **Supabase Dashboard → Authentication → Sign In / Providers → Anonymous
   Sign-Ins**, turn **Allow anonymous sign-ins** **ON** and save.
   [Supabase's settings link and documentation](https://supabase.com/docs/guides/auth/auth-anonymous).
   If Auth CAPTCHA protection was previously enabled, turn **Enable CAPTCHA
   protection** **OFF** under Authentication's **Bot and Abuse Protection**
   for this temporary mode; the app does not submit a CAPTCHA.
   No phone provider, Twilio account, or Turnstile key is required.
3. Copy `.env.example` to an untracked `.env`. Supply `SUPABASE_URL`,
   `SUPABASE_PUBLISHABLE_KEY`, a strong random `FLASK_SECRET_KEY`, and a private,
   nonempty `FAMILY_ACCESS_CODE`. Never put the real passcode or Flask secret in
   `.env.example`, source control, URLs, logs, or screenshots. The app refuses
   family login and reports degraded health without the passcode configuration.
4. Install and start locally (Flask loads `.env` through python-dotenv):
   ```text
   python -m pip install -r requirements.txt
   python -m flask --app app run
   ```
   Open `http://localhost:5000`. For the existing Vercel app, set these same
   variables in its server environment, set `APP_BASE_URL` to the exact HTTPS
   origin (no trailing slash), `APP_ENV=production`, and `COOKIE_SECURE=true`.
   No worker, local state store, service-role key, or additional runtime is needed.

Guests enter the shared code, their name, and a unique username. Flask checks
the passcode with a timing-safe comparison, obtains a Supabase anonymous session,
and calls `upsert_my_profile` using that user's access token. Existing schema,
RLS, RPC authorization and `auth.uid()` ownership are unchanged. No phone
numbers are collected or sent. The existing HttpOnly auth cookies and
refresh/logout endpoints are retained. The sign-in form reuses a valid session,
or refreshes it when possible, rather than creating a new identity on each retry.
Username conflicts and dependency failures appear on the form; retry in the
same browser if a profile write fails.

### Event limitations and stronger authentication later

- Stay in the same browser/device and keep cookies. Signing out or losing the
  session loses the account; entering the same username does **not** recover it.
  If access expires, revisit sign-in to refresh the existing session. Contact
  the host if the refresh session is no longer valid.
- This is a trusted, small-group compromise, not strong private-event access
  control: Supabase's public anonymous-signup API can bypass the Flask passcode.
  Anonymous users have the `authenticated` database role. Do not use this mode
  for sensitive data or valuable prizes; keep Supabase Auth rate limits enabled.
  Server-side signup calls may share an egress-IP rate limit; check
  **Authentication → Rate Limits** against the expected event size.
- Rotating the shared code stops new Flask logins, not existing Supabase
  sessions. Do not enable request-body or auth-header logging.
- After the event, restore verified authentication (for example, Supabase phone
  OTP with an SMS provider and CAPTCHA). Link a verified identity to each
  existing anonymous user while their session is valid to preserve their UUID,
  profile and ballots; do not identify/reassign accounts by username alone.
  Supabase's anonymous-user documentation covers manual identity linking.
  Re-enable CAPTCHA and provider abuse controls, test recovery and migration,
  then disable anonymous sign-ins. The previous OTP adapter is in Git history;
  its routes are intentionally removed from the active application.

## Validation

```text
python -m pytest tests -q
```

On this workstation use
`C:\Users\EricTruett\miniconda3\envs\dia\python.exe`.
Tests use isolated HTTP mocks, not real signups or database rows. For a live
check after configuring Supabase, open `/api/health` (configuration check only),
sign in from `/sign-in`, verify `/profile` contains the submitted details,
then reload `/` and verify the empty contest list. A live signup creates a real
Auth user/profile; run it only against the intended event or test project.
