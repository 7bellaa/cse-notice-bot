from pathlib import Path

import httpx
import respx

from cse_bot.article import extract_body, fetch_article_body

FIXTURE = Path(__file__).parent / "fixtures" / "article_sample.html"


def test_extract_body_returns_text_only_from_txt_block():
    html = FIXTURE.read_text(encoding="utf-8")
    body = extract_body(html)
    assert body is not None
    # Body content must appear
    assert "국제처" in body or "해외파견" in body
    # Header metadata labels must NOT appear (they live in .title, not .txt)
    assert "조회수" not in body
    assert "URL 복사" not in body
    # No "첨부파일이(가) 없습니다" — that lives in .attachment
    assert "첨부파일이(가) 없습니다" not in body


def test_extract_body_returns_none_for_missing_block():
    html = "<html><body><div>nothing relevant</div></body></html>"
    assert extract_body(html) is None


def test_extract_body_collapses_whitespace():
    html = '<div class="board-view"><div class="txt">  hello\n\n\nworld   </div></div>'
    body = extract_body(html)
    assert body == "hello world" or body == "hello\nworld"  # impl chooses


@respx.mock
def test_fetch_article_body_success():
    html = FIXTURE.read_text(encoding="utf-8")
    respx.get("https://cse.pusan.ac.kr/bbs/cse/2055/1389652/artclView.do").mock(
        return_value=httpx.Response(200, text=html)
    )
    body = fetch_article_body(
        "https://cse.pusan.ac.kr/bbs/cse/2055/1389652/artclView.do",
        timeout=5.0,
        retries=1,
    )
    assert body is not None
    assert "국제처" in body or "해외파견" in body


@respx.mock
def test_fetch_article_body_returns_none_on_5xx():
    respx.get("https://x/y").mock(return_value=httpx.Response(503))
    body = fetch_article_body("https://x/y", timeout=1.0, retries=1)
    assert body is None


@respx.mock
def test_fetch_article_body_returns_none_on_network_error():
    respx.get("https://x/y").mock(side_effect=httpx.ConnectError("boom"))
    body = fetch_article_body("https://x/y", timeout=1.0, retries=1)
    assert body is None
