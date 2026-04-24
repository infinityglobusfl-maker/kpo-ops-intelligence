# KPO Ops Intelligence

KPO Ops Intelligence is a niche B2B SaaS dashboard for accounting KPO managers in India. This project now runs as a single FastAPI application that serves both the API and the manager dashboard UI, which makes local running and Railway deployment much simpler.

## What Is Included

- Manager login flow
- Daily ops board with one-click status updates
- Client utilisation view
- 30-day deadline calendar
- Reviewer bottleneck alerts for tasks stuck over 24 hours
- Task creation form
- Teams-ready adaptive card endpoints
- Railway-ready deployment packaging with `Dockerfile` and `railway.toml`

## Local Run

From the project root:

```powershell
.\start-backend.ps1
```

Then open:

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/docs`

## Demo Login

The built-in manager login is:

- Email: `admin@kpoops.local`
- Password: `demo1234`

You can override these in `backend/.env` with:

```env
DEMO_MANAGER_EMAIL=your-email
DEMO_MANAGER_PASSWORD=your-password
DEMO_MANAGER_TOKEN=your-demo-token
```

## Supabase Behavior

The app reads from the Supabase project configured in `backend/.env`.

If that project is empty, the app automatically uses demo fallback data so the product still works end to end.

If you want to force real-data-only mode:

```env
USE_DEMO_FALLBACK=false
```

## Key Endpoints

- `GET /health`
- `POST /auth/login`
- `GET /auth/me`
- `GET /tasks/today`
- `GET /clients/utilisation`
- `GET /deadlines/upcoming`
- `GET /ops/alerts`
- `POST /tasks`
- `PATCH /task/status/{token}/{new_status}`
- `GET /teams/card/{token}`
- `POST /teams/action`

## Production Deployment

This repo is prepared for Railway deployment as a single service.

Files included:

- `Dockerfile`
- `railway.toml`

Expected environment variables on Railway:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `USE_DEMO_FALLBACK=false` for live production once data is ready
- optional demo auth variables if you want a fallback admin login

## What Still Needs External Account Work

These pieces cannot be fully completed from this local session because they require your cloud accounts and account-side approvals:

- Creating Railway production service and environment variables
- Connecting GitHub repo to Railway
- Railway domain / custom domain setup
- Seeding the live Supabase project if it is still empty
- Creating real Supabase Auth users
- Microsoft Teams bot or Power Automate registration on the Microsoft side

## Current Status

You now have a production-structured local app, but not yet a fully live internet deployment. The codebase is ready; the remaining work is account-side release setup.
