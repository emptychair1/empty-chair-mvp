# Empty Chair — App Store submission copy

## Name
Empty Chair

## Subtitle
Fill canceled tattoo appointments

## Promotional text
When a tattoo appointment disappears, Empty Chair finds a qualified client to take the chair.

## Description
Empty Chair protects a tattoo artist's calendar when a client cancels.

Connect your tattoo calendar once, connect payments, import your clients, and close the app. When an appointment disappears, Empty Chair contacts the best available clients by SMS. The replacement client can commit with a deposit, and the filled appointment is written back to your calendar.

No dashboard to babysit. No marketplace. No customer accounts.

When they cancel, we fill the chair.

## Keywords
cancellation,tattoo,calendar,artist,booking,appointment,waitlist

## Privacy / permission review notes
- Calendar full access: required to detect removed tattoo appointments and write a replacement appointment after a chair is filled.
- Face ID / device authentication: used only as a local unlock gate for the Empty Chair app.
- The iOS app never asks for an Apple ID password or iCloud app-specific password. Calendar access is through EventKit.
- SMS account linking verifies the artist's existing Empty Chair phone number once; the device token is then stored in Keychain.

## Review demo flow
1. Open Empty Chair.
2. Verify an existing Empty Chair account by SMS.
3. Grant Calendar access.
4. Select the calendar that contains tattoo appointments.
5. App shows ARMED and can be closed.

The cancellation/recovery process happens through calendar events, SMS and the existing Empty Chair backend.

## Release version
2.0.0 (build 1)
