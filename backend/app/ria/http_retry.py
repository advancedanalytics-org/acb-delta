"""POST with retries for transient provider errors (429, 5xx, timeouts, dropped connections)."""

import time

import httpx

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def post_json(url: str, *, headers: dict, json: dict, timeout: float, attempts: int = 3):
    for attempt in range(attempts):
        try:
            resp = httpx.post(url, headers=headers, json=json, timeout=timeout)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == attempts - 1:
                raise
        else:
            if resp.status_code not in RETRY_STATUS or attempt == attempts - 1:
                resp.raise_for_status()
                return resp.json()
        time.sleep(1.5 * 2**attempt)
    raise RuntimeError("unreachable")
