from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = REPO_ROOT / "docs" / "calendar" / "index.html"
CSS_PATH = REPO_ROOT / "docs" / "calendar" / "style.css"


def read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def read_css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def test_viewport_has_viewport_fit_cover():
    assert "viewport-fit=cover" in read_html()


def test_day_sheet_dom_present():
    assert 'id="day-sheet"' in read_html()


def test_info_toggle_present():
    assert "data-info-toggle" in read_html()


def test_brand_subtitle_split():
    html = read_html()
    assert "brand-subtitle--full" in html
    assert "brand-subtitle--short" in html


def test_css_360_breakpoint():
    assert "@media (max-width: 360px)" in read_css()


def test_css_global_keep_all():
    assert "keep-all" in read_css()


def test_css_safe_area_inset():
    assert "safe-area-inset" in read_css()


def test_css_day_sheet_rules():
    assert ".day-sheet" in read_css()


def test_css_chip_min_height():
    assert "min-height: 44px" in read_css()
