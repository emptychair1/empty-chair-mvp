# Empty Chair iPhone shell

Native SwiftUI/EventKit shell for the headless Empty Chair product.

## Product flow

Face ID -> Apple Calendar native permission -> choose tattoo calendar -> ARMED -> close app.

No Apple ID or app-specific password is collected.

## Current boundary

This commit establishes the native permission, calendar selection, Face ID, and ARMED surfaces. The next implementation step is the sync bridge: snapshot selected EventKit appointments to the Empty Chair backend, detect device-side calendar changes/background refresh, and accept filled-booking writes back into EventKit.

The existing server CalDAV credential flow is legacy and must not be exposed as the shipped Apple experience.
