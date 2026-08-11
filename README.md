# Empty Chair MVP

A deliberately small, real MVP for the Empty Chair pilot.

## What it does

1. Creates a tattoo-studio opening.
2. Finds eligible customers.
3. Scores candidates with transparent rules.
4. Creates offers.
5. Sends SMS in demo mode or through Twilio.
6. Lets a customer claim an opening.
7. Creates a booking handoff.
8. Lets the shop confirm and complete the booking.
9. Records events and recovered revenue.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open:

```text
http://localhost:8000
```

Click `Load Demo Studio`.

## Demo SMS

Demo mode is enabled by default:

```bash
EMPTY_CHAIR_DEMO_MODE=true
```

SMS links are printed in the server console instead of being sent.

## Real SMS

Set:

```bash
EMPTY_CHAIR_DEMO_MODE=false
EMPTY_CHAIR_BASE_URL=https://your-public-domain.example
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=...
```

The public base URL must be reachable by the customer's phone.

## Important pilot limitations

This is intentionally not production-ready.

Before real customer deployment, add:

- Authentication and authorization
- HTTPS
- CSRF protection
- Rate limiting
- Secure secrets management
- Proper consent/opt-out handling
- Twilio webhook delivery status
- Sequential offer sending
- Booking-system integration
- Audit logging
- Database migrations
- Production database
- Error monitoring
- Privacy/data-retention controls
- Real legal/compliance review

The MVP is designed to validate the product loop, not to be the final production platform.
