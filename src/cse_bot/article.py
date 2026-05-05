"""Fetch a PNU CSE article detail page and extract the body text."""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"


def fetch_article_body(url: str, *, timeout: float, retries: int) -> str | None:
    """GET the article page and return body text, or None on any failure."""
    attempts = max(1, retries)
    for i in range(attempts):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            log.warning("article.network_error url=%s err=%s", url, e)
            if i == attempts - 1:
                return None
            continue
        if 500 <= resp.status_code < 600:
            log.warning("article.retryable status=%d url=%s", resp.status_code, url)
            if i == attempts - 1:
                return None
            continue
        if resp.status_code >= 400:
            log.warning("article.client_error status=%d url=%s", resp.status_code, url)
            return None
        return extract_body(resp.text)
    return None


def extract_body(html: str) -> str | None:
    """Extract body text from `.board-view .txt`. Returns None if missing/empty."""
    soup = BeautifulSoup(html, "lxml")
    el = soup.select_one(".board-view .txt")
    if el is None:
        return None
    text = el.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
