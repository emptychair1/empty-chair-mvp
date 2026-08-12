# Empty Chair Pilot v1.1

FastAPI application for filling unused tattoo appointments from a studio's existing customer base.

Current pilot capabilities:

- User signup/login/logout
- Signed session authentication
- Password reset email flow
- Per-user shop isolation
- Customer CSV import
- Artist management
- Opening/recovery queue
- Twilio SMS offers
- Resend email offers and transactional email
- Customer claim/decline flow
- Booking flow
- Cancellation recovery
- Pilot readiness and delivery-health reporting
- **Fill Week / Fill Month Autopilot campaigns**
- Controlled appointment-inventory generation
- Target-utilization campaign stopping
- 24-hour customer contact cooldown
- PostgreSQL on Render, SQLite locally

## Product direction

Empty Chair is evolving from a cancellation-recovery tool into an automatic calendar-filling engine for tattoo artists and studios.

The pilot thesis is:

> Empty Chair automatically fills unused tattoo appointments using the customers a shop already has.

The long-term product promise is:

> Empty Chair keeps tattoo artists booked.

See [`docs/AUTOPILOT_PILOT.md`](docs/AUTOPILOT_PILOT.md) for the full Pilot v1.1 model, guardrails, success metrics, and production roadmap.

## Pilot Control Center

After signing in, open:

```text
/pilot
```

The Pilot Control Center includes:

- Pilot readiness
- Recovered revenue
- Recovery rate
- Offer conversion
- Delivery health
- Fill Week / Fill Month campaign creation
- Minimum-ticket control
- Appointment-length control
- Target-utilization control
- Active campaign progress

Autopilot intentionally works only a small number of openings at once. This keeps the customer experience targeted instead of turning the system into a mass-message campaign tool.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn bootstrap:app --reload
```

Open:

```text
http://localhost:8000/signup
```

## Render

Set the environment variables shown in `.env.example`.

At minimum for production:

```text
EMPTY_CHAIR_SESSION_SECRET=<long random value>
EMPTY_CHAIR_BASE_URL=https://YOUR-APP.onrender.com
DATABASE_URL=<Render Postgres URL>
```

Notification controls:

```text
EMPTY_CHAIR_SMS_LIVE=false
EMPTY_CHAIR_EMAIL_LIVE=true
```

For SMS, configure the Twilio variables. For real email, configure `RESEND_API_KEY` and a verified `EMPTY_CHAIR_EMAIL_FROM`.

## Production entry point

Render should run the application through:

```text
bootstrap:app
```

`bootstrap.py` registers the additive feature pages, notification overrides, atomic claim flow, Pilot v1.1 Autopilot routes, and pilot safety rules before serving traffic.
