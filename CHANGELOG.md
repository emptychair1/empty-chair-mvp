# Changelog

All notable Empty Chair pilot changes are documented here.

## [1.1.0-pilot] - 2026-08-14

### Added
- Pilot control center and utilization-focused dashboard
- Fill Week / Fill Month Autopilot campaigns
- Google Calendar connection and calendar safety checks
- Stripe deposits and Stripe Connect onboarding
- Booking confirmation and rejection workflow
- Studio-facing booking detail pages
- Calendar visualization for open, working, confirmed, completed, and Google-busy time
- Demo mode and guided onboarding
- Delivery safety, retry controls, and pilot worker

### Fixed
- PostgreSQL demo reset query handling
- Calendar appointment detail links
- Pending claim confirmation controls
- Booking confirmation failures caused by non-critical Google Calendar errors

### Release policy
- `main` is the production branch.
- Feature work is developed on `feature/*`, `fix/*`, or `chore/*` branches.
- Production releases should be tagged from `main` after tests pass.
