"""Create a reusable Hunter Instagram browser session with Safari WebDriver.

This helper opens a normal visible Safari window. The operator completes login and
any Instagram verification manually. The script then exports cookies and basic
session metadata to a local JSON file for later Hunter browser collectors.

It does not automate credentials, bypass checkpoints, or print cookie values.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.safari.options import Options


OUT = Path(os.environ.get("HUNTER_IG_SAFARI_SESSION_OUT", "hunter-instagram-safari-session.json"))


def main() -> int:
    options = Options()
    driver = webdriver.Safari(options=options)
    try:
        driver.get("https://www.instagram.com/")
        print("Safari opened Instagram.")
        print("Log in manually and complete any Instagram verification.")
        input("When you can see your Instagram home feed, return here and press ENTER... ")

        cookies = driver.get_cookies()
        if not cookies:
            raise SystemExit("No Safari session cookies found. Make sure Instagram is logged in before pressing ENTER.")

        current_url = driver.current_url
        payload = {
            "schema": "empty-chair-hunter-safari-session-v1",
            "origin": "https://www.instagram.com",
            "current_url": current_url,
            "cookies": cookies,
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if not OUT.exists() or OUT.stat().st_size == 0:
            raise SystemExit("Safari session file was not created")

        print(f"hunter safari session bootstrap // ok cookies={len(cookies)} file={OUT}")
        print("Session contents are sensitive. Do not commit or paste this file into chat.")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
