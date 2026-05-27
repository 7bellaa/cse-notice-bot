"""HTTP fetch layer with retry and timeout."""
from __future__ import annotations

import logging

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from cse_bot._http import USER_AGENT

log = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when an HTTP fetch fails terminally (after retries or on 4xx)."""


class _RetryableHTTPError(Exception):
    """Internal marker — only retry these."""


def fetch(url: str, timeout: float, retries: int) -> str:
    """GET *url* and return the response body as text.

    Retries on network errors and 5xx responses with exponential backoff
    (1s → 2s → 4s, capped). Does not retry 4xx — those are terminal.
    """

    @retry(
        stop=stop_after_attempt(max(1, retries)),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(_RetryableHTTPError),
        reraise=True,
    )
    def _do() -> str:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            log.warning("fetch.network_error url=%s err=%s", url, e)
            raise _RetryableHTTPError(str(e)) from e

        if 500 <= resp.status_code < 600:
            log.warning("fetch.server_error url=%s status=%d", url, resp.status_code)
            raise _RetryableHTTPError(f"status={resp.status_code}")
        if resp.status_code >= 400:
            raise FetchError(f"client error: status={resp.status_code} url={url}")
        return resp.text

    try:
        return _do()
    except _RetryableHTTPError as e:
        raise FetchError(f"retries exhausted: {e}") from e
    except RetryError as e:  # defensive — reraise=True should bypass this
        raise FetchError(f"retries exhausted: {e}") from e
