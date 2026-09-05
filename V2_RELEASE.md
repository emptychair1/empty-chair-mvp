# Empty Chair 2.0

## One job

A tattoo appointment disappears. Empty Chair gets another qualified client into that chair.

`CANCELLATION -> REPLACEMENT CUSTOMER -> DEPOSIT -> CALENDAR -> RECOVERED REVENUE`

## Production surface

Render loads exactly:

`production_entry.py -> bootstrap.py -> v2_app.py`

No 1.x dashboards, M4 UI, Concierge, contests, demand tools, meetings, simulations, content systems, admin surfaces, or demo modules are imported in production.

## Runtime dependencies

Only FastAPI, Uvicorn, python-multipart, and psycopg2-binary. Twilio, Resend, Google, Apple CalDAV, Square, and PayPal are called through HTTPS using Python's standard library.

## Artist experience

Setup once: identity -> phone verification -> Google Calendar or Apple Calendar -> deposit rule/payment methods -> client CSV import -> `ARMED.` / `YOU CAN CLOSE THIS NOW.` Normal use is headless; no dashboard.

## Customer experience

SMS/email remain literal monospace ASCII. Customer web flow is `OPEN -> TAKE THE CHAIR -> YES -> CASH APP / VENMO / CARD -> YOURS -> TAKE A SEAT.` Cash App + card use Square; Venmo uses PayPal. Successful deposit writes the replacement booking back to the connected calendar.

## Brand

Amber terminal: background `#0B0905`, primary `#FFB000`, bright `#FFD36A`, dim `#805800`, off `#332300`. The chair is not present on every screen. Whenever it is present it is centered exactly.

## Required production configuration

Core: `DATABASE_URL`, `EMPTY_CHAIR_BASE_URL`, `EMPTY_CHAIR_SESSION_SECRET`, `EMPTY_CHAIR_WORKER_ENABLED=true`.

SMS: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.

Email: `RESEND_API_KEY`, `EMPTY_CHAIR_EMAIL_FROM`.

Google: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

Square: `SQUARE_APPLICATION_ID`, `SQUARE_LOCATION_ID`, `SQUARE_ACCESS_TOKEN`, `SQUARE_ENV=production`.

PayPal/Venmo: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV=production`.
