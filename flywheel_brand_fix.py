"""Keep the public Flywheel demo aligned with the sales-site brand assets."""

import m4_flywheel_demo as demo

HOMEPAGE_LOGO = "https://tryemptychair.com/static/D8F5F51D-90EE-45DE-9D95-DB078BDEB87E.png?v=1"
OLD_LOGO = "/static/empty-chair-logo-transparent.png?v=3"
TRANSPARENT_ARTIST = "https://tryemptychair.com/static/3ED11A15-1DAE-4450-A37B-6AF171462465.png?v=1"
OLD_ARTIST = "/static/196D271D-A614-4C34-9A62-AE9D2E18DC15.png"
PREVIOUS_ARTIST = "https://tryemptychair.com/static/DBDDCE04-FDE7-4F7B-A7D6-9A1D7D0AC98B.png?v=1"

if OLD_LOGO in demo._HTML:
    demo._HTML = demo._HTML.replace(OLD_LOGO, HOMEPAGE_LOGO)

for artist_src in (OLD_ARTIST, PREVIOUS_ARTIST):
    if artist_src in demo._HTML:
        demo._HTML = demo._HTML.replace(artist_src, TRANSPARENT_ARTIST)
