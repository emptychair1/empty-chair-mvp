"""Create a reusable Hunter Instagram browser session with Safari WebDriver.

This helper opens a visible Safari automation window. Credentials are read from
local environment variables and entered into Instagram without being printed.
Any Instagram verification or approval remains manual. The resulting cookies
are saved locally for later Hunter browser collectors.

It does not bypass checkpoints or print credential/session values.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.safari.options import Options


OUT = Path(os.environ.get("HUNTER_IG_SAFARI_SESSION_OUT", "hunter-instagram-safari-session.json"))


def _set_input_value(driver, element, value: str) -> None:
    """Set a controlled React-style input value and dispatch normal events."""
    driver.execute_script(
        """
        const el = arguments[0];
        const value = arguments[1];
        const proto = Object.getPrototypeOf(el);
        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
        if (desc && desc.set) {
            desc.set.call(el, value);
        } else {
            el.value = value;
        }
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        """,
        element,
        value,
    )


def _find_first(driver, selectors: list[tuple[str, str]], timeout: int = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for by, selector in selectors:
            found = driver.find_elements(by, selector)
            if found:
                return found[0]
        time.sleep(0.5)
    return None


def main() -> int:
    username = os.environ.get("HUNTER_IG_USERNAME", "").strip()
    password = os.environ.get("HUNTER_IG_PASSWORD", "")
    if not username or not password:
        raise SystemExit("Missing HUNTER_IG_USERNAME or HUNTER_IG_PASSWORD in this Terminal session")

    options = Options()
    driver = webdriver.Safari(options=options)
    try:
        driver.get("https://www.instagram.com/accounts/login/")

        user_field = _find_first(
            driver,
            [
                (By.NAME, "username"),
                (By.CSS_SELECTOR, "input[autocomplete='username']"),
                (By.CSS_SELECTOR, "input[type='text']"),
            ],
        )
        pass_field = _find_first(
            driver,
            [
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[autocomplete='current-password']"),
                (By.CSS_SELECTOR, "input[type='password']"),
            ],
            timeout=5,
        )

        if user_field is None or pass_field is None:
            print("Instagram login form was not detected.")
            print(f"Current URL: {driver.current_url}")
            print(f"Page title: {driver.title}")
            print("Leave the Safari window open and tell me exactly what page/message you see.")
            input("Press ENTER here only when you are ready to close Safari... ")
            return 2

        _set_input_value(driver, user_field, username)
        _set_input_value(driver, pass_field, password)

        login_button = _find_first(
            driver,
            [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(., 'Log in') or contains(., 'Log In')]"),
            ],
            timeout=10,
        )
        if login_button is None:
            raise SystemExit("Instagram login fields were found, but the Log in button was not detected")

        driver.execute_script("arguments[0].click();", login_button)

        print("Safari submitted the Instagram login using local environment credentials.")
        print("Complete any legitimate Instagram verification/approval if prompted.")
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
