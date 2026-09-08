# Hunter Watchtower deployment contract

Hunter Watchtower is a standalone service. Do not run it inside the Empty Chair customer web service.

## Container

Build from the repository root:

```bash
docker build -f hunter/Dockerfile.watchtower -t hunter-watchtower .
```

The container listens on port `8080`.

## Required configuration

- `WATCHTOWER_API_TOKEN`: long random bearer token used by the control API.
- Persistent volume mounted at `/data`.

Recommended:

- `WATCHTOWER_HEADLESS=true`
- `WATCHTOWER_POLL_SECONDS=3`
- `WATCHTOWER_SETTLE_SECONDS=4`

The persistent Chromium profile lives at `/data/chromium-profile` and the local job ledger lives at `/data/watchtower.sqlite3`.

## API

Public health check:

- `GET /healthz`

Bearer-token protected control endpoints:

- `GET /v1/status`
- `POST /v1/jobs` with `{ "username": "artistname" }`
- `POST /v1/jobs/batch` with `{ "usernames": ["artist1", "artist2"] }`
- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs?limit=50`

## Authentication rule

The service never accepts Instagram usernames/passwords over its API and never returns cookie values.
The production Chromium profile must be authenticated through Instagram's legitimate login/approval flow. If Instagram invalidates the session or requests verification, Watchtower reports `authenticated=false` and observation pauses until the account is legitimately reauthenticated.

## Isolation

Watchtower is intentionally separate from Empty Chair. Chromium crashes, Instagram auth failures, and collector maintenance must not affect customer-facing Empty Chair traffic.
