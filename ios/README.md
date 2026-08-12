# Empty Chair — Native iPhone + iPad App

This folder contains the native SwiftUI client for Empty Chair. It talks to the existing FastAPI backend and reuses the same production recovery actions.

## Requirements

- macOS
- Xcode 26 or later for App Store submission in 2026
- XcodeGen (`brew install xcodegen`)
- Apple Developer Program membership for signing, TestFlight, APNs, and App Store distribution

## Generate and open the Xcode project

```bash
cd ios
brew install xcodegen
xcodegen generate
open EmptyChair.xcodeproj
```

Choose an iPhone or iPad simulator and press Run.

## Connect to the backend

The first native build currently points at:

```text
https://empty-chair-mvp.onrender.com
```

If your production Render URL differs, edit `APIClient.baseURL` in:

```text
ios/EmptyChair/EmptyChairApp.swift
```

For a local backend, use:

```text
http://127.0.0.1:8000
```

When testing the iOS Simulator against a backend running on the same Mac, `127.0.0.1` works. For a physical iPhone/iPad against your Mac, use the Mac's LAN IP and configure development transport security as needed.

## Native features included

- Native session login
- Adaptive iPhone/iPad `NavigationSplitView`
- War Room dashboard
- Native Swift Charts recovery chart
- Openings list
- Match Intelligence
- Full-screen Recovery Autopilot launch sequence
- Haptic recovery feedback
- Recovery Command Center
- Queue advance action
- Bookings
- Customer roster/search
- Settings
- Native notification permission/foreground notification handling
- Pull-to-refresh
- Dark Empty Chair visual system

## Backend API included

The feature branch adds:

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/me
GET  /api/dashboard
GET  /api/openings
GET  /api/openings/{id}
GET  /api/recovery
GET  /api/customers
GET  /api/artists
GET  /api/bookings
```

Recovery launch/advance intentionally reuse the existing production web POST actions so there is only one recovery engine.

## Before TestFlight

1. Set the exact production backend URL.
2. In Xcode Signing & Capabilities, choose your Apple Developer team.
3. Add the Push Notifications capability if remote APNs delivery is being enabled.
4. Add your app icon asset set and final screenshots.
5. Confirm a support URL and privacy-policy URL.
6. Confirm account deletion is available in-app before App Store submission if account creation remains available.
7. Test on a physical iPhone and iPad.
8. Archive in Xcode and upload to App Store Connect / TestFlight.

The current project uses bundle identifier:

```text
com.emptychairtattoo.app
```

This intentionally avoids colliding with an unrelated existing app that already uses the Empty Chair name.
