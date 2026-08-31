"""Compatibility shim for the full-funnel Empty Chair demo.

The flywheel presentation is now self-contained in m4_flywheel_demo.py. Keeping
this module as a no-op avoids legacy presentation injections if an older import
path still loads it.
"""
import m4_flywheel_demo as demo


def refine(html: str) -> str:
    return html


# Preserve the historical side-effect contract without changing the new demo.
demo._HTML = refine(demo._HTML)
