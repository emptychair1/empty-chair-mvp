# Empty Chair 2.0

## One job

A tattoo appointment disappears. Empty Chair gets another qualified client into that chair.

`CANCELLATION -> REPLACEMENT CUSTOMER -> DEPOSIT -> CALENDAR -> RECOVERED REVENUE`

## Production surface

Render loads exactly:

`production_entry.py -> bootstrap.py -> v2_app.py + v2_auth.py + v2_pwa.py`

No 1.x dashboards, M4 UI, Concierge, contests, demand tools, meetings, simulations, content systems, admin surfaces, or demo modules are imported in production.

## Runtime dependencies

FastAPI, Uvicorn, python-multipart, psycopg2-binary, and PyJWT[crypto]. Twilio, Resend, Google APIs, Apple CalDAV, Square, and PayPal are called through HTTPS. PyJWT[crypto] exists only to generate and validate Sign in with Apple tokens securely.

## Artist sign-in

Artists can sign in with Google or Apple. Authentication provider and calendar provider are independent: Apple sign-in can use Google Calendar and Google sign-in can use Apple Calendar. After social sign-in, Empty Chair verifies the artist's mobile number, then continues setup.

Google sign-in uses `openid email profile` and requires the callback `https://app.tryemptychair.com/auth/google/login/callback` in Google OAuth configuration.

Sign in with Apple requires a Services ID and associated primary App ID. Register domain `app.tryemptychair.com` and return URL `https://app.tryemptychair.com/auth/apple/callback`. Render variables: `APPLE_CLIENT_ID` (Services ID), `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`.

## Calendar providers

Google Calendar and Apple Calendar are both first-class. Calendar connection is separate from account sign-in.

## Required production configuration

Existing: `DATABASE_URL`, `EMPTY_CHAIR_BASE_URL`, `EMPTY_CHAIR_SESSION_SECRET`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `RESEND_API_KEY`, `EMPTY_CHAIR_EMAIL_FROM`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

Apple sign-in: `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`.

Payments when enabled: `SQUARE_APPLICATION_ID`, `SQUARE_LOCATION_ID`, `SQUARE_ACCESS_TOKEN`, `SQUARE_ENV`; `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV`.
