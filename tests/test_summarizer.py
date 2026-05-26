import httpx
import respx

from cse_bot.summarizer import PROMPT_TEMPLATE, SummaryResult, summarize


def test_prompt_covers_action_period_end_dates() -> None:
    """Prompt must instruct Gemini to also treat 인정/모집/운영/신청 기간
    종료일 as a deadline, not just classic 신청·접수·제출 마감일.

    Real example that motivated this: 1388685 학과활동 안내 — body said
    "인정 기간: 2026.03.02. ~ 2026.7.1." but the old prompt asked only
    for "신청·접수·제출 마감일", so Gemini returned deadline=null and
    the calendar missed 2026-07-01.
    """
    for token in ("인정 기간", "모집 기간", "운영 기간", "신청 기간"):
        assert token in PROMPT_TEMPLATE, f"prompt missing coverage for '{token}'"
    # Negative anchor: stale, narrow phrasing must not survive
    assert "신청·접수·제출 마감일이 명시되어 있으면" not in PROMPT_TEMPLATE

ENDPOINT_RE = (
    r"https://generativelanguage\.googleapis\.com/v1beta/models/"
    r"gemini-2\.5-flash-lite:generateContent.*"
)


def _gemini_response(payload_text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": payload_text}]}}]},
    )


@respx.mock
def test_summarize_parses_json_with_summary_and_deadline():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response(
            '{"summary": "- 5/12 시작\\n- 학년별 차등", "deadline": "2026-05-14"}'
        )
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=2.0)
    assert isinstance(out, SummaryResult)
    assert out.summary == "- 5/12 시작\n- 학년별 차등"
    assert out.deadline == "2026-05-14"


@respx.mock
def test_summarize_handles_null_deadline():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response('{"summary": "- bullet", "deadline": null}')
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=2.0)
    assert out is not None
    assert out.summary == "- bullet"
    assert out.deadline is None


@respx.mock
def test_summarize_handles_missing_deadline_key():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response('{"summary": "- bullet"}')
    )
    out = summarize("body", api_key="k", model="gemini-2.5-flash-lite", timeout=2.0)
    assert out is not None
    assert out.summary == "- bullet"
    assert out.deadline is None


@respx.mock
def test_summarize_returns_none_on_429():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(429))
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_on_5xx():
    respx.post(url__regex=ENDPOINT_RE).mock(return_value=httpx.Response(500))
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_on_timeout():
    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=httpx.TimeoutException("t"))
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_when_text_is_not_json():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=_gemini_response("this is not JSON at all")
    )
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_returns_none_on_empty_candidates():
    respx.post(url__regex=ENDPOINT_RE).mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )
    assert summarize("b", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


def test_summarize_returns_none_for_empty_body_and_no_images():
    assert summarize("", api_key="k", model="gemini-2.5-flash-lite", timeout=1.0) is None


@respx.mock
def test_summarize_includes_image_urls_in_payload():
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json
        captured["body"] = json.loads(request.content)
        return _gemini_response('{"summary": "- s", "deadline": null}')

    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=_capture)

    out = summarize(
        "body text",
        image_urls=["https://x/a.jpg", "https://x/b.png"],
        api_key="k", model="gemini-2.5-flash-lite", timeout=2.0,
    )
    assert out is not None
    parts = captured["body"]["contents"][0]["parts"]
    file_parts = [p for p in parts if "fileData" in p or "file_data" in p]
    assert len(file_parts) == 2


@respx.mock
def test_summarize_calls_api_with_image_only_input():
    """Even with empty body, if image_urls are given, summarize should still call API."""
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json
        captured["body"] = json.loads(request.content)
        return _gemini_response('{"summary": "- image content", "deadline": null}')

    respx.post(url__regex=ENDPOINT_RE).mock(side_effect=_capture)
    out = summarize(
        "",
        image_urls=["https://x/a.jpg"],
        api_key="k", model="gemini-2.5-flash-lite", timeout=2.0,
    )
    assert out is not None
    assert out.summary == "- image content"
