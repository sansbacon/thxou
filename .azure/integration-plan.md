# Integration hand-off

## Backend
- Project: repository root
- Run: `.venv\Scripts\python app.py`
- Port: 5000
- Build: `.venv\Scripts\python -m pytest tests/unit`
- Health: `GET /api/health`

## Frontend
- Project: `thxou/`
- Dev: `.venv\Scripts\python app.py`
- Build: none (server-rendered Jinja)
- API seam: `thxou/supabase_gateway.py`
- Mock files to delete: none; no mock datasets or preview switcher

## API routes
- GET `/api/health`
- GET `/`, `/sign-in`, `/profile`, `/contests/new`, `/c/<id>`, `/c/<id>/leaderboard`
- POST `/auth/otp/request`, `/auth/otp/verify`, `/auth/refresh`, `/auth/logout`
- POST `/profile`, `/contests`, `/c/<id>/ballot`, `/c/<id>/questions/<question_id>/resolve`
- GET `/api/contests/<id>/leaderboard`

## Database
- Supabase PostgreSQL via PostgREST; migration: `supabase/migrations/0001_initial.sql`
- Runtime env: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`
- Apply migration with a separate trusted migration credential. No seed data.
- RPCs: `upsert_my_profile`, `get_contest_invitation`, `list_my_contests`, `get_leaderboard`

## Services
- Essential: Flask/Vercel, Supabase PostgreSQL Data API, Supabase Auth, Twilio, Cloudflare Turnstile
- Enhancement: polling (manual refresh remains available)
