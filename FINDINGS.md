# Hunter API Call Findings

## Outbound API Calls & Rate Limit Handling

### 1. Webhook Dispatcher
* **File:** `hunter/action_engine.py`
* **API Hit:** Configurable webhook endpoint (`HUNTER_ACTION_WEBHOOK_URL` environment variable)
* **Retry / Throttling Logic:**
  - Implements an exponential backoff loop inside the `send_webhook` function.
  - Number of attempts defaults to 3 (`MAX_ATTEMPTS = 3`).
  - Delay calculation: `sleep(0.5 * (2 ** (attempt - 1)))`.
* **429 Surfacing:**
  - A `429` status code surfaces inside `send_webhook` in `hunter/action_engine.py`.
  - It is classified as a retryable transient error because `429` is present in the `TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}` set.

### 2. Broadcast Channel Probe
* **File:** `hunter/broadcast_channel_probe.py`
* **API Hit:** Instagram profile APIs
  - `WEB_PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"`
  - `PROFILE_URL = "https://www.instagram.com/{username}/"`
  - Also relies on the `instagrapi` library (`probe_instagrapi` function calling `user_info_by_username_gql`).
* **Retry / Throttling Logic:**
  - The direct HTTP fallback logic inside `probe` does not implement manual backoff or retry loops for rate limits; it immediately yields a rate limit result.
  - However, the `instagrapi` request made immediately beforehand uses `public_request_retries_count=1`.
* **429 Surfacing:**
  - A `429` response from either the `WEB_PROFILE_URL` or `PROFILE_URL` call surfaces in the `probe` function.
  - Specifically, `if 429 in codes:` causes it to return a `ProbeResult(..., status="rate_limited", ...)` directly back to the caller.
