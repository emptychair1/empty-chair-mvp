# Google Integration

Empty Chair uses Google in two separate ways:

1. **Google sign-in** authenticates an existing Empty Chair user.
2. **Google Calendar connection** is optional and grants Calendar access for double-booking protection.

## Required Render environment variables

```text
GOOGLE_CLIENT_ID=<Google OAuth client ID>
GOOGLE_CLIENT_SECRET=<Google OAuth client secret>
GOOGLE_REDIRECT_URI=https://YOUR-RENDER-DOMAIN/auth/google/callback
GOOGLE_CALENDAR_REDIRECT_URI=https://YOUR-RENDER-DOMAIN/integrations/google-calendar/callback
```

Add both redirect URIs to the authorized redirect URIs for the Google OAuth web client.

## Availability safety flow

```text
Owner creates an Empty Chair availability block
        ↓
Before an offer is activated, Empty Chair checks Google Calendar
        ↓
Busy → mark slot NO_RECOVERY and do not contact a customer
Free → send the offer
        ↓
Customer claims
        ↓
Empty Chair checks Google Calendar again
        ↓
Busy → reject claim
Free → atomically create Empty Chair booking
        ↓
Create a Google Calendar event for the booked time
```

If no Calendar connection exists, Empty Chair continues to use manually entered availability.

Calendar API failures are logged and currently fail open so a temporary Google outage does not disable manual availability. The claim transaction still prevents two Empty Chair customers from claiming the same opening.
