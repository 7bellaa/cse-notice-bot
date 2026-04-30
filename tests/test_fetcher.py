"""Unit tests for the fetcher (HTTP layer)."""
from __future__ import annotations

import httpx
import pytest
import respx

from cse_bot.fetcher import FetchError, fetch

URL = "https://cse.pusan.ac.kr/cse/14221/subview.do"


@respx.mock
def test_fetch_returns_text_on_200() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, text="<html>OK</html>"))
    assert fetch(URL, timeout=5.0, retries=3) == "<html>OK</html>"


@respx.mock
def test_fetch_retries_on_5xx_then_succeeds() -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(503),
            httpx.Response(200, text="ok"),
        ]
    )
    assert fetch(URL, timeout=5.0, retries=3) == "ok"
    assert route.call_count == 3


@respx.mock
def test_fetch_raises_after_all_retries_exhausted() -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(FetchError):
        fetch(URL, timeout=5.0, retries=3)


@respx.mock
def test_fetch_raises_immediately_on_4xx() -> None:
    respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FetchError, match="404"):
        fetch(URL, timeout=5.0, retries=3)


@respx.mock
def test_fetch_sets_user_agent() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, text="ok"))
    fetch(URL, timeout=5.0, retries=3)
    sent = route.calls.last.request.headers.get("User-Agent", "")
    assert "cse-discord-bot" in sent
