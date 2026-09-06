# EMPTY CHAIR // NATIVE STORE SUBMISSION

## Product

Name: Empty Chair
Subtitle / short description: When they cancel, we fill the chair.
Category: Business
Launch price: $97/month after a 7-day free trial.

## App Store promotional text

A tattoo appointment disappears. Empty Chair finds another qualified client, takes the deposit, and puts the replacement back on your calendar.

## App Store description

Empty Chair protects a tattoo artist's calendar when a client cancels.

Connect your tattoo calendar once, connect payments, import clients, and close the app. When an appointment disappears, Empty Chair works through qualified clients by SMS until someone commits with a deposit. The replacement appointment is written back to the artist's calendar automatically.

Built for individual tattoo artists. No dashboard to manage. No campaigns to run. No inbox to babysit.

WHEN THEY CANCEL, WE FILL THE CHAIR.

## Google Play short description

Recover canceled tattoo appointments automatically.

## Google Play full description

Empty Chair is income protection for tattoo artists.

Set it up once. Empty Chair watches the tattoo calendar for canceled appointments, contacts qualified existing clients by SMS, takes a deposit when someone commits, and restores the filled appointment to the calendar.

The normal artist experience is intentionally quiet: ARMED, OPEN, FILLED, or a clear message if calendar or payment access needs attention.

No dashboard. No lead marketplace. No campaign management.

WHEN THEY CANCEL, WE FILL THE CHAIR.

## Native permissions

### iOS
- Calendar full access: required to watch the selected tattoo calendar and write replacement appointments back.
- Face ID / device authentication: used only to unlock the local Empty Chair container.
- Background refresh: used to request opportunistic calendar synchronization; iOS controls actual execution timing.

### Android
- READ_CALENDAR: required to watch the selected tattoo calendar.
- WRITE_CALENDAR: required to write replacement appointments back.
- USE_BIOMETRIC / device credential: used only to unlock the local Empty Chair container.
- INTERNET: required to synchronize the selected calendar snapshot with Empty Chair.

## Privacy / data-use summary for store forms

Empty Chair processes artist account/contact information, imported client contact information, selected calendar appointment metadata, payment-connection state, recovery activity, and subscription/payment identifiers needed to provide the service. The native device token is an opaque credential used to link the installed app to the artist account. Calendar access is used for the core app function and not for advertising.

The app does not sell personal data and does not use calendar data for third-party advertising.

Store privacy answers must be reconciled against the production privacy policy before submission; this file is implementation guidance, not a replacement legal policy.

## App review notes

Empty Chair is intentionally headless. After setup, the expected artist state is `ARMED. ✓` and the app tells the artist they can close it. Cancellation recovery happens through the backend and SMS; the native app exists primarily to provide device calendar permission/sync and secure local access.

Test reviewer path:
1. Launch app.
2. Link an existing Empty Chair artist account using the SMS verification code.
3. Grant calendar access.
4. Choose a writable tattoo calendar.
5. Confirm `ARMED. ✓`.
6. Add a future test appointment to that calendar and allow the app to sync.
7. Remove that appointment to exercise the cancellation path.

Payment and SMS behavior require the corresponding production/test service accounts to be available during review.

## Distribution boundary

The source projects and unsigned CI builds can be produced from GitHub. Public/TestFlight distribution still requires platform-owned signing material and accounts:

- Apple Developer Program membership, App ID/bundle registration, signing certificate/provisioning, App Store Connect record, privacy answers, screenshots, and TestFlight submission.
- Google Play Console app, Play App Signing or release keystore, privacy/data-safety answers, screenshots, and internal testing track submission.

Do not replace native EventKit/Calendar Provider integration with the web Apple CalDAV password flow. The CalDAV path remains the web fallback only.
