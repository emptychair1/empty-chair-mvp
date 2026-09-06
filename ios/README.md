# Empty Chair native containers

## iOS

The iPhone container is intentionally thin and headless:

SMS link -> device authentication -> EventKit permission -> choose tattoo calendar -> ARMED -> close app.

It uses native EventKit. No Apple ID, CalDAV URL, or app-specific password is collected in the iOS app. Selected calendar snapshots are sent to the existing Empty Chair backend; removed appointments enter the existing recovery engine; filled-chair write commands return to EventKit and are acknowledged by the device.

Background refresh is registered as `com.tryemptychair.calendar-sync`. iOS schedules background work at system discretion, so foreground/EventKit-change sync remains part of the design.

## Android

The Android container uses Android Calendar Provider with READ_CALENDAR/WRITE_CALENDAR and the same backend sync/outbox protocol. It is under `android/`.

## Distribution boundary

Source is ready for native project builds, but repository commits are not proof of a signed device build. Shipping requires the external platform steps:

- Apple Developer membership, bundle/App ID, signing team and provisioning profile.
- Xcode archive -> App Store Connect -> TestFlight.
- Google Play Console app, signing key / Play App Signing, release bundle -> internal testing.
- Real-device permission/background tests on each platform before public distribution.

Do not replace the native calendar experience with the web CalDAV password flow. The web flow remains the fallback for the current web product.
