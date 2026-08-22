# Attribution Classification V1

Empty Chair assigns outcome credit conservatively.

- **Direct** — the same customer explicitly claimed an Empty Chair offer for the same opening before the confirmed booking.
- **Assisted** — no same-opening claim exists, but the customer received a qualifying Empty Chair intervention within the prior 30 days.
- **Organic** — no qualifying recent Empty Chair intervention exists.

The booking outcome event stores the class, classification reason, and strongest evidence reference. The learning signal also carries the attribution class.

This prevents a confirmed booking from being automatically labeled Direct simply because Empty Chair has interacted with the customer at some point.
