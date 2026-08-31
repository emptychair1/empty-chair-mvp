"""Keep the public Flywheel demo on the same logo asset as the sales homepage."""

import m4_flywheel_demo as demo

HOMEPAGE_LOGO = "https://tryemptychair.com/static/D8F5F51D-90EE-45DE-9D95-DB078BDEB87E.png?v=1"
OLD_LOGO = "/static/empty-chair-logo-transparent.png?v=3"

if OLD_LOGO in demo._HTML:
    demo._HTML = demo._HTML.replace(OLD_LOGO, HOMEPAGE_LOGO)
