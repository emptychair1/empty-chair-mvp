"""Amber CRT styling and utility controls shared by every Empty Chair 2.0 screen."""
import v2_app as core

_original_page = core.page

CRT_CSS = '''
<style>
html { background: #0B0905; }
body {
  position: relative;
  text-shadow: 0 0 3px rgba(255,176,0,.24), 0 0 8px rgba(255,176,0,.07);
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 9998;
  pointer-events: none;
  background: repeating-linear-gradient(to bottom,rgba(255,176,0,.032) 0,rgba(255,176,0,.032) 1px,transparent 1px,transparent 4px);
  opacity: .62;
}
body::after {
  content: "";
  position: fixed;
  inset: 0;
  z-index: 9997;
  pointer-events: none;
  background: radial-gradient(ellipse at center, transparent 62%, rgba(0,0,0,.16) 100%);
}
main { position: relative; padding-bottom: 68px !important; }
.ec-settings-gear {
  position: absolute;
  left: 22px;
  bottom: 15px;
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: var(--amber);
  text-decoration: none;
  opacity: .78;
  font-size: 20px;
  line-height: 1;
  text-shadow: 0 0 5px rgba(255,176,0,.28);
  z-index: 5;
}
.ec-settings-gear:hover { opacity: 1; }
.ec-corner-marks {
  position: absolute;
  right: 22px;
  bottom: 16px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--amber);
  opacity: .62;
  pointer-events: none;
  text-shadow: 0 0 4px rgba(255,176,0,.28);
}
.ec-dharma-svg { width: 25px; height: 25px; display:block; }
.ec-divider { width: 1px; height: 17px; background: currentColor; opacity: .45; }
.ec-pirate {
  width: 25px;
  height: 25px;
  display: grid;
  place-items: center;
  font-size: 24px;
  line-height: 1;
  transform: translateY(-1px);
}
header, button, .button, input, select, textarea, .error, .status, .chair {
  filter: drop-shadow(0 0 2px rgba(255,176,0,.11));
}

/* Keep all selectable controls inside the amber terminal language. */
input[type="checkbox"] {
  -webkit-appearance: none;
  appearance: none;
  width: 24px;
  height: 24px;
  margin: 0 10px 0 0;
  border: 1px solid var(--amber);
  border-radius: 2px;
  background: transparent;
  display: inline-grid;
  place-content: center;
  vertical-align: middle;
  box-shadow: inset 0 0 0 1px rgba(255,176,0,.12), 0 0 6px rgba(255,176,0,.08);
}
input[type="checkbox"]::before {
  content: "✓";
  color: #FFD875;
  font-size: 20px;
  line-height: 1;
  transform: scale(0);
  transform-origin: center;
  text-shadow: 0 0 4px rgba(255,216,117,.62), 0 0 9px rgba(255,176,0,.28);
}
input[type="checkbox"]:checked {
  background: rgba(255,176,0,.08);
  border-color: #FFD875;
  box-shadow: inset 0 0 0 1px rgba(255,216,117,.18), 0 0 8px rgba(255,176,0,.16);
}
input[type="checkbox"]:checked::before { transform: scale(1); }
input[type="checkbox"]:focus-visible { outline: 1px solid #FFD875; outline-offset: 3px; }

/* Success should read brighter than the normal terminal UI, not bloom across the screen. */
.bright,
.success,
.success *,
.success-mark {
  color: #FFD875 !important;
  text-shadow:
    0 0 3px rgba(255,216,117,.76),
    0 0 9px rgba(255,176,0,.35),
    0 0 17px rgba(255,176,0,.14) !important;
  filter: drop-shadow(0 0 2px rgba(255,176,0,.25)) !important;
}

h1.bright,
h1.success,
.success.big {
  text-shadow:
    0 0 4px rgba(255,216,117,.86),
    0 0 11px rgba(255,176,0,.39),
    0 0 22px rgba(255,176,0,.16) !important;
}

.dim { text-shadow: 0 0 2px rgba(128,88,0,.16); }
.settings-list { display:grid; gap:10px; margin-top:24px; }
.settings-row { display:flex; justify-content:space-between; align-items:center; gap:14px; padding:14px 0; border-bottom:1px solid var(--off); text-decoration:none; color:var(--bright); }
.settings-row small { display:block; margin-top:4px; }
</style>
'''

DHARMA = '''<svg class="ec-dharma-svg" viewBox="0 0 48 48" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5">
<polygon points="16,3 32,3 45,16 45,32 32,45 16,45 3,32 3,16"/>
<circle cx="24" cy="24" r="8"/>
<path d="M24 3v9M24 36v9M3 24h9M36 24h9M9 9l7 7M32 32l7 7M39 9l-7 7M16 32l-7 7"/>
<path d="M17 7h14M17 10h14M17 38h14M17 41h14M7 17v14M10 17v14M38 17v14M41 17v14" opacity=".72"/>
</svg>'''

MARKS = f'<a class="ec-settings-gear" href="/settings" aria-label="Settings">⚙</a><div class="ec-corner-marks" aria-hidden="true">{DHARMA}<span class="ec-divider"></span><span class="ec-pirate">☠</span></div>'


def _mark_success_checks(body: str) -> str:
    """Make every visible completed-state checkmark inherit the global success glow."""
    return body.replace("[✓]", '<span class="success-mark">[✓]</span>')


def crt_page(title: str, body: str, *, script: str = "", chair: bool = False, head: str = ""):
    body = _mark_success_checks(body)
    return _original_page(title, body + MARKS, script=script, chair=chair, head=head + CRT_CSS)


core.page = crt_page
print("Empty Chair 2.0 CRT UI + amber checkbox controls loaded", flush=True)
