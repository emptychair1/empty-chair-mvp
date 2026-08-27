"""Shared Empty Chair brand wrapper for owner-facing M4 surfaces."""
from fastapi.responses import HTMLResponse

import app as core


BRAND_LINK = '<link rel="stylesheet" href="/static/m4-brand.css?v=1">'


def _brand_html(html: str, surface: str) -> str:
    if BRAND_LINK not in html:
        html = html.replace("</head>", BRAND_LINK + "</head>")
    html = html.replace("<body>", f'<body class="m4-branded {surface}">', 1)

    # Replace the engineering-label header in the live operator with the real product header.
    if surface == "m4-operator-surface":
        old = '<div class="top"><div class="brand">EMPTY CHAIR<small>M4 // AUTONOMOUS RECOVERY</small></div><div style="display:flex;gap:8px"><button id="run" class="btn">Run full recovery</button><a class="btn alt" href="/demo">Demo home</a></div></div>'
        new = '<div class="top"><div class="brand"><img class="ec-logo" src="/static/empty-chair-logo-transparent.png?v=3" alt="Empty Chair"><div class="ec-product-name"><b>M4 INTELLIGENCE</b>Decision center</div></div><div style="display:flex;gap:8px"><button id="run" class="btn">Run full recovery</button><a class="btn alt" href="/demo">Back to Empty Chair</a></div></div>'
        html = html.replace(old, new)
        marker = '<div class="metrics">'
        strip = '<div class="ec-intel-strip"><div><b>Rank</b><span>Who is most worth contacting first?</span></div><div><b>Explain</b><span>Why M4 prefers that customer.</span></div><div><b>Know when not to guess</b><span>Low confidence triggers learning or fallback.</span></div></div>'
        html = html.replace(marker, strip + marker, 1)

    # Bring the flywheel demo header into the same product vocabulary without disturbing its animation.
    if surface == "m4-flywheel-surface":
        html = html.replace('<body><main class="shell">', '<body class="m4-branded m4-flywheel-surface"><main class="shell">', 1)
        html = html.replace('<div class="brand-copy"><b>M4 INTELLIGENCE</b>THE FLYWHEEL DEMO</div>', '<div class="ec-product-name"><b>M4 INTELLIGENCE</b>Learning flywheel</div>')
        html = html.replace('class="brand"><img', 'class="brand"><img class="ec-logo"', 1)
    return html


def _wrap_route(path: str, surface: str) -> None:
    for route in core.app.routes:
        if getattr(route, "path", None) != path:
            continue
        methods = getattr(route, "methods", None) or set()
        if "GET" not in methods:
            continue
        original = route.endpoint

        def wrapped(*args, __original=original, __surface=surface, **kwargs):
            response = __original(*args, **kwargs)
            if not isinstance(response, HTMLResponse):
                return response
            html = response.body.decode("utf-8")
            html = _brand_html(html, __surface)
            return HTMLResponse(html, status_code=response.status_code, headers={"Cache-Control": "no-store"})

        route.endpoint = wrapped
        break


_wrap_route("/m4-operator-live", "m4-operator-surface")
_wrap_route("/m4-flywheel-demo", "m4-flywheel-surface")
