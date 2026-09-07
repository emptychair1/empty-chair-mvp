"""Raise Hunter's official auto-engagement daily cap to 100.

This is loaded immediately after v2_hunter_auto_engage so its worker uses the updated
module-level cap. No other engagement behavior changes.
"""
import v2_hunter_auto_engage as auto_engage

auto_engage.DAILY_CAP = 100

print("Hunter auto engage cap override loaded // daily_cap=100", flush=True)
