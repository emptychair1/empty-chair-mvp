# Empty Chair — Google Play submission copy

## App name
Empty Chair

## Short description
Fill canceled tattoo appointments automatically.

## Full description
Empty Chair protects a tattoo artist's calendar when a client cancels.

Connect your tattoo calendar once, connect payments, import your clients, and close the app. When an appointment disappears, Empty Chair contacts the best available clients by SMS. A replacement client can commit with a deposit, and the filled appointment is written back to your calendar.

No dashboard to babysit. No marketplace. No customer accounts.

When they cancel, we fill the chair.

## Permission disclosure
- READ_CALENDAR: reads the artist-selected tattoo calendar so Empty Chair can detect when an appointment disappears.
- WRITE_CALENDAR: writes a replacement appointment back after a chair is filled.
- USE_BIOMETRIC: protects local app access with the device authentication prompt.
- INTERNET: syncs the selected calendar snapshot and write commands with Empty Chair.

## Data safety notes
- Calendar data is limited to the artist-selected calendar and the time window needed for cancellation recovery.
- The app uses one-time SMS verification to link an existing Empty Chair artist account.
- Customers do not create accounts in the mobile app.

## Internal-test flow
1. Open Empty Chair.
2. Verify an existing artist account by SMS.
3. Allow calendar read/write access.
4. Select the tattoo calendar.
5. App shows ARMED and schedules periodic calendar sync.

## Release
versionName 2.0.0
versionCode 1
