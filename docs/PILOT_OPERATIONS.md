# Pilot operations runbook

Phase 4 gives each authenticated shop owner one shop-scoped control center at
`/operations`.

## Daily check

1. Resolve claims in **Needs attention**.
2. Check disconnected artist calendars before confirming appointments.
3. Review failed deliveries and retry only offers that are still active.
4. Review system failures. Record recurring failures with timestamps before
   changing configuration.

## Safe controls

- **Pause** stops a campaign from advancing. It does not revoke an offer that a
  customer already received.
- **Resume** reactivates the campaign and immediately asks the worker to advance
  eligible openings.
- **Cancel booking** is available for provisional and confirmed bookings. It
  cancels the booking, invalidates active offers, reopens the slot, and starts a
  recovery campaign.
- **Retry** never revives expired, claimed, declined, or cancelled offers.

## Reporting

Dashboard revenue and booking totals include only `CONFIRMED` and `COMPLETED`
bookings. The CSV export contains all booking states so corrections remain
auditable.

## Backup and rollback before pilot changes

1. Create a database backup using the hosting provider's PostgreSQL backup or
   snapshot feature and verify its timestamp.
2. Record the currently deployed commit SHA.
3. Deploy the change and run the authenticated health and operations checks.
4. If validation fails, redeploy the recorded commit. Restore the database only
   when a schema or data mutation cannot be corrected forward; restoring a
   snapshot discards newer pilot activity.

Never claim a backup exists until it is visible and restorable in the hosting
provider.
