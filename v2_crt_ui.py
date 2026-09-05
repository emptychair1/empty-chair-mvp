"""Subtle amber CRT styling shared by every Empty Chair 2.0 HTML screen."""
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
  background: repeating-linear-gradient(
    to bottom,
    rgba(255,176,0,.032) 0,
    rgba(255,176,0,.032) 1px,
    transparent 1px,
    transparent 4px
  );
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
main { position: relative; }
.ec-corner-marks {
  position: absolute;
  right: 22px;
  bottom: 16px;
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--amber);
  opacity: .58;
  pointer-events: none;
  text-shadow: 0 0 4px rgba(255,176,0,.28);
}
.ec-dharma {
  width: 13px;
  height: 13px;
  border: 1px solid currentColor;
  transform: rotate(22.5deg);
  position: relative;
}
.ec-dharma::before,
.ec-dharma::after {
  content: "";
  position: absolute;
  background: currentColor;
  opacity: .8;
}
.ec-dharma::before { width: 1px; height: 17px; left: 5px; top: -3px; }
.ec-dharma::after { width: 17px; height: 1px; left: -3px; top: 5px; }
.ec-divider { width: 1px; height: 14px; background: currentColor; opacity: .45; }
.ec-pirate { font-size: 11px; line-height: 1; transform: translateY(-1px); }
header, button, .button, input, select, textarea, .error, .status, .chair {
  filter: drop-shadow(0 0 2px rgba(255,176,0,.11));
}
.bright {
  text-shadow: 0 0 4px rgba(255,211,106,.32), 0 0 10px rgba(255,176,0,.08);
}
.dim { text-shadow: 0 0 2px rgba(128,88,0,.16); }
</style>
'''

MARKS = '<div class="ec-corner-marks" aria-hidden="true"><span class="ec-dharma"></span><span class="ec-divider"></span><span class="ec-pirate">☠</span></div>'


def crt_page(title: str, body: str, *, script: str = "", chair: bool = False, head: str = ""):
    return _original_page(title, body + MARKS, script=script, chair=chair, head=head + CRT_CSS)


core.page = crt_page
print("Empty Chair 2.0 subtle CRT UI loaded", flush=True)
