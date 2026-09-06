"""Route the shared Square OAuth callback to artist deposits or Empty Chair billing."""
from __future__ import annotations

from fastapi import Request
import v2_app as core
import v2_artist_payments as artist_payments
import v2_subscription_billing as billing

CALLBACK_PATH = "/settings/payments/square/callback"


def _is_square_callback(route):
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", set()) or set()
    return path == CALLBACK_PATH and "GET" in methods


# v2_artist_payments owns this callback historically. Replace that route with a dispatcher
# so the same Square application can connect both artist deposit accounts and the one
# Empty Chair platform merchant used for SaaS subscriptions.
core.app.router.routes[:] = [r for r in core.app.router.routes if not _is_square_callback(r)]


@core.app.get(CALLBACK_PATH)
def square_callback_bridge(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    signed = core.unsign(state)
    if signed and signed.startswith("billing-platform:"):
        return billing.finish_platform_oauth(code, state, error)
    return artist_payments.square_callback(code, state, error)


print("Empty Chair 2.0 Square OAuth callback bridge loaded", flush=True)
