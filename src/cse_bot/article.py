"""Fetch a PNU CSE article detail page and extract the body text."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"


@dataclass(frozen=True)
class ArticleContent:
    body: str
    image_urls: list[str]


def extract_image_urls(html: str, *, base_url: str, limit: int = 3) -> list[str]:
    """Return absolute URLs of the first `limit` <img> tags inside `.board-view .txt`."""
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one(".board-view .txt")
    if container is None:
        return []
    urls: list[str] = []
    for img in container.find_all("img"):
        src = img.get("src", "")
        if not isinstance(src, str) or not src:
            continue
        urls.append(urljoin(base_url, src))
        if len(urls) >= limit:
            break
    return urls


def fetch_article_content(
    url: str, *, timeout: float, retries: int,
) -> ArticleContent | None:
    """GET the article and return body + first 3 image URLs, or None on failure."""
    attempts = max(1, retries)
    html: str | None = None
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
            log.warning("article.retryable status=%d", resp.status_code)
            if i == attempts - 1:
                return None
            continue
        if resp.status_code >= 400:
            log.warning("article.client_error status=%d", resp.status_code)
            return None
        html = resp.text
        break
    if html is None:
        return None
    body = extract_body(html) or ""
    images = extract_image_urls(html, base_url=url, limit=3)
    if not body and not images:
        return None
    return ArticleContent(body=body, image_urls=images)


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
