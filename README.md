# Empty Chair v0.7.0

Ready-to-upload FastAPI project with:

- User signup/login/logout
- Signed session authentication
- Password reset email flow
- Per-user shop isolation
- Customer CSV import
- Opening/recovery queue
- Twilio SMS offers
- Customer claim/decline flow
- Booking flow
- Transactional email via Resend
- PostgreSQL on Render, SQLite locally

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://localhost:8000/signup`.

## Render

Set the environment variables shown in `.env.example`.

At minimum for production:

```text
EMPTY_CHAIR_SESSION_SECRET=<long random value>
EMPTY_CHAIR_BASE_URL=https://YOUR-APP.onrender.com
DATABASE_URL=<Render Postgres URL>
```

For SMS, configure the Twilio variables. For real email, configure `RESEND_API_KEY`
and a verified `EMPTY_CHAIR_EMAIL_FROM`.

## GitHub

Upload the **contents** of this folder to your branch/repository root. Do not upload
the outer ZIP itself as the application source.
