"""Create a reusable authenticated Instagram browser session for Hunter.

This opens a normal visible Chromium window. The operator completes Instagram's
own login / verification flow manually, then returns to Terminal and presses
ENTER. Hunter saves Playwright storage state for later read-only collectors.

No password is read by this script and no challenge is bypassed.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright


DEFAULT_OUT = ".hunter-instagram-browser-state.json"


async def main() -> int:
    out = Path(os.environ.get("HUNTER_IG_BROWSER_STATE_OUT", DEFAULT_OUT))

    print("hunter instagram browser bootstrap // opening visible browser")
    print("Log into Instagram normally in the browser window.")
    print("Complete any Instagram verification it asks for.")
    print("When you can see your Instagram home/feed, return here and press ENTER.")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")

        await asyncio.get_running_loop().run_in_executor(
            None, input, "Press ENTER after Instagram is fully logged in... "
        )

        # Basic sanity check only; do not scrape or act on the account here.
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        if "/accounts/login" in page.url:
            raise SystemExit("Instagram is still showing the login page; session not saved")

        await context.storage_state(path=str(out))
        if not out.exists() or out.stat().st_size == 0:
            raise SystemExit("Browser session state was not created")

        print(f"hunter instagram browser bootstrap // ok file={out}")
        await browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
