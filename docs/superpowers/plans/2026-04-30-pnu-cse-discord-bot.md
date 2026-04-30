# PNU CSE Discord Notification Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PNU 정컴 학부 공지(`https://cse.pusan.ac.kr/cse/14221/subview.do`)를 매일 09:00, 18:00에 점검하여 신규 게시글을 Discord webhook으로 알림하는 로컬 자동화 봇을 구현한다.

**Architecture:** Python 3.11+ 단일 실행 (one-shot) 스크립트. launchd가 매 트리거마다 새 프로세스 spawn → HTML fetch → 파싱 → 워터마크(`last_max_post_id`) 기반 diff → Discord webhook POST → 상태 저장 후 종료. 순수 함수(parser, differ)와 I/O 모듈(fetcher, notifier, state)을 분리해 단위 테스트 가능성과 Gemini 리뷰 명료성 확보.

**Tech Stack:** Python 3.11+, `httpx`, `beautifulsoup4` + `lxml`, `pytest`, `respx`, `freezegun`, `ruff`, `mypy`. 의존성 관리는 `uv` (없으면 `pip` + `venv` 폴백). launchd로 macOS 스케줄링.

---

## Per-Task Verification Gate

**Every task ends with Gemini 3 Pro review before proceeding.**

After the final implementation step of each task, run:

```bash
bash scripts/gemini_review.sh "docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-N"
```

(`scripts/gemini_review.sh` is created in **Task 12**. Until that task ships, skip the Gemini step and rely on local pytest/ruff/mypy. From Task 12 onward, every subsequent task **and** retroactively any incomplete prior tasks must obtain `VERDICT: PASS`.)

**Failure handling:** if Gemini returns `FAIL`, parse blocker/major issues, fix, rerun. If 10 iterations don't reach PASS, stop and report to the user with the last response, summary of attempts, and the four resolution options listed in the spec §11.7.

---

## File Structure

```
cseDiscordBot/
├── src/cse_bot/
│   ├── __init__.py            # Task 1
│   ├── models.py              # Task 2
│   ├── parser.py              # Task 3
│   ├── differ.py              # Task 4
│   ├── state.py               # Task 5
│   ├── config.py              # Task 6
│   ├── fetcher.py             # Task 7
│   ├── notifier.py            # Task 8
│   ├── logging_setup.py       # Task 9
│   └── main.py                # Task 10, extended in Task 11
├── tests/
│   ├── conftest.py            # Task 1
│   ├── fixtures/
│   │   └── sample_board.html  # Task 3 (captured live)
│   ├── test_models.py         # Task 2
│   ├── test_parser.py         # Task 3
│   ├── test_differ.py         # Task 4
│   ├── test_state.py          # Task 5
│   ├── test_config.py         # Task 6
│   ├── test_fetcher.py        # Task 7
│   ├── test_notifier.py       # Task 8
│   └── test_main.py           # Task 10
├── config/config.toml         # Task 6
├── scripts/
│   ├── gemini_review.sh       # Task 12
│   └── gemini_review_template.md  # Task 12
├── deploy/
│   └── com.user.cse-bot.plist # Task 13
├── data/                      # Task 5 (runtime, gitignored)
├── logs/                      # Task 9 (runtime, gitignored)
├── .env.example               # Task 6
├── .gitignore                 # Task 1
├── pyproject.toml             # Task 1
└── README.md                  # Task 14
```

---

## Task 1: 프로젝트 스캐폴드

**Goal:** Python 프로젝트 구조, 의존성, gitignore, 가상환경 셋업.

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/cse_bot/__init__.py`, `tests/__init__.py`, `tests/conftest.py`
- Create dirs: `src/cse_bot/`, `tests/fixtures/`, `config/`, `scripts/`, `deploy/`, `data/`, `logs/`, `docs/`

- [ ] **Step 1: Initialize git and verify directory**

```bash
cd /Users/7bellaa/cseDiscordBot
git init
ls
```
Expected: shows existing `docs/` directory.

- [ ] **Step 2: Create directory skeleton**

```bash
mkdir -p src/cse_bot tests/fixtures config scripts deploy data logs
```

- [ ] **Step 3: Write `.gitignore`**

Create `.gitignore`:
```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage

# Project runtime
.env
data/state.json
data/*.corrupt-*
logs/*.log*

# OS
.DS_Store
```

- [ ] **Step 4: Write `pyproject.toml`**

Create `pyproject.toml`:
```toml
[project]
name = "cse_bot"
version = "0.1.0"
description = "PNU CSE Discord notification bot"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "tenacity>=8.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "respx>=0.21",
    "freezegun>=1.4",
    "ruff>=0.5",
    "mypy>=1.10",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-q --strict-markers"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["src"]
```

- [ ] **Step 5: Create empty package init files**

Create `src/cse_bot/__init__.py`:
```python
"""PNU CSE Discord notification bot."""

__version__ = "0.1.0"
```

Create `tests/__init__.py`:
```python
```

Create `tests/conftest.py`:
```python
"""Shared pytest fixtures."""
```

- [ ] **Step 6: Create venv and install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```
Expected: dependencies install without errors.

- [ ] **Step 7: Verify toolchain works**

```bash
source .venv/bin/activate
pytest -q
ruff check src/ tests/
mypy src/
```
Expected:
- pytest: "no tests ran" (0 tests collected — expected at this stage)
- ruff: clean
- mypy: clean (no source files to check yet)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore src/ tests/
git commit -m "chore: initialize Python project scaffold"
```

---

## Task 2: 데이터 모델 (`models.py`)

**Goal:** `Post`, `BoardConfig`, `BoardState` 데이터클래스 정의 및 단위 테스트.

**Files:**
- Create: `src/cse_bot/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_models.py`:
```python
"""Unit tests for data models."""
import pytest

from cse_bot.models import BoardConfig, BoardState, Post


def test_post_is_frozen() -> None:
    post = Post(
        id=19234,
        title="공지 제목",
        author="홍길동",
        date="2026.04.30",
        url="https://cse.pusan.ac.kr/post/19234",
        category="일반공지",
        has_attachment=True,
    )
    with pytest.raises(Exception):
        post.id = 99999  # type: ignore[misc]


def test_post_equality_by_value() -> None:
    a = Post(
        id=1, title="t", author="a", date="d", url="u", category="c", has_attachment=False
    )
    b = Post(
        id=1, title="t", author="a", date="d", url="u", category="c", has_attachment=False
    )
    assert a == b


def test_board_config_defaults_enabled() -> None:
    cfg = BoardConfig(
        id="14221",
        name="일반공지",
        url="https://cse.pusan.ac.kr/cse/14221/subview.do",
        webhook_env="DISCORD_WEBHOOK_GENERAL",
    )
    assert cfg.enabled is True


def test_board_state_baseline_when_none() -> None:
    state = BoardState(last_max_post_id=None, last_checked="2026-04-30T18:00:00+09:00")
    assert state.last_max_post_id is None
    assert state.empty_streak == 0
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest tests/test_models.py -v
```
Expected: ImportError / collection error (`models` module doesn't exist).

- [ ] **Step 3: Implement `models.py`**

Create `src/cse_bot/models.py`:
```python
"""Data classes used across the bot."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Post:
    id: int
    title: str
    author: str
    date: str
    url: str
    category: str
    has_attachment: bool


@dataclass(frozen=True)
class BoardConfig:
    id: str
    name: str
    url: str
    webhook_env: str
    enabled: bool = True


@dataclass
class BoardState:
    last_max_post_id: int | None
    last_checked: str
    empty_streak: int = 0
```

- [ ] **Step 4: Run test, verify it passes**

```bash
pytest tests/test_models.py -v
ruff check src/cse_bot/models.py tests/test_models.py
mypy src/cse_bot/models.py
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/models.py tests/test_models.py
git commit -m "feat(models): add Post, BoardConfig, BoardState dataclasses"
```

- [ ] **Step 6: Gemini review** (skip until Task 12 ships)

---

## Task 3: HTML 파서 (`parser.py`)

**Goal:** PNU CSE 일반공지 게시판 HTML을 `List[Post]`로 변환하는 순수 함수. 실제 사이트 HTML을 한 번 캡처해 픽스처로 사용.

**Files:**
- Create: `tests/fixtures/sample_board.html` (live capture)
- Create: `tests/fixtures/empty_board.html`
- Create: `src/cse_bot/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Capture live HTML fixture**

```bash
curl -sSL -A "cse-discord-bot/0.1 (fixture-capture)" \
  "https://cse.pusan.ac.kr/cse/14221/subview.do" \
  -o tests/fixtures/sample_board.html

wc -c tests/fixtures/sample_board.html
head -20 tests/fixtures/sample_board.html
```
Expected: file is non-empty (typically 50–200 KB), shows HTML doctype.

- [ ] **Step 2: Inspect fixture to identify selectors**

```bash
python3 -c "
from bs4 import BeautifulSoup
html = open('tests/fixtures/sample_board.html').read()
soup = BeautifulSoup(html, 'lxml')
table = soup.select_one('table.board-table, table._artclTbl, table')
print('Table found:', table is not None)
rows = soup.select('table tbody tr')
print('Rows:', len(rows))
if rows:
    print('First row HTML (first 600 chars):')
    print(str(rows[0])[:600])
"
```
Expected: prints structure. Use this to confirm selectors. The PNU 정컴 site typically renders posts in `<table>` rows with `<td>` for number/category/title/author/date/views/attachment.

Record observations (selectors, attributes for post id link, attachment indicator class) — adjust the parser implementation in Step 4 to match.

- [ ] **Step 3: Write failing tests**

Create `tests/fixtures/empty_board.html`:
```html
<!DOCTYPE html>
<html><body>
<table class="board-table"><tbody>
</tbody></table>
</body></html>
```

Create `tests/test_parser.py`:
```python
"""Unit tests for the HTML parser."""
from pathlib import Path

import pytest

from cse_bot.models import Post
from cse_bot.parser import ParseEmptyError, parse


FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_returns_list_of_posts() -> None:
    posts = parse(_load("sample_board.html"))
    assert len(posts) > 0
    assert all(isinstance(p, Post) for p in posts)


def test_parse_post_has_required_fields() -> None:
    posts = parse(_load("sample_board.html"))
    p = posts[0]
    assert p.id > 0
    assert p.title.strip()
    assert p.author.strip()
    assert p.date.strip()
    assert p.url.startswith("http")
    assert isinstance(p.has_attachment, bool)


def test_parse_post_ids_are_unique_within_page() -> None:
    posts = parse(_load("sample_board.html"))
    ids = [p.id for p in posts]
    assert len(ids) == len(set(ids))


def test_parse_empty_board_raises() -> None:
    with pytest.raises(ParseEmptyError):
        parse(_load("empty_board.html"))
```

- [ ] **Step 4: Run tests, verify they fail**

```bash
pytest tests/test_parser.py -v
```
Expected: ImportError / collection error.

- [ ] **Step 5: Implement parser**

Create `src/cse_bot/parser.py`:
```python
"""Parse PNU CSE bulletin board HTML into Post objects.

This module is a pure function: HTML string in, list of Post out.
Selectors target the standard Kollus/Onmam university CMS table layout
used by `cse.pusan.ac.kr`.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup, Tag

from cse_bot.models import Post


BASE_URL = "https://cse.pusan.ac.kr"


class ParseEmptyError(Exception):
    """Raised when the parsed page contains zero rows.

    May indicate site structure change or genuine empty page.
    """


def parse(html: str) -> list[Post]:
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
    # The CSE site uses a board table; try several common selectors.
    candidates = [
        "table._artclTbl tbody tr",
        "table.board-table tbody tr",
        "div._articleTable table tbody tr",
        "table tbody tr",
    ]
    for sel in candidates:
        rows = soup.select(sel)
        # Skip header rows / empty layouts.
        rows = [r for r in rows if r.find("td")]
        if rows:
            return rows
    return []


def _row_to_post(row: Tag) -> Post | None:
    title_link = row.select_one("td._artclTdTitle a, td.td-subject a, td a[href*='artclView']")
    if title_link is None or not isinstance(title_link, Tag):
        return None

    href = title_link.get("href", "")
    if not isinstance(href, str) or not href:
        return None
    full_url = urljoin(BASE_URL, href)
    post_id = _extract_post_id(full_url)
    if post_id is None:
        return None

    title = _clean_text(title_link.get_text(separator=" ", strip=True))
    cells = row.find_all("td")
    text_cells = [_clean_text(c.get_text(separator=" ", strip=True)) for c in cells]

    author = _pick_cell(text_cells, ["작성자", "이름"], fallback_index=-3)
    date = _pick_cell(text_cells, ["작성일", "등록일", "날짜"], fallback_index=-2)
    category = _pick_cell(text_cells, ["분류", "구분"], fallback_index=0)
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


def _extract_post_id(url: str) -> int | None:
    # PNU CSE post URLs typically embed the id in the path (.../artclView.do?...) or
    # as a numeric segment. Try a few extraction strategies.
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("articleNo", "article_no", "artclNo", "artcl_no", "no"):
        if key in qs:
            try:
                return int(qs[key][0])
            except (ValueError, IndexError):
                continue
    m = re.search(r"/(\d{3,})/", parsed.path)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{3,})", parsed.path)
    if m:
        return int(m.group(1))
    return None


def _pick_cell(cells: list[str], _keywords: list[str], fallback_index: int) -> str:
    # Header-driven picking is unreliable here (no <th> mapping in <tr> data rows),
    # so use the fallback positional index. _keywords retained for future extension.
    if not cells:
        return ""
    try:
        return cells[fallback_index]
    except IndexError:
        return ""


def _has_attachment(row: Tag) -> bool:
    if row.select_one("img[alt*='첨부'], i.icon-file, i.fa-paperclip, .attached, .file"):
        return True
    return False


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
```

- [ ] **Step 6: Run tests, verify pass**

```bash
pytest tests/test_parser.py -v
```
Expected: PASS. If selectors miss, inspect the printed structure from Step 2 and adjust the selectors / `_row_to_post` until tests pass.

- [ ] **Step 7: Lint and type-check**

```bash
ruff check src/cse_bot/parser.py tests/test_parser.py
mypy src/cse_bot/parser.py
```
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/cse_bot/parser.py tests/test_parser.py tests/fixtures/
git commit -m "feat(parser): parse PNU CSE board HTML into Post objects"
```

- [ ] **Step 9: Gemini review** (skip until Task 12 ships)

---

## Task 4: Diff 알고리즘 (`differ.py`)

**Goal:** `(posts, watermark) → new_posts` 순수 함수. 워터마크보다 큰 post들을 id 오름차순으로 반환.

**Files:**
- Create: `src/cse_bot/differ.py`
- Create: `tests/test_differ.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_differ.py`:
```python
"""Unit tests for the differ."""
from cse_bot.differ import diff
from cse_bot.models import Post


def _post(id_: int) -> Post:
    return Post(
        id=id_,
        title=f"title-{id_}",
        author="author",
        date="2026.04.30",
        url=f"https://example.com/{id_}",
        category="일반공지",
        has_attachment=False,
    )


def test_diff_returns_empty_when_no_new() -> None:
    posts = [_post(10), _post(11), _post(12)]
    assert diff(posts, watermark=12) == []


def test_diff_returns_only_greater_than_watermark() -> None:
    posts = [_post(10), _post(13), _post(11), _post(14), _post(12)]
    result = diff(posts, watermark=12)
    assert [p.id for p in result] == [13, 14]


def test_diff_returns_ascending_order() -> None:
    posts = [_post(20), _post(15), _post(18)]
    result = diff(posts, watermark=10)
    assert [p.id for p in result] == [15, 18, 20]


def test_diff_baseline_returns_empty() -> None:
    posts = [_post(10), _post(11)]
    # When watermark is None, the bot is in baseline mode — caller handles it.
    # diff() is still defined to return [] for this case.
    assert diff(posts, watermark=None) == []


def test_diff_with_strict_inequality_excludes_equal() -> None:
    posts = [_post(10), _post(11)]
    assert diff(posts, watermark=11) == []
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_differ.py -v
```
Expected: ImportError on `differ`.

- [ ] **Step 3: Implement differ**

Create `src/cse_bot/differ.py`:
```python
"""Pure-function diff: identify new posts strictly above a watermark."""
from __future__ import annotations

from cse_bot.models import Post


def diff(posts: list[Post], watermark: int | None) -> list[Post]:
    """Return posts whose id is strictly greater than watermark, ascending.

    If watermark is None (baseline mode), returns []. The caller is
    responsible for the baseline behaviour (storing max id without notifying).
    """
    if watermark is None:
        return []
    return sorted((p for p in posts if p.id > watermark), key=lambda p: p.id)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_differ.py -v
ruff check src/cse_bot/differ.py tests/test_differ.py
mypy src/cse_bot/differ.py
```
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/differ.py tests/test_differ.py
git commit -m "feat(differ): identify new posts above watermark"
```

- [ ] **Step 6: Gemini review** (skip until Task 12)

---

## Task 5: 상태 저장소 (`state.py`)

**Goal:** `data/state.json`을 load/save하고, 손상된 JSON을 백업한 뒤 베이스라인 모드로 진입.

**Files:**
- Create: `src/cse_bot/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_state.py`:
```python
"""Unit tests for state persistence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cse_bot.models import BoardState
from cse_bot.state import load_state, save_state


def test_load_state_returns_empty_when_file_missing(tmp_path: Path) -> None:
    state = load_state(tmp_path / "state.json")
    assert state == {}


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    payload = {
        "14221": BoardState(
            last_max_post_id=19234,
            last_checked="2026-04-30T18:00:00+09:00",
            empty_streak=0,
        )
    }
    save_state(path, payload)
    loaded = load_state(path)
    assert loaded["14221"].last_max_post_id == 19234
    assert loaded["14221"].last_checked == "2026-04-30T18:00:00+09:00"
    assert loaded["14221"].empty_streak == 0


def test_load_state_with_corrupt_json_backs_up_and_returns_empty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not valid json", encoding="utf-8")

    state = load_state(path)
    assert state == {}

    backups = list(tmp_path.glob("state.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not valid json"


def test_save_state_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "state.json"
    save_state(path, {})
    assert path.exists()


def test_save_state_writes_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    payload = {
        "14221": BoardState(
            last_max_post_id=1, last_checked="t", empty_streak=2
        )
    }
    save_state(path, payload)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["boards"]["14221"]["last_max_post_id"] == 1
    assert raw["boards"]["14221"]["empty_streak"] == 2


def test_save_state_rejects_non_monotonic_watermark(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(path, {"14221": BoardState(last_max_post_id=10, last_checked="t")})
    with pytest.raises(ValueError, match="monotonic"):
        save_state(
            path, {"14221": BoardState(last_max_post_id=5, last_checked="t")}
        )
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_state.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement state**

Create `src/cse_bot/state.py`:
```python
"""Persist board watermark state to a JSON file.

Schema:
    {
      "boards": {
        "<board_id>": {
          "last_max_post_id": int | null,
          "last_checked": ISO8601 string,
          "empty_streak": int
        },
        ...
      }
    }
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from cse_bot.models import BoardState


log = logging.getLogger(__name__)

BoardStateMap = dict[str, BoardState]


def load_state(path: Path) -> BoardStateMap:
    """Load state from disk. Returns {} if missing.

    On corrupt JSON, the file is moved aside as `<name>.corrupt-<epoch>`
    and {} is returned (baseline-mode reset).
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        shutil.move(str(path), backup)
        log.warning("state.corrupt path=%s backup=%s", path, backup)
        return {}

    boards = raw.get("boards", {}) if isinstance(raw, dict) else {}
    result: BoardStateMap = {}
    for board_id, entry in boards.items():
        if not isinstance(entry, dict):
            continue
        result[board_id] = BoardState(
            last_max_post_id=entry.get("last_max_post_id"),
            last_checked=entry.get("last_checked", ""),
            empty_streak=int(entry.get("empty_streak", 0)),
        )
    return result


def save_state(path: Path, state: BoardStateMap) -> None:
    """Persist state to disk atomically. Enforces monotonic watermarks."""
    if path.exists():
        previous = load_state(path)
        for board_id, new in state.items():
            old = previous.get(board_id)
            if (
                old is not None
                and old.last_max_post_id is not None
                and new.last_max_post_id is not None
                and new.last_max_post_id < old.last_max_post_id
            ):
                raise ValueError(
                    f"watermark must be monotonic: board={board_id} "
                    f"old={old.last_max_post_id} new={new.last_max_post_id}"
                )

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "boards": {
            board_id: {
                "last_max_post_id": s.last_max_post_id,
                "last_checked": s.last_checked,
                "empty_streak": s.empty_streak,
            }
            for board_id, s in state.items()
        }
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_state.py -v
ruff check src/cse_bot/state.py tests/test_state.py
mypy src/cse_bot/state.py
```
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/state.py tests/test_state.py
git commit -m "feat(state): JSON persistence with corruption recovery and monotonic watermarks"
```

- [ ] **Step 6: Gemini review** (skip until Task 12)

---

## Task 6: 설정 로더 (`config.py`)

**Goal:** `config/config.toml` + `.env` 로드, 검증, `Config` 객체 반환.

**Files:**
- Create: `config/config.toml`
- Create: `.env.example`
- Create: `src/cse_bot/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create runtime config files**

Create `config/config.toml`:
```toml
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "정컴 일반공지"
url = "https://cse.pusan.ac.kr/cse/14221/subview.do"
webhook_env = "DISCORD_WEBHOOK_GENERAL"
enabled = true
```

Create `.env.example`:
```
DISCORD_WEBHOOK_GENERAL=https://discord.com/api/webhooks/REPLACE_ME
DISCORD_WEBHOOK_ALERT=https://discord.com/api/webhooks/REPLACE_ME
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_config.py`:
```python
"""Unit tests for config loading."""
from __future__ import annotations

from pathlib import Path

import pytest

from cse_bot.config import Config, ConfigError, load_config


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_load_config_parses_general_and_boards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_env = "WH_GEN"
enabled = true
""",
    )
    monkeypatch.setenv("WH_GEN", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://discord.com/api/webhooks/a/b")

    cfg = load_config(cfg_path)
    assert isinstance(cfg, Config)
    assert cfg.general.max_pages == 2
    assert cfg.notification.format == "medium"
    assert len(cfg.boards) == 1
    assert cfg.boards[0].id == "14221"
    assert cfg.webhook_url("14221") == "https://discord.com/api/webhooks/x/y"
    assert cfg.alert_webhook_url == "https://discord.com/api/webhooks/a/b"


def test_missing_webhook_env_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_env = "WH_MISSING"
enabled = true
""",
    )
    monkeypatch.delenv("WH_MISSING", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "https://discord.com/api/webhooks/a/b")

    with pytest.raises(ConfigError, match="WH_MISSING"):
        load_config(cfg_path)


def test_invalid_format_value_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "fancy"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "https://example.com"
webhook_env = "WH_GEN"
enabled = true
""",
    )
    monkeypatch.setenv("WH_GEN", "x")
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "y")

    with pytest.raises(ConfigError, match="format"):
        load_config(cfg_path)


def test_disabled_board_skips_webhook_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    _write(
        cfg_path,
        """
[general]
log_dir = "logs"
state_file = "data/state.json"
max_pages = 2
http_timeout_seconds = 15
http_retries = 3

[notification]
format = "medium"
self_alert_webhook_env = "DISCORD_WEBHOOK_ALERT"

[[boards]]
id = "99999"
name = "비활성"
url = "https://example.com"
webhook_env = "WH_NEVER"
enabled = false
""",
    )
    monkeypatch.delenv("WH_NEVER", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_ALERT", "y")

    cfg = load_config(cfg_path)
    assert cfg.boards[0].enabled is False
```

- [ ] **Step 3: Run tests, verify they fail**

```bash
pytest tests/test_config.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement config**

Create `src/cse_bot/config.py`:
```python
"""Load and validate runtime configuration from TOML + environment."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cse_bot.models import BoardConfig


VALID_FORMATS: tuple[str, ...] = ("minimal", "medium", "detailed")


class ConfigError(Exception):
    """Raised on any configuration validation error."""


@dataclass(frozen=True)
class GeneralConfig:
    log_dir: str
    state_file: str
    max_pages: int
    http_timeout_seconds: float
    http_retries: int


@dataclass(frozen=True)
class NotificationConfig:
    format: Literal["minimal", "medium", "detailed"]
    self_alert_webhook_env: str


@dataclass(frozen=True)
class Config:
    general: GeneralConfig
    notification: NotificationConfig
    boards: list[BoardConfig]
    _webhook_urls: dict[str, str]
    alert_webhook_url: str

    def webhook_url(self, board_id: str) -> str:
        try:
            return self._webhook_urls[board_id]
        except KeyError as e:
            raise ConfigError(f"no webhook resolved for board {board_id}") from e


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    general = _load_general(raw)
    notification = _load_notification(raw)
    boards = _load_boards(raw)

    webhook_urls: dict[str, str] = {}
    for b in boards:
        if not b.enabled:
            continue
        url = os.environ.get(b.webhook_env)
        if not url:
            raise ConfigError(
                f"environment variable {b.webhook_env} is required for board {b.id}"
            )
        webhook_urls[b.id] = url

    alert_env = notification.self_alert_webhook_env
    alert_url = os.environ.get(alert_env)
    if not alert_url:
        raise ConfigError(f"environment variable {alert_env} is required (alert webhook)")

    return Config(
        general=general,
        notification=notification,
        boards=boards,
        _webhook_urls=webhook_urls,
        alert_webhook_url=alert_url,
    )


def _load_general(raw: dict) -> GeneralConfig:
    g = raw.get("general") or {}
    try:
        return GeneralConfig(
            log_dir=str(g["log_dir"]),
            state_file=str(g["state_file"]),
            max_pages=int(g["max_pages"]),
            http_timeout_seconds=float(g["http_timeout_seconds"]),
            http_retries=int(g["http_retries"]),
        )
    except KeyError as e:
        raise ConfigError(f"missing [general] key: {e.args[0]}") from e


def _load_notification(raw: dict) -> NotificationConfig:
    n = raw.get("notification") or {}
    fmt = str(n.get("format", ""))
    if fmt not in VALID_FORMATS:
        raise ConfigError(
            f"invalid notification.format={fmt!r}; expected one of {VALID_FORMATS}"
        )
    alert = str(n.get("self_alert_webhook_env", ""))
    if not alert:
        raise ConfigError("notification.self_alert_webhook_env is required")
    return NotificationConfig(format=fmt, self_alert_webhook_env=alert)  # type: ignore[arg-type]


def _load_boards(raw: dict) -> list[BoardConfig]:
    items = raw.get("boards") or []
    if not items:
        raise ConfigError("at least one [[boards]] entry is required")
    boards: list[BoardConfig] = []
    for i, b in enumerate(items):
        try:
            boards.append(
                BoardConfig(
                    id=str(b["id"]),
                    name=str(b["name"]),
                    url=str(b["url"]),
                    webhook_env=str(b["webhook_env"]),
                    enabled=bool(b.get("enabled", True)),
                )
            )
        except KeyError as e:
            raise ConfigError(f"[[boards]] index {i}: missing key {e.args[0]}") from e
    return boards
```

- [ ] **Step 5: Run tests, verify they pass**

```bash
pytest tests/test_config.py -v
ruff check src/cse_bot/config.py tests/test_config.py
mypy src/cse_bot/config.py
```
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/cse_bot/config.py tests/test_config.py config/config.toml .env.example
git commit -m "feat(config): TOML + env loader with validation"
```

- [ ] **Step 7: Gemini review** (skip until Task 12)

---

## Task 7: HTTP Fetcher (`fetcher.py`)

**Goal:** 페이지 URL을 받아 HTML 문자열을 반환. `tenacity`로 5xx/네트워크 오류 지수 백오프 재시도.

**Files:**
- Create: `src/cse_bot/fetcher.py`
- Create: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_fetcher.py`:
```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_fetcher.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement fetcher**

Create `src/cse_bot/fetcher.py`:
```python
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


log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1 (+https://github.com/local)"


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
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_fetcher.py -v
ruff check src/cse_bot/fetcher.py tests/test_fetcher.py
mypy src/cse_bot/fetcher.py
```
Expected: green. If retry timing makes tests slow, consider patching `wait_exponential` in tests; otherwise total runtime should still be a few seconds.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): HTTP GET with retry on 5xx and network errors"
```

- [ ] **Step 6: Gemini review** (skip until Task 12)

---

## Task 8: Discord Notifier (`notifier.py`)

**Goal:** `Post`를 medium 포맷 메시지로 변환해 Discord webhook에 POST. 429/5xx 재시도, 4xx 즉시 실패.

**Files:**
- Create: `src/cse_bot/notifier.py`
- Create: `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_notifier.py`:
```python
"""Unit tests for the Discord notifier."""
from __future__ import annotations

import httpx
import pytest
import respx

from cse_bot.models import Post
from cse_bot.notifier import NotifyError, format_message, send


WEBHOOK = "https://discord.com/api/webhooks/123/abc"


def _post(id_: int = 19234) -> Post:
    return Post(
        id=id_,
        title="국제처 해외파견 안내",
        author="홍길동",
        date="2026.04.30",
        url=f"https://cse.pusan.ac.kr/post/{id_}",
        category="일반공지",
        has_attachment=True,
    )


def test_format_medium_includes_required_fields() -> None:
    msg = format_message(_post(), fmt="medium")
    assert "국제처 해외파견 안내" in msg
    assert "홍길동" in msg
    assert "2026.04.30" in msg
    assert "https://cse.pusan.ac.kr/post/19234" in msg


def test_format_detailed_includes_category_and_attachment() -> None:
    msg = format_message(_post(), fmt="detailed")
    assert "일반공지" in msg
    assert "첨부 있음" in msg


@respx.mock
def test_send_posts_to_webhook() -> None:
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)
    assert route.called
    body = route.calls.last.request.content.decode("utf-8")
    assert "국제처 해외파견 안내" in body


@respx.mock
def test_send_retries_on_429_then_succeeds() -> None:
    route = respx.post(WEBHOOK).mock(
        side_effect=[
            httpx.Response(429, json={"retry_after": 0.01}),
            httpx.Response(204),
        ]
    )
    send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)
    assert route.call_count == 2


@respx.mock
def test_send_raises_on_4xx_other_than_429() -> None:
    respx.post(WEBHOOK).mock(return_value=httpx.Response(404))
    with pytest.raises(NotifyError, match="404"):
        send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)


@respx.mock
def test_send_raises_after_5xx_retries_exhausted() -> None:
    respx.post(WEBHOOK).mock(return_value=httpx.Response(500))
    with pytest.raises(NotifyError):
        send(_post(), webhook_url=WEBHOOK, fmt="medium", timeout=5.0, retries=3)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_notifier.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement notifier**

Create `src/cse_bot/notifier.py`:
```python
"""Send post notifications to a Discord webhook."""
from __future__ import annotations

import logging
from typing import Literal

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from cse_bot.models import Post


log = logging.getLogger(__name__)

USER_AGENT = "cse-discord-bot/0.1"

Format = Literal["minimal", "medium", "detailed"]


class NotifyError(Exception):
    """Raised when sending a Discord webhook fails terminally."""


class _RetryableNotifyError(Exception):
    pass


def format_message(post: Post, fmt: Format) -> str:
    if fmt == "minimal":
        return f"📢 **새 공지: {post.title}**\n🔗 {post.url}"
    if fmt == "medium":
        return (
            f"📢 **새 공지: {post.title}**\n"
            f"✍️ {post.author} · 📅 {post.date}\n"
            f"🔗 {post.url}"
        )
    if fmt == "detailed":
        attached = "첨부 있음" if post.has_attachment else "첨부 없음"
        return (
            f"📢 **새 공지: {post.title}**  `[{post.category}]`\n"
            f"✍️ {post.author} · 📅 {post.date} · 📎 {attached}\n"
            f"🔗 {post.url}"
        )
    raise ValueError(f"unknown format: {fmt}")


def send(
    post: Post,
    *,
    webhook_url: str,
    fmt: Format,
    timeout: float,
    retries: int,
) -> None:
    """POST a notification to the Discord webhook. Raises NotifyError on terminal failure."""
    content = format_message(post, fmt)
    payload = {"content": content}

    @retry(
        stop=stop_after_attempt(max(1, retries)),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(_RetryableNotifyError),
        reraise=True,
    )
    def _do() -> None:
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    webhook_url, json=payload, headers={"User-Agent": USER_AGENT}
                )
        except httpx.HTTPError as e:
            log.warning("notify.network_error err=%s", e)
            raise _RetryableNotifyError(str(e)) from e

        if resp.status_code in (429,) or 500 <= resp.status_code < 600:
            log.warning("notify.retryable status=%d", resp.status_code)
            raise _RetryableNotifyError(f"status={resp.status_code}")
        if resp.status_code >= 400:
            raise NotifyError(
                f"discord error: status={resp.status_code} body={resp.text[:200]}"
            )
        # 2xx (Discord webhooks usually return 204).

    try:
        _do()
    except _RetryableNotifyError as e:
        raise NotifyError(f"retries exhausted: {e}") from e
    except RetryError as e:
        raise NotifyError(f"retries exhausted: {e}") from e


def send_alert(message: str, *, webhook_url: str, timeout: float = 5.0) -> None:
    """Best-effort alert to the self-alert webhook. Never raises."""
    try:
        with httpx.Client(timeout=timeout) as client:
            client.post(
                webhook_url,
                json={"content": message[:1900]},
                headers={"User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as e:
        log.error("alert.failed err=%s", e)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_notifier.py -v
ruff check src/cse_bot/notifier.py tests/test_notifier.py
mypy src/cse_bot/notifier.py
```
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/notifier.py tests/test_notifier.py
git commit -m "feat(notifier): Discord webhook send with formatted messages"
```

- [ ] **Step 6: Gemini review** (skip until Task 12)

---

## Task 9: 로깅 셋업 (`logging_setup.py`)

**Goal:** 로테이션 핸들러 + key=value 포맷 로거 구성.

**Files:**
- Create: `src/cse_bot/logging_setup.py`

- [ ] **Step 1: Implement logging setup**

Create `src/cse_bot/logging_setup.py`:
```python
"""Configure logging for the cse_bot package."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(log_dir: Path, level: int = logging.INFO) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "cse_bot.log"

    formatter = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if called twice in the same process (tests).
    root.handlers = [file_handler, stream_handler]
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from cse_bot.logging_setup import configure_logging; print('ok')"
ruff check src/cse_bot/logging_setup.py
mypy src/cse_bot/logging_setup.py
```
Expected: prints `ok`, lint/types clean. (No dedicated tests; this is exercised by `test_main.py` in Task 10.)

- [ ] **Step 3: Commit**

```bash
git add src/cse_bot/logging_setup.py
git commit -m "feat(logging): rotating file handler with key=value format"
```

- [ ] **Step 4: Gemini review** (skip until Task 12)

---

## Task 10: 오케스트레이터 (`main.py`) + 통합 테스트

**Goal:** 모든 모듈을 조합하는 한 사이클. 베이스라인 모드, 신규 글 알림, 부분 실패 처리, 페이지 2 fetch까지.

**Files:**
- Create: `src/cse_bot/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_main.py`:
```python
"""Integration tests for the orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from cse_bot.main import run_cycle


BOARD_URL = "https://cse.pusan.ac.kr/cse/14221/subview.do"
WEBHOOK = "https://discord.com/api/webhooks/x/y"
ALERT = "https://discord.com/api/webhooks/a/alert"


def _html_with_posts(ids: list[int]) -> str:
    rows = "".join(
        f"""
        <tr>
            <td>일반공지</td>
            <td class="_artclTdTitle">
                <a href="https://cse.pusan.ac.kr/cse/14221/artclView.do?articleNo={i}">제목 {i}</a>
            </td>
            <td>작성자</td>
            <td>2026.04.30</td>
            <td>10</td>
        </tr>
        """
        for i in ids
    )
    return f"<html><body><table class='_artclTbl'><tbody>{rows}</tbody></table></body></html>"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"""
[general]
log_dir = "{tmp_path / 'logs'}"
state_file = "{tmp_path / 'state.json'}"
max_pages = 2
http_timeout_seconds = 5
http_retries = 2

[notification]
format = "medium"
self_alert_webhook_env = "WH_ALERT"

[[boards]]
id = "14221"
name = "일반공지"
url = "{BOARD_URL}"
webhook_env = "WH_GEN"
enabled = true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WH_GEN", WEBHOOK)
    monkeypatch.setenv("WH_ALERT", ALERT)
    return cfg


@respx.mock
def test_baseline_mode_sends_no_notifications(cfg_file: Path, tmp_path: Path) -> None:
    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, text=_html_with_posts([19234, 19233, 19232]))
    )
    notify_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    assert notify_route.call_count == 0

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["boards"]["14221"]["last_max_post_id"] == 19234


@respx.mock
def test_new_posts_are_notified_in_ascending_order(
    cfg_file: Path, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "boards": {
                    "14221": {
                        "last_max_post_id": 19234,
                        "last_checked": "2026-04-30T09:00:00+09:00",
                        "empty_streak": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(
            200, text=_html_with_posts([19237, 19236, 19235, 19234, 19233])
        )
    )
    notify_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    assert notify_route.call_count == 3

    bodies = [json.loads(c.request.content) for c in notify_route.calls]
    titles_in_order = [b["content"] for b in bodies]
    assert "제목 19235" in titles_in_order[0]
    assert "제목 19236" in titles_in_order[1]
    assert "제목 19237" in titles_in_order[2]

    final = json.loads(state_path.read_text(encoding="utf-8"))
    assert final["boards"]["14221"]["last_max_post_id"] == 19237


@respx.mock
def test_partial_failure_preserves_progress(cfg_file: Path, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "boards": {
                    "14221": {
                        "last_max_post_id": 19234,
                        "last_checked": "t",
                        "empty_streak": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    respx.get(BOARD_URL).mock(
        return_value=httpx.Response(
            200, text=_html_with_posts([19236, 19235, 19234])
        )
    )
    # First notify (id 19235) succeeds, second (19236) fails terminally with 404.
    respx.post(WEBHOOK).mock(
        side_effect=[httpx.Response(204), httpx.Response(404)]
    )
    respx.post(ALERT).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    # Cycle reports failure (non-zero), but state was advanced for the successful send.
    assert exit_code != 0

    final = json.loads(state_path.read_text(encoding="utf-8"))
    assert final["boards"]["14221"]["last_max_post_id"] == 19235


@respx.mock
def test_page_2_fetched_when_first_page_all_new(
    cfg_file: Path, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "boards": {
                    "14221": {
                        "last_max_post_id": 19000,
                        "last_checked": "t",
                        "empty_streak": 0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    page1_ids = list(range(19200, 19220))  # 20 posts, all > watermark 19000
    page2_ids = list(range(19180, 19200))  # 20 posts, partly above watermark

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        if page == "2":
            return httpx.Response(200, text=_html_with_posts(page2_ids))
        return httpx.Response(200, text=_html_with_posts(page1_ids))

    respx.get(host="cse.pusan.ac.kr").mock(side_effect=handler)
    notify_route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    exit_code = run_cycle(cfg_file)
    assert exit_code == 0
    # All 40 posts have ids > 19000, so all 40 are notified.
    assert notify_route.call_count == 40
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_main.py -v
```
Expected: ImportError on `cse_bot.main.run_cycle`.

- [ ] **Step 3: Implement main**

Create `src/cse_bot/main.py`:
```python
"""Single-cycle orchestrator entry point."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from cse_bot import differ, fetcher, notifier, parser, state
from cse_bot.config import Config, ConfigError, load_config
from cse_bot.logging_setup import configure_logging
from cse_bot.models import BoardConfig, BoardState, Post


log = logging.getLogger("cse_bot.main")

EMPTY_STREAK_ALERT_THRESHOLD = 3


def run_cycle(config_path: Path) -> int:
    """Run one full check cycle. Returns exit code (0 = success, non-zero = error)."""
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        # Logging may not yet be configured; fall back to stderr.
        sys.stderr.write(f"CRITICAL config.error {e}\n")
        return 1

    configure_logging(Path(cfg.general.log_dir))
    log.info("cycle.start config=%s", config_path)

    state_path = Path(cfg.general.state_file)
    state_map = state.load_state(state_path)

    overall_ok = True
    for board in cfg.boards:
        if not board.enabled:
            log.info("board.skip id=%s reason=disabled", board.id)
            continue
        try:
            _process_board(board, cfg, state_map, state_path)
        except Exception as e:  # noqa: BLE001
            overall_ok = False
            log.exception("board.failed id=%s err=%s", board.id, e)
            _safe_alert(cfg, f"❌ board {board.id} failed: {e}")

    state.save_state(state_path, state_map)
    log.info("cycle.end ok=%s", overall_ok)
    return 0 if overall_ok else 2


def _process_board(
    board: BoardConfig,
    cfg: Config,
    state_map: dict[str, BoardState],
    state_path: Path,
) -> None:
    board_state = state_map.get(
        board.id, BoardState(last_max_post_id=None, last_checked="", empty_streak=0)
    )

    posts = _fetch_posts_until_cutoff(board, cfg, board_state.last_max_post_id)

    if not posts:
        board_state.empty_streak += 1
        log.warning("parse.empty board=%s streak=%d", board.id, board_state.empty_streak)
        if board_state.empty_streak >= EMPTY_STREAK_ALERT_THRESHOLD:
            _safe_alert(
                cfg,
                f"⚠️ board {board.id} parsing returned empty {board_state.empty_streak} times — "
                "site structure may have changed",
            )
        state_map[board.id] = board_state
        return

    board_state.empty_streak = 0
    page_max_id = max(p.id for p in posts)

    if board_state.last_max_post_id is None:
        board_state.last_max_post_id = page_max_id
        board_state.last_checked = _now_iso()
        state_map[board.id] = board_state
        log.info("baseline.recorded board=%s watermark=%d", board.id, page_max_id)
        return

    new_posts: list[Post] = differ.diff(posts, watermark=board_state.last_max_post_id)
    log.info(
        "diff.computed board=%s watermark=%d new_count=%d",
        board.id,
        board_state.last_max_post_id,
        len(new_posts),
    )

    webhook_url = cfg.webhook_url(board.id)
    for post in new_posts:
        notifier.send(
            post,
            webhook_url=webhook_url,
            fmt=cfg.notification.format,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        board_state.last_max_post_id = post.id
        state_map[board.id] = board_state
        state.save_state(state_path, state_map)
        log.info("notify.ok board=%s post_id=%d", board.id, post.id)

    board_state.last_checked = _now_iso()
    state_map[board.id] = board_state


def _fetch_posts_until_cutoff(
    board: BoardConfig, cfg: Config, watermark: int | None
) -> list[Post]:
    posts: list[Post] = []
    for page in range(1, cfg.general.max_pages + 1):
        url = _with_page(board.url, page)
        html = fetcher.fetch(
            url,
            timeout=cfg.general.http_timeout_seconds,
            retries=cfg.general.http_retries,
        )
        try:
            page_posts = parser.parse(html)
        except parser.ParseEmptyError:
            # Page 1 empty → genuine empty/structure change. Page >1 empty →
            # treat as end of pagination and use what we already have.
            if page == 1:
                return []
            break
        posts.extend(page_posts)

        if watermark is None:
            break
        if min(p.id for p in page_posts) <= watermark:
            break
    return posts


def _with_page(url: str, page: int) -> str:
    if page == 1:
        return url
    parsed = urlparse(url)
    qs = dict(parse_qsl(parsed.query))
    qs["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(qs)))


def _safe_alert(cfg: Config, message: str) -> None:
    try:
        notifier.send_alert(message, webhook_url=cfg.alert_webhook_url)
    except Exception:  # noqa: BLE001
        log.exception("alert.send_failed")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cse_bot")
    p.add_argument(
        "--config",
        type=Path,
        default=Path("config/config.toml"),
        help="Path to config.toml",
    )
    args = p.parse_args(argv)
    return run_cycle(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_main.py -v
ruff check src/cse_bot/main.py tests/test_main.py
mypy src/cse_bot/main.py
```
Expected: green.

- [ ] **Step 5: Run full test suite for regression check**

```bash
pytest --cov=cse_bot --cov-report=term-missing -q
```
Expected: all tests pass, coverage ≥ 85% on `src/cse_bot/`.

- [ ] **Step 6: Commit**

```bash
git add src/cse_bot/main.py tests/test_main.py
git commit -m "feat(main): orchestrator with baseline, partial-failure, and page-2 logic"
```

- [ ] **Step 7: Gemini review** (skip until Task 12)

---

## Task 11: Self-alert on uncaught cycle failure

**Goal:** `main()` 진입 지점에서 예외를 잡아 self-alert webhook으로 알림.

**Files:**
- Modify: `src/cse_bot/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_main.py`:
```python
@respx.mock
def test_uncaught_exception_triggers_alert(
    cfg_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert_route = respx.post(ALERT).mock(return_value=httpx.Response(204))

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated catastrophic failure")

    # Force fetcher.fetch to blow up before any HTTP mock matches.
    monkeypatch.setattr("cse_bot.main.fetcher.fetch", boom)

    exit_code = run_cycle(cfg_file)
    assert exit_code != 0
    assert alert_route.called
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest tests/test_main.py::test_uncaught_exception_triggers_alert -v
```
Expected: depending on current behaviour either passes (board-level catch already routes here) or fails. If it fails, proceed to Step 3; if it passes, the wrap is already sufficient and proceed to Step 4.

- [ ] **Step 3: Wrap top level if needed**

Edit `src/cse_bot/main.py` and replace the `main()` function with:
```python
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cse_bot")
    p.add_argument(
        "--config",
        type=Path,
        default=Path("config/config.toml"),
        help="Path to config.toml",
    )
    args = p.parse_args(argv)
    try:
        return run_cycle(args.config)
    except Exception as e:  # noqa: BLE001
        # Last-line defence: log and try to alert.
        log.exception("cycle.unhandled err=%s", e)
        try:
            cfg = load_config(args.config)
            notifier.send_alert(
                f"❌ cse_bot cycle crashed: {e}", webhook_url=cfg.alert_webhook_url
            )
        except Exception:  # noqa: BLE001
            log.exception("alert.unreachable")
        return 1
```

- [ ] **Step 4: Run all tests**

```bash
pytest -v
ruff check src/ tests/
mypy src/
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/cse_bot/main.py tests/test_main.py
git commit -m "feat(main): self-alert on uncaught cycle failure"
```

- [ ] **Step 6: Gemini review** (skip until Task 12)

---

## Task 12: Gemini review automation

**Goal:** `scripts/gemini_review.sh` + 프롬프트 템플릿. 이 task가 ship되면 그 이후 모든 task는 Gemini PASS를 받고 진행한다. 또한 Task 1–11도 retroactively review를 돌려 PASS를 확인한다.

**Files:**
- Create: `scripts/gemini_review.sh`
- Create: `scripts/gemini_review_template.md`

- [ ] **Step 1: Create review template**

Create `scripts/gemini_review_template.md`:
```markdown
You are a strict senior code reviewer. Review the following changes for the task below.

# Acceptance criteria
The change must satisfy the task's stated goal, follow the project design (pure functions vs I/O separation, named modules), keep tests passing, and contain no obvious logic bugs, race conditions, or unhandled edge cases.

# Review checklist
1. Does the code satisfy the acceptance criteria of the task?
2. Are there logic bugs, race conditions, or unhandled edge cases?
3. Is the separation of pure functions vs I/O respected?
4. Are tests adequate? List missed edge cases if any.
5. Naming, readability, dead code?
6. Any security issues (secrets in code, unsafe HTTP, injection)?

# Required response format (strict)
VERDICT: PASS | FAIL
ISSUES:
  - <severity: blocker|major|minor> <file:line> <description>
SUGGESTIONS:
  - <optional improvements not blocking PASS>
SUMMARY: <one-line>

If you cannot determine PASS/FAIL with confidence, output VERDICT: FAIL with reason.
```

- [ ] **Step 2: Create review script**

Create `scripts/gemini_review.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <task-anchor>" >&2
    echo "example: $0 'docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-3'" >&2
    exit 64
fi

TASK_ANCHOR="$1"
DIFF_FILE="$(mktemp)"
PROMPT_FILE="$(mktemp)"
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$DIFF_FILE" "$PROMPT_FILE" "$RESPONSE_FILE"' EXIT

# 1. Diff scope: uncommitted changes (option A).
git diff HEAD > "$DIFF_FILE"

if ! [[ -s "$DIFF_FILE" ]]; then
    # No uncommitted changes → review the most recent commit instead, so we can
    # still verify a just-committed task.
    git diff HEAD~1 HEAD > "$DIFF_FILE"
fi

# 2. Test summary (assumes pytest already ran successfully before invocation).
TEST_SUMMARY="$(pytest -q 2>&1 | tail -3 || true)"
RUFF_SUMMARY="$(ruff check src/ tests/ 2>&1 | tail -3 || true)"
MYPY_SUMMARY="$(mypy src/ 2>&1 | tail -3 || true)"

# 3. Assemble prompt.
{
    cat scripts/gemini_review_template.md
    printf '\n# Task anchor\n%s\n' "$TASK_ANCHOR"
    printf '\n# Diff\n```diff\n'
    cat "$DIFF_FILE"
    printf '\n```\n'
    printf '\n# Test results\npytest:\n%s\nruff:\n%s\nmypy:\n%s\n' \
        "$TEST_SUMMARY" "$RUFF_SUMMARY" "$MYPY_SUMMARY"
} > "$PROMPT_FILE"

# 4. Call Gemini 3 Pro.
gemini -m gemini-3-pro < "$PROMPT_FILE" > "$RESPONSE_FILE"

# 5. Echo response and parse VERDICT.
cat "$RESPONSE_FILE"
echo "----"
VERDICT="$(grep -E '^VERDICT:' "$RESPONSE_FILE" | head -1 | awk '{print $2}' || true)"

if [[ "$VERDICT" == "PASS" ]]; then
    echo "✅ Gemini PASS for $TASK_ANCHOR"
    exit 0
else
    echo "❌ Gemini FAIL for $TASK_ANCHOR (verdict='$VERDICT')"
    exit 1
fi
```

- [ ] **Step 3: Make executable**

```bash
chmod +x scripts/gemini_review.sh
```

- [ ] **Step 4: Smoke test the script (skip if `gemini` CLI is unavailable in this environment)**

```bash
which gemini || echo "gemini CLI not found — install/configure separately and skip this smoke test"
```
If `gemini` is available, run a tiny dry call:
```bash
echo "ping" | gemini -m gemini-3-pro || echo "(adjust the model flag if -m gemini-3-pro is wrong; check 'gemini --help')"
```
If the flag name differs, edit `scripts/gemini_review.sh` line containing `gemini -m gemini-3-pro` to match the actual CLI syntax.

- [ ] **Step 5: Commit**

```bash
git add scripts/
git commit -m "tooling: add gemini_review.sh and prompt template"
```

- [ ] **Step 6: Retroactive review of Tasks 1–11**

For each prior task, check out the commit and run the script. The simplest approach: from current HEAD, walk back 11 commits and run the script per commit's diff:
```bash
for sha in $(git log --reverse --format=%H -n 11); do
    echo "=== reviewing $sha ==="
    git checkout "$sha"
    bash scripts/gemini_review.sh "retroactive:$sha" || echo "FAIL — record and address before proceeding"
done
git checkout main 2>/dev/null || git checkout -
```
If any task fails, follow the spec §11 loop (up to 10 fix attempts; report to user if still failing).

- [ ] **Step 7: Gemini review of Task 12 itself**

```bash
bash scripts/gemini_review.sh "docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-12"
```
Expected: PASS (or fix and retry).

---

## Task 13: launchd 배포

**Goal:** macOS launchd plist를 생성하고 README에 설치 절차를 명시.

**Files:**
- Create: `deploy/com.user.cse-bot.plist`

- [ ] **Step 1: Create plist**

Create `deploy/com.user.cse-bot.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.cse-bot</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/7bellaa/cseDiscordBot/.venv/bin/python</string>
        <string>-m</string>
        <string>cse_bot.main</string>
        <string>--config</string>
        <string>/Users/7bellaa/cseDiscordBot/config/config.toml</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/7bellaa/cseDiscordBot</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>

    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key><integer>9</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key><integer>18</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
    </array>

    <key>StandardOutPath</key>
    <string>/Users/7bellaa/cseDiscordBot/logs/launchd.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/7bellaa/cseDiscordBot/logs/launchd.stderr.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

- [ ] **Step 2: Validate plist syntax**

```bash
plutil -lint deploy/com.user.cse-bot.plist
```
Expected: `deploy/com.user.cse-bot.plist: OK`.

- [ ] **Step 3: Manual smoke run (still inside repo, no launchd yet)**

Ensure `.env` exists with real webhook URLs (not REPLACE_ME):
```bash
cp -n .env.example .env
# edit .env to set DISCORD_WEBHOOK_GENERAL and DISCORD_WEBHOOK_ALERT
source .venv/bin/activate
set -a; source .env; set +a
python -m cse_bot.main --config config/config.toml
echo "exit=$?"
ls -la data/ logs/
```
Expected:
- exit=0
- `data/state.json` created (baseline mode — `last_max_post_id` set, no Discord notification)
- `logs/cse_bot.log` populated

Verify in Discord: **no** notification arrived (this was a baseline run).

- [ ] **Step 4: Install plist (manual operation — confirm with user before running)**

```bash
cp deploy/com.user.cse-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.cse-bot.plist
launchctl list | grep cse-bot
```
Expected: agent listed.

Trigger immediately for end-to-end verification:
```bash
launchctl start com.user.cse-bot
sleep 5
tail -n 50 logs/cse_bot.log
tail -n 50 logs/launchd.stdout.log
```
Expected: cycle ran, exit 0. Since baseline already completed in Step 3, this run will show `diff.computed ... new_count=0` (no posts since baseline).

- [ ] **Step 5: Commit**

```bash
git add deploy/
git commit -m "deploy: launchd plist for 09:00/18:00 schedule"
```

- [ ] **Step 6: Gemini review**

```bash
bash scripts/gemini_review.sh "docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-13"
```
Expected: PASS.

---

## Task 14: README

**Goal:** 사용자가 다른 머신에서도 셋업할 수 있는 운영 문서.

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

Create `README.md`:
```markdown
# PNU CSE Discord Notification Bot

부산대학교 정보컴퓨터공학부 학부 공지사항(`https://cse.pusan.ac.kr/cse/14221/subview.do`)을 매일 09:00, 18:00 KST에 점검하여 신규 게시글을 Discord webhook으로 알림합니다.

## Requirements
- macOS
- Python 3.11+
- Discord 서버 + 채널별 webhook URL
- (옵션) Gemini CLI — 개발 시 task 자동 리뷰용

## Setup

```bash
git clone <this repo> ~/cseDiscordBot
cd ~/cseDiscordBot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# .env 편집: DISCORD_WEBHOOK_GENERAL, DISCORD_WEBHOOK_ALERT 채우기

# 베이스라인 실행 (알림 없이 현재 상태만 저장)
set -a; source .env; set +a
python -m cse_bot.main --config config/config.toml
```

## launchd 등록

```bash
cp deploy/com.user.cse-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.cse-bot.plist
launchctl list | grep cse-bot
```

즉시 1회 실행으로 동작 확인:
```bash
launchctl start com.user.cse-bot
tail -f logs/cse_bot.log
```

## 설정 변경

`config/config.toml`에서:
- `notification.format` — `minimal` / `medium` / `detailed`
- `[[boards]]` 섹션 추가로 게시판 확장 가능 (해당 `webhook_env` 환경변수 필요)

## 운영 메모
- macOS가 절전/꺼짐일 때 launchd 트리거를 놓칠 수 있음 → 09:00, 18:00에는 깨어 있어야 함
- 로그: `logs/cse_bot.log` (회전 5MB×5)
- 상태: `data/state.json` (워터마크). 손상 시 자동 백업 + 베이스라인 재시작
- 사이트 구조 변경으로 파싱이 3회 연속 빈 결과면 `DISCORD_WEBHOOK_ALERT` 채널로 알림

## Development

```bash
pytest --cov=cse_bot          # 테스트 + 커버리지
ruff check src/ tests/         # 린트
mypy src/                      # 타입 체크
```

각 task 완료 시:
```bash
bash scripts/gemini_review.sh "docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-N"
```
PASS 받으면 다음 task로 진행. 10회 실패 시 사용자에게 보고 후 일시 중지.

## 문서
- 디자인 스펙: `docs/superpowers/specs/2026-04-30-pnu-cse-discord-bot-design.md`
- 데이터 플로우 다이어그램: `docs/data-flow.md`
- 구현 계획: `docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md`

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.user.cse-bot.plist
rm ~/Library/LaunchAgents/com.user.cse-bot.plist
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, launchd, dev workflow"
```

- [ ] **Step 3: Gemini review**

```bash
bash scripts/gemini_review.sh "docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-14"
```
Expected: PASS.

---

## Task 15: Final smoke + acceptance check

**Goal:** 스펙 §16의 수용 기준을 모두 통과하는지 최종 확인.

- [ ] **Step 1: Run all tests with coverage**

```bash
source .venv/bin/activate
pytest --cov=cse_bot --cov-report=term-missing -v
```
Expected: all PASS. Pure modules ≥95%, I/O ≥80%, overall ≥85%.

- [ ] **Step 2: Verify launchd schedule**

```bash
launchctl list | grep cse-bot
plutil -p ~/Library/LaunchAgents/com.user.cse-bot.plist | grep -A 3 StartCalendarInterval
```
Expected: agent listed; 09:00 and 18:00 entries present.

- [ ] **Step 3: Verify gitignore safety**

```bash
git status --ignored
```
Expected: `.env`, `data/state.json`, `logs/*.log` listed under "Ignored files" — not staged or tracked.

- [ ] **Step 4: Manual webhook failure recovery test**

Temporarily break the webhook in `.env` (e.g., set `DISCORD_WEBHOOK_GENERAL` to a bogus URL with `https://discord.com/api/webhooks/0/0`). Run:
```bash
set -a; source .env; set +a
python -m cse_bot.main --config config/config.toml
echo "exit=$?"
tail -n 30 logs/cse_bot.log
```
Expected: non-zero exit, log shows notify failures, alert sent if there were new posts. Restore the correct webhook in `.env` afterwards.

- [ ] **Step 5: Final commit (if any tracked changes from smoke)**

```bash
git status
# Only commit non-runtime changes; data/, logs/, .env must stay untracked.
```

- [ ] **Step 6: Acceptance checklist (verify each box from spec §16)**

```
☐ launchd가 09:00/18:00에 봇을 트리거한다 (Step 2 above)
☐ 첫 실행 시 알림 0건, state.json에 워터마크 저장 (Task 13 Step 3)
☐ 두 번째 이후 실행에서 새 글이 있으면 medium 포맷으로 디스코드에 알림 (test_main + 실사용 관찰)
☐ 새 글이 없으면 알림 없이 정상 종료 (test_main "diff.computed new_count=0")
☐ webhook이 일시 실패해도 다음 사이클이 누락 글을 보낸다 (test_partial_failure_preserves_progress)
☐ HTML 파싱 3회 연속 빈 결과 → self-alert (코드 EMPTY_STREAK_ALERT_THRESHOLD)
☐ 모든 자동 테스트 통과 (Step 1)
☐ 모든 task가 Gemini 3 Pro PASS (Tasks 1–14)
☐ .env / state.json / logs/ git에 들어가지 않음 (Step 3)
```

- [ ] **Step 7: Gemini review of overall plan execution**

```bash
bash scripts/gemini_review.sh "docs/superpowers/plans/2026-04-30-pnu-cse-discord-bot.md#task-15"
```
Expected: PASS. Project ready for ongoing operation.
