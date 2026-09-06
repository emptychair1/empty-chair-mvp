"""Render simple Empty Chair Instagram cards as PNGs."""
from __future__ import annotations

import io
import textwrap

import v2_app as core
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont

BG = "#0B0905"
AMBER = "#FFB000"
BRIGHT = "#FFD36A"
DIM = "#805800"


def _font(size: int, bold: bool = False):
    names = [
        "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap(text: str, width: int):
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False))


@core.app.get("/growth/card/{content_id}.png")
def instagram_card(content_id: str):
    row = core.one("SELECT * FROM growth_content WHERE id=?", (content_id,))
    if not row:
        return Response(status_code=404)

    img = Image.new("RGB", (1080, 1080), BG)
    d = ImageDraw.Draw(img)

    mono = _font(28, False)
    title = _font(58, True)
    body = _font(36, False)
    cta = _font(38, True)

    d.text((72, 66), "EMPTY CHAIR //", font=mono, fill=AMBER)
    d.line((72, 118, 1008, 118), fill=DIM, width=2)

    hook = _wrap(str(row.get("hook") or ""), 24)
    d.multiline_text((72, 190), hook, font=title, fill=BRIGHT, spacing=18)

    body_text = _wrap(str(row.get("body") or ""), 38)
    d.multiline_text((72, 535), body_text, font=body, fill=AMBER, spacing=14)

    d.rectangle((72, 820, 1008, 958), outline=AMBER, width=3)
    d.text((120, 852), "7 DAYS FREE  ->  LINK IN BIO", font=cta, fill=BRIGHT)

    d.text((72, 1000), "WHEN THEY CANCEL, WE FILL THE CHAIR.", font=mono, fill=DIM)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return Response(content=out.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
