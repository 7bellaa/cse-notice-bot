import httpx
import respx

from cse_bot.summarizer import summarize

ENDPOINT_RE = (
    r"https://generativelanguage\.googleapis\.com/v1beta/models/"
    r"gemini-2\.5-flash-lite:generateContent.*"
)


@respx.mock
def test_summarize_returns_text_on_success():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "- 5/12 09:00 시작\n- 학년별 차등"}]}}
                ]
            },
        )
    )
    out = summarize(
        "본문 내용...",
        api_key="k",
        model="gemini-2.5-flash-lite",
        timeout=5.0,
    )
    assert out == "- 5/12 09:00 시작\n- 학년별 차등"


@respx.mock
def test_summarize_returns_none_on_429():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(429))
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_5xx():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(500))
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_timeout():
    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=httpx.TimeoutException("t"))
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_empty_candidates():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


@respx.mock
def test_summarize_returns_none_on_malformed_response():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None


def test_summarize_returns_none_for_empty_body():
    # No HTTP call should be made
    out = summarize("", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0)
    assert out is None
