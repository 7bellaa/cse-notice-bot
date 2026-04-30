"""Parse PNU CSE bulletin board HTML into Post objects.

This module is a pure function: HTML string in, list of Post out.
Selectors target the JW CMS table layout used by cse.pusan.ac.kr:
  - Table:       table.board-table tbody tr
  - Title link:  td.td-title a
  - Author:      td.td-write
  - Date:        td.td-date
  - Attachment:  td.td-file img[alt="첨부파일"]
  - Post ID:     extracted from href path /bbs/.../1234567/artclView.do
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from cse_bot.models import Post

BASE_URL = "https://cse.pusan.ac.kr"


class ParseEmptyError(Exception):
    """Raised when the parsed page contains zero posts.

    May indicate a site structure change or a genuinely empty page.
    """


def parse(html: str) -> list[Post]:
    """Parse board HTML and return a list of Post objects.

    Raises:
        ParseEmptyError: if no posts could be extracted.
    """
    soup = BeautifulSoup(html, "lxml")
    rows = _select_post_rows(soup)
    if not rows:
        raise ParseEmptyError("no post rows found in HTML")

    posts: list[Post] = []
    for row in rows:
        post = _row_to_post(row)
        if post is not None:
            posts.append(post)

    if not posts:
        raise ParseEmptyError("rows found but none parseable as posts")
    return posts


def _select_post_rows(soup: BeautifulSoup) -> list[Tag]:
    rows = soup.select("table.board-table tbody tr")
    return [r for r in rows if isinstance(r, Tag) and r.find("td")]


def _row_to_post(row: Tag) -> Post | None:
    # Title link — must be inside td.td-title
    title_td = row.select_one("td.td-title")
    if title_td is None:
        return None
    title_link = title_td.select_one("a")
    if title_link is None or not isinstance(title_link, Tag):
        return None

    href = title_link.get("href", "")
    if not isinstance(href, str) or not href:
        return None

    post_id = extract_post_id(href)
    if post_id is None:
        return None

    full_url = urljoin(BASE_URL, href)
    title = _clean_text(title_link.get_text(separator=" ", strip=True))

    author_td = row.select_one("td.td-write")
    author = _clean_text(author_td.get_text(separator=" ", strip=True)) if author_td else ""

    date_td = row.select_one("td.td-date")
    date = _clean_text(date_td.get_text(separator=" ", strip=True)) if date_td else ""

    # td-num contains either "일반공지" (pinned) or a plain post sequence number
    num_td = row.select_one("td.td-num")
    category = _clean_text(num_td.get_text(separator=" ", strip=True)) if num_td else ""

    has_attachment = _has_attachment(row)

    return Post(
        id=post_id,
        title=title,
        author=author,
        date=date,
        url=full_url,
        category=category,
        has_attachment=has_attachment,
    )


# Matches /bbs/<board>/<menu>/<post_id>/artclView.do — used as the primary path pattern.
_ARTCL_ID_RE = re.compile(r"/bbs/[^/]+/[^/]+/(\d+)/artclView")


def extract_post_id(url: str) -> int | None:
    """Extract a positive post ID from a URL, or return None.

    Tries query-string keys first, then the specific artclView path pattern,
    then a generic 3+-digit path segment as a last resort.
    Returns None if no ID is found or if the ID is <= 0.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("articleNo", "article_no", "artclNo", "artcl_no", "no"):
        if key in qs:
            try:
                value = int(qs[key][0])
            except (ValueError, IndexError):
                continue
            if value > 0:
                return value
    m = _ARTCL_ID_RE.search(parsed.path)
    if m:
        value = int(m.group(1))
        # Matched the artclView pattern — return the ID or None; do not fall through.
        return value if value > 0 else None
    m = re.search(r"/(\d{4,})/", parsed.path)
    if m:
        value = int(m.group(1))
        if value > 0:
            return value
    return None


def _has_attachment(row: Tag) -> bool:
    file_td = row.select_one("td.td-file")
    return bool(file_td and file_td.find("img"))


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
