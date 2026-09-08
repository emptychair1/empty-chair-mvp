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
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
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


def _submit_login(driver, pass_field) -> None:
    """Submit the form containing the password field without locating a button."""
    submitted = driver.execute_script(
        """
        const pass = arguments[0];
        const form = pass.form || pass.closest('form');
        if (!form) return null;

        if (typeof form.requestSubmit === 'function') {
            try {
                form.requestSubmit();
                return 'form.requestSubmit';
            } catch (e) {}
        }

        try {
            const ev = new Event('submit', {bubbles: true, cancelable: true});
            const allowed = form.dispatchEvent(ev);
            if (allowed) {
                form.submit();
                return 'form.submit';
            }
            return 'submit.event';
        } catch (e) {}

        return null;
        """,
        pass_field,
    )
    if not submitted:
        raise SystemExit("Instagram login fields were filled, but Safari could not locate/submit their form")
    print(f"Safari login submit method: {submitted}")


def _capture_authenticated_cookies(driver, timeout: int = 120):
    """Poll while SafariDriver is alive and return cookies as soon as login lands."""
    deadline = time.time() + timeout
    last_url = ""
    verification_notice_printed = False

    while time.time() < deadline:
        try:
            current_url = driver.current_url
            cookies = driver.get_cookies()
        except InvalidSessionIdException as exc:
            raise SystemExit(
                "Safari automation session ended before Hunter could save the authenticated cookies"
            ) from exc
        except WebDriverException:
            time.sleep(0.5)
            continue

        if current_url != last_url:
            print(f"Instagram page: {current_url}")
            last_url = current_url

        cookie_names = {cookie.get("name") for cookie in cookies}
        if "sessionid" in cookie_names:
            return current_url, cookies

        lowered = current_url.lower()
        if any(token in lowered for token in ("challenge", "checkpoint", "two_factor", "login_activity")):
            if not verification_notice_printed:
                print("Instagram is requesting legitimate verification. Complete it in Safari; Hunter will keep watching for the authenticated session.")
                verification_notice_printed = True

        time.sleep(0.5)

    raise SystemExit(
        "Timed out waiting for Instagram to create an authenticated session. Leave Safari on the verification/login result and report what it shows."
    )


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
        _submit_login(driver, pass_field)

        print("Safari submitted the Instagram login using local environment credentials.")
        print("Hunter will save the session automatically as soon as Instagram authenticates it.")
        print("If Instagram requests verification, complete only that legitimate verification in Safari.")

        current_url, cookies = _capture_authenticated_cookies(driver)

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
        try:
            driver.quit()
        except WebDriverException:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
