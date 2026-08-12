# Empty Chair Autopilot — Pilot v1.1

## Product thesis

Empty Chair should not only recover last-minute cancellations. It should help tattoo artists and studios fill unused calendar capacity automatically using customers who already have a relationship with the studio.

The simplest customer-facing promise is:

> Empty Chair keeps tattoo artists booked.

Cancellation recovery remains the highest-urgency use case. Autopilot expands the same matching and offer engine across a controlled block of available time such as a week or month.

## Pilot modes

### Recovery Mode

One unexpected opening is created and Empty Chair immediately works the recovery queue.

### Fill Week

The studio gives Empty Chair a seven-day availability block. Empty Chair creates bookable appointment inventory and works the open slots in a controlled sequence.

### Fill Month

The studio provides up to 31 days of availability. Empty Chair creates appointment inventory and continues working toward the target utilization level.

### Autopilot

Autopilot is the umbrella behavior behind Fill Week and Fill Month. The studio provides a small set of business constraints and Empty Chair handles matching and offer sequencing.

## Required inputs

The pilot intentionally keeps setup simple:

- Artist
- Start date
- End date
- Daily start time
- Daily end time
- Appointment length
- Minimum ticket
- Target utilization

The shop should not need to configure ranking weights, customer segments, cadence logic, or offer sequencing.

## Pilot workflow

1. Shop starts an Autopilot campaign from `/pilot`.
2. Empty Chair creates bookable openings across the selected date range and daily hours.
3. Openings are associated with the Autopilot campaign.
4. Only a small number of openings are activated at once.
5. The existing recovery engine ranks eligible customers.
6. Existing communication consent and customer frequency rules remain in force.
7. The highest-ranked eligible customer receives the offer.
8. A claimed slot becomes unavailable and the booking flow remains authoritative.
9. The campaign continues working available slots until stopped or the target utilization is reached.

## Safety and anti-spam guardrails

The pilot should optimize for trust rather than maximum message volume.

Current guardrails:

- Maximum campaign duration: 31 days
- Only consented customers are eligible through the existing matching engine
- Existing customer frequency protection remains enabled
- Existing scoring and ranking remain authoritative
- Maximum active Autopilot opening window: 3 openings per campaign
- A campaign automatically stops progressing when its target utilization is reached
- The shop can stop a campaign manually
- No automatic discounting is introduced by Autopilot

The goal is not to blast the database. The goal is to make a small number of relevant offers to customers most likely to want a specific artist and appointment.

## Pilot success metrics

The pilot should measure business outcomes rather than vanity activity.

Primary metrics:

- Recovered / incremental revenue
- Filled appointments
- Campaign utilization
- Offer-to-claim conversion
- Completed appointment rate
- Average time to fill

Supporting metrics:

- Number of consented customers
- Successful delivery events
- Failed delivery events
- Active campaigns
- Slots actively offering

## What the pilot must prove

The pilot is testing five core assumptions:

1. Shops will provide future availability, not only cancellations.
2. Artists understand a simple `Fill my week` / `Fill my month` workflow.
3. Existing customers respond to relevant availability offers at a useful rate.
4. Controlled automation can generate meaningful incremental revenue without annoying the customer base.
5. A target-utilization model is more valuable to studios than a cancellation-only recovery tool.

## UX principle

The complexity belongs inside Empty Chair, not in the shop interface.

A shop owner should be able to think in terms of:

- Who needs bookings?
- What dates are open?
- What is the minimum ticket?
- How full do I want the calendar?

Everything else should be automated or placed behind advanced settings later.

## Architecture added in Pilot v1.1

Two additive tables support the pilot:

### `autopilot_campaigns`

Stores the artist, date range, daily hours, appointment length, minimum ticket, target utilization, and campaign status.

### `autopilot_campaign_openings`

Associates generated openings with the campaign that created them.

The pilot reuses the existing `openings`, `offers`, `customers`, `bookings`, and `events` tables instead of creating a parallel booking system.

## Current activation model

Pilot v1.1 uses a controlled activation window rather than attempting to work every generated opening simultaneously.

The campaign status is refreshed when the Pilot Control Center or pilot status endpoint runs. At that point Empty Chair can activate additional openings if the campaign is still below its target and has capacity in the active window.

This is intentionally conservative for the pilot. A later production version should move campaign advancement into a scheduled worker so Autopilot progresses independently of dashboard traffic.

## Next production steps after validation

If the pilot proves demand and conversion, the production Autopilot roadmap should include:

- Background scheduler / worker for continuous campaign advancement
- Calendar integration so existing booked time is excluded automatically
- Artist-specific working days and recurring schedules
- Variable appointment lengths by service or project
- Customer preference learning from claims and declines
- Deposit / checkout integration
- Advanced but optional targeting controls
- Shop-level and artist-level utilization targets
- Reporting that separates cancellation recovery revenue from future-calendar fill revenue

## Positioning

Old positioning:

> Empty Chair helps tattoo shops recover cancellations.

Pilot v1.1 positioning:

> Empty Chair automatically fills unused tattoo appointments using the customers a shop already has.

Long-term positioning:

> Empty Chair keeps tattoo artists booked.
