"""Desktop interaction hardening for the observable M4 operator demo.

The original page works on mobile but some desktop browsers can leave the Run
button inert because its initial disabled state / cached page state survives the
status load. This wrapper preserves the original page and adds a fresh desktop
click bridge plus visible diagnostics instead of silent failure.
"""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import m4_operator_observable as observable

_original_live = observable.m4_operator_live

# Replace only the GET page route; all operator APIs remain unchanged.
core.app.router.routes[:] = [
    route for route in core.app.router.routes
    if not (
        getattr(route, "path", None) == "/m4-operator-live"
        and "GET" in (getattr(route, "methods", None) or set())
    )
]


@core.app.get("/m4-operator-live", response_class=HTMLResponse)
def m4_operator_live_desktop_safe(request: Request):
    response = _original_live(request)
    if not isinstance(response, HTMLResponse):
        return response

    html = response.body.decode("utf-8")
    patch = r'''
<script>
(() => {
  function showDiagnostic(message) {
    const log = document.getElementById('log');
    if (log) log.textContent += '\nDESKTOP // ' + message;
    const state = document.getElementById('m4state');
    if (state) state.textContent = message;
  }

  async function refreshRunAvailability() {
    const run = document.getElementById('run');
    if (!run) return;
    try {
      const r = await fetch('/api/m4/operator/status?desktop=' + Date.now(), {
        cache: 'no-store',
        headers: {'Cache-Control': 'no-cache'}
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'status failed');
      if ((!j.openings || !j.openings.length) && j.synthetic) {
        const rr = await fetch('/api/m4/operator/reset-synthetic?desktop=' + Date.now(), {
          method: 'POST', cache: 'no-store'
        });
        if (rr.ok) return refreshRunAvailability();
      }
      run.disabled = !(j.openings && j.openings.length);
      run.style.pointerEvents = 'auto';
      run.style.opacity = '1';
    } catch (e) {
      run.disabled = false;
      run.style.pointerEvents = 'auto';
      showDiagnostic('Run control recovered; status refresh failed: ' + (e.message || e));
    }
  }

  function installDesktopBridge() {
    const run = document.getElementById('run');
    if (!run || run.dataset.desktopBridge === '1') return;
    run.dataset.desktopBridge = '1';
    run.setAttribute('type', 'button');
    run.style.pointerEvents = 'auto';

    // Preserve the page's existing recovery handler but invoke it from a fresh,
    // explicit listener. This avoids stale inline/property click state on desktop.
    const original = run.onclick;
    run.onclick = null;
    run.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (run.dataset.running === '1') return;
      run.dataset.running = '1';
      run.textContent = 'M4 RUNNING…';
      showDiagnostic('Run click received.');
      try {
        if (typeof original !== 'function') {
          throw new Error('Recovery handler did not initialize. Reloading operator state.');
        }
        run.disabled = false;
        await original.call(run, event);
      } catch (e) {
        run.disabled = false;
        showDiagnostic('Run failed: ' + (e.message || e));
      } finally {
        run.dataset.running = '0';
        if (run.textContent === 'M4 RUNNING…') run.textContent = 'Run full recovery';
      }
    }, {capture: true});
  }

  // The original script is at the end of the page, so install after it has had a
  // chance to assign run.onclick. Re-check once more for slower desktop parsing.
  window.addEventListener('load', () => {
    setTimeout(() => { installDesktopBridge(); refreshRunAvailability(); }, 50);
    setTimeout(() => { installDesktopBridge(); refreshRunAvailability(); }, 800);
  }, {once: true});
})();
</script>
'''
    html = html.replace("</body>", patch + "</body>")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
