# Calendar P0 Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four P0 items from `docs/superpowers/specs/2026-05-26-calendar-p0-improvements-spec.md` — event label readability, top-anchored collapsible legend, mobile-responsive layout, and WCAG 2.1 AA contrast — without introducing new dependencies or breaking the existing FullCalendar-backed static site.

**Architecture:** The site is a static page at `docs/calendar/index.html` with custom styles in `docs/calendar/style.css` and inline vanilla JS. Implementation is purely additive on those two files: bump CSS custom-property tokens for contrast, reposition the legend, restructure event chips inside `eventDidMount`, then layer mobile breakpoints over everything. Each phase ends with a focused commit that can be reverted independently.

**Tech Stack:** HTML5 · CSS custom properties · Vanilla JS · FullCalendar 6.1.10 (UMD via CDN) · `python -m http.server` for local dev · `@axe-core/cli` (npx) for accessibility checks · Browser DevTools device toolbar for cross-viewport screenshots.

---

## Files Touched

| File | Responsibility | Phases touching it |
|------|----------------|--------------------|
| `docs/calendar/style.css` | All visual tokens, layout, breakpoints, chip/tooltip styles | All |
| `docs/calendar/index.html` | Markup (header/legend/main) + inline `<script>` (renderers, toggles, view-switch) | All |
| `CHANGELOG.md` | Release notes for v1.1.0 | Phase 5 |
| `docs/superpowers/specs/2026-05-26-calendar-p0-improvements-spec.md` | Source spec — read-only reference | — |

**No new files.** Keeping JS inline avoids a second HTTP request for a ~250-line script. If the inline `<script>` exceeds ~400 lines after Phase 4, split into `docs/calendar/calendar.js` in a follow-up.

---

## Conventions

- **Commit style** (matches existing repo log): `feat(calendar): …` for behavior changes, `style(calendar): …` for pure CSS, `chore(calendar): …` for release prep. No body unless something non-obvious.
- **Verification per task**: dev server is already running on `http://localhost:8765/` (see existing `python -m http.server 8765 --directory docs/calendar`). If not, start it: `python -m http.server 8765 --directory docs/calendar &`.
- **Cache-busting during dev**: append `?v=N` to URLs when the browser caches old assets (Python's `SimpleHTTPServer` sends no `Cache-Control`).
- **Korean text in code**: keep as-is (UTF-8). No transliteration.
- **No emoji in code/comments** unless already present.

---

## Phase 0 · Smoke baseline (pre-flight, ~2 minutes)

Establish a working state so phase-end verifications are meaningful.

### Task 0: Confirm dev server + baseline render

**Files:** none (verification only)

- [ ] **Step 1: Confirm server**

```bash
curl -sI http://localhost:8765/ | head -3
```

Expected: `HTTP/1.0 200 OK`. If server is down, start it:
```bash
python -m http.server 8765 --directory docs/calendar &
```

- [ ] **Step 2: Confirm baseline page loads in a browser**

Open `http://localhost:8765/?v=baseline` in Chrome. Expected: existing layout with the recently added "마감일" hero, FullCalendar grid, bottom legend.

- [ ] **Step 3: Capture baseline screenshot for later diff**

In Chrome DevTools → Cmd+Shift+P → "Capture full size screenshot". Save to `~/Desktop/calendar-baseline-1280.png`. (Used for visual diff in Phase 5.)

---

## Phase 1 · P0-4 contrast tokens (D1, ~2 hours)

Foundation pass — all later tasks depend on the new token values.

### Task 1.1: Bump text-tertiary to AA-compliant gray

The existing `:root` text tokens use opacity (`rgba(0,0,0,0.35)` etc.). Opacity-based grays are convenient but `rgba(0,0,0,0.35)` over `#f7f7f5` resolves to ~`#a6a5a4` with a 2.85:1 contrast — fails WCAG AA (needs 4.5:1 for body text, 3:1 for non-text/large).

**Files:**
- Modify: `docs/calendar/style.css` (the `:root { ... }` block, ~lines 9–50)

- [ ] **Step 1: Edit the token block**

Replace the existing `/* Text (opacity 기반 — Notion 방식) */` block with the spec-aligned values:

```css
  /* Text — WCAG 2.1 AA validated against --bg-page (#f7f7f5).
     We move off pure opacity for the muted ramp so contrast is predictable. */
  --text: rgba(0, 0, 0, 0.9);          /* 14.9:1  — body, headings */
  --text-secondary: #4B5563;            /* 7.0:1   — header meta, labels */
  --text-tertiary: #6B7280;             /* 4.6:1   — captions, badges */
  --text-disabled: #9CA3AF;             /* 3.1:1   — adjacent-month dates */
  --text-quaternary: rgba(0, 0, 0, 0.22); /* decorative only, never on text */

  /* Component-specific (sampled in axe-core sweep) */
  --btn-today-fg: #374151;              /* 9.1:1   — today button text */
  --btn-today-bg: rgba(35, 131, 226, 0.08);
```

Leave every other variable in the block untouched.

- [ ] **Step 2: Update the few call-sites still using the old quaternary**

Search for stale references:
```bash
grep -n "text-quaternary\|--text-tertiary" docs/calendar/style.css
```

Expected: any rule that styled *text* with `--text-quaternary` needs to move to `--text-tertiary` or `--text-disabled`. (`--text-quaternary` is kept only because it may still be used for icons/dividers — purely decorative.)

If a grep hit reads like `color: var(--text-quaternary)` on a text element (e.g., `.badge`, `.github-link`, `.brand-subtitle`), change it to `--text-tertiary`.

- [ ] **Step 3: Verify in the browser**

Reload `http://localhost:8765/?v=p4-1`. Expected:
- The header `…건 마감 예정` badge now reads in a clearly darker gray (was nearly invisible).
- The `↗ GitHub` link is darker.
- The `brand-subtitle` is more readable.

- [ ] **Step 4: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): raise text tokens to WCAG AA contrast"
```

---

### Task 1.2: Adjust adjacent-month and today-button colors inside FullCalendar

FullCalendar paints adjacent-month cells via `.fc-day-other` and the today button via `.fc-today-button`. The current cascade lets them inherit muted grays that fail AA.

**Files:**
- Modify: `docs/calendar/style.css` (FullCalendar override section — add if missing)

- [ ] **Step 1: Add overrides at the bottom of style.css**

```css
/* ─── FullCalendar contrast overrides (P0-4) ──────────────────── */

/* Adjacent-month dates: visible but lower weight than current month. */
.fc .fc-day-other .fc-daygrid-day-number {
  color: var(--text-disabled);
  opacity: 1;            /* FC ships 0.3 — too faint */
}

/* "Today" button — make active state legible */
.fc .fc-today-button {
  color: var(--btn-today-fg);
  background-color: var(--btn-today-bg);
  border-color: transparent;
  font-weight: 500;
}
.fc .fc-today-button:disabled {
  color: var(--text-tertiary);
  background-color: transparent;
  opacity: 1;
}

/* Toolbar buttons in general */
.fc .fc-button-primary {
  color: var(--text-secondary);
  background-color: transparent;
  border-color: var(--border);
}
.fc .fc-button-primary:hover {
  color: var(--text);
  background-color: var(--bg-hover);
  border-color: var(--border);
}
.fc .fc-button-primary:not(:disabled).fc-button-active {
  color: var(--text);
  background-color: var(--accent-soft);
  border-color: var(--accent);
}
```

- [ ] **Step 2: Reload and verify**

`http://localhost:8765/?v=p4-2`. Expected:
- May/June grid: adjacent-month days (e.g., April 27–30 on the May grid, June 1–7 if visible) are clearly readable but visually subordinate to current-month days.
- "오늘" button looks like a real button, not disabled text.
- Active view (월/목록) button has a faint accent background.

- [ ] **Step 3: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): improve adjacent-month + toolbar button contrast"
```

---

### Task 1.3: Run axe-core baseline scan

Captures the current state so we can confirm by the end that all contrast violations are resolved.

**Files:** none (writes a JSON report to `/tmp/`)

- [ ] **Step 1: Run axe via npx**

```bash
npx -y @axe-core/cli http://localhost:8765/ --tags wcag2aa,wcag21aa --save /tmp/axe-after-p1.json 2>&1 | tail -20
```

Expected: a summary line `<N> violations`. Note the count for contrast specifically:

```bash
jq '[.[] | .violations[] | select(.id=="color-contrast") | .nodes | length] | add // 0' /tmp/axe-after-p1.json
```

Record the number. It should already be lower than before Phase 1; Phase 5 will verify it's 0.

> **If axe-core CLI is unavailable** (no npx, offline), substitute Chrome DevTools → Lighthouse → Accessibility category. Note the contrast-specific violations from the report.

- [ ] **Step 2: No commit** — this is a measurement only.

---

## Phase 2 · P0-2 legend repositioning (D1, ~2 hours)

Move the legend from the calendar footer to a sticky-ish bar between the toolbar and the grid, add collapse persistence.

### Task 2.1: Add the new top-anchored legend markup

**Files:**
- Modify: `docs/calendar/index.html` (insert above `<div id="calendar"></div>`)

- [ ] **Step 1: Insert legend bar after the existing `.hero` section**

In `docs/calendar/index.html`, find:

```html
    <section class="hero" aria-label="마감일 캘린더">
      <h1 class="hero-word">마감일</h1>
      <span class="hero-tag">DEADLINE · 해당 날짜에 마감되는 공지</span>
    </section>
    <div id="calendar"></div>
```

Replace with:

```html
    <section class="hero" aria-label="마감일 캘린더">
      <h1 class="hero-word">마감일</h1>
      <span class="hero-tag">DEADLINE · 해당 날짜에 마감되는 공지</span>
    </section>

    <div class="legend-bar" id="legend-bar" aria-label="카테고리 색상 범례">
      <div class="legend-bar__items" id="legend-bar-items">
        <span class="legend-chip" data-category="scholarship">
          <span class="legend-chip__dot" style="background:#8b5cf6"></span>
          <span class="legend-chip__label">장학/등록</span>
        </span>
        <span class="legend-chip" data-category="academic">
          <span class="legend-chip__dot" style="background:#14b8a6"></span>
          <span class="legend-chip__label">학업/수강</span>
        </span>
        <span class="legend-chip" data-category="career">
          <span class="legend-chip__dot" style="background:#ec4899"></span>
          <span class="legend-chip__label">졸업/진로</span>
        </span>
        <span class="legend-chip" data-category="extracurricular">
          <span class="legend-chip__dot" style="background:#f59e0b"></span>
          <span class="legend-chip__label">비교과/활동</span>
        </span>
        <span class="legend-chip" data-category="notice">
          <span class="legend-chip__dot" style="background:#6b7280"></span>
          <span class="legend-chip__label">일반공지</span>
        </span>
        <span class="legend-bar__divider" aria-hidden="true"></span>
        <span class="legend-chip">
          <span class="legend-chip__dot legend-chip__dot--ring"></span>
          <span class="legend-chip__label">★ 중요 일정</span>
        </span>
      </div>
      <button
        type="button"
        class="legend-bar__toggle"
        id="legend-toggle"
        aria-controls="legend-bar-items"
        aria-expanded="true"
        title="범례 접기/펼치기"
      >
        <span class="legend-bar__toggle-label">접기</span>
        <svg class="legend-bar__chevron" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
          <path d="M3 5l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>

    <div id="calendar"></div>
```

- [ ] **Step 2: Delete the old bottom legend**

In the same file, find:

```html
    <div class="legend" aria-label="카테고리 색상 범례">
      <span class="legend-item"><span class="dot" style="background:#8b5cf6"></span>장학/등록</span>
      <span class="legend-item"><span class="dot" style="background:#14b8a6"></span>학업/수강</span>
      <span class="legend-item"><span class="dot" style="background:#ec4899"></span>졸업/진로</span>
      <span class="legend-item"><span class="dot" style="background:#f59e0b"></span>비교과/활동</span>
      <span class="legend-item"><span class="dot" style="background:#6b7280"></span>일반공지</span>
      <span class="legend-divider"></span>
      <span class="legend-item"><span class="dot dot-ring"></span>★ 중요 일정</span>
    </div>
```

Delete the entire block.

- [ ] **Step 3: Verify markup loads**

```bash
curl -s http://localhost:8765/ | grep -c 'legend-bar\|legend-chip'
```

Expected: a non-zero count (at least 14).

```bash
curl -s http://localhost:8765/ | grep -c 'class="legend"'
```

Expected: `0` (old legend removed).

- [ ] **Step 4: No commit yet** — needs CSS in Task 2.2 to look right.

---

### Task 2.2: Style the new legend bar

**Files:**
- Modify: `docs/calendar/style.css` (replace the existing `.legend` block; remove `.legend-item`, `.dot`, `.dot-ring`, `.legend-divider` rules)

- [ ] **Step 1: Locate and remove old legend CSS**

Find the `/* Color legend (categories + ★ marker) */` block and delete the rules for `.legend`, `.legend-item`, `.dot`, `.dot-ring`, and `.legend-divider`. Replace with:

```css
/* ─── Legend bar (top-anchored, P0-2) ─────────────────────────── */

.legend-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  margin: 16px 4px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-card);
  font-size: 13px;
  color: var(--text-secondary);
}

.legend-bar__items {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 18px;
  min-width: 0;
  overflow: hidden;
  transition: max-height 0.18s ease, opacity 0.18s ease;
  max-height: 200px;
  opacity: 1;
}

.legend-bar--collapsed .legend-bar__items {
  max-height: 0;
  opacity: 0;
  pointer-events: none;
}

.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: default;
}

.legend-chip__dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}

.legend-chip__dot--ring {
  background: transparent;
  border: 2px solid rgb(245, 184, 0);
}

.legend-chip__label {
  white-space: nowrap;
}

.legend-bar__divider {
  width: 1px;
  height: 16px;
  background: var(--border);
  display: inline-block;
}

.legend-bar__toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: inherit;
  font-size: 12px;
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  padding: 4px 8px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
  flex-shrink: 0;
}
.legend-bar__toggle:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.legend-bar__toggle:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}

.legend-bar__chevron {
  transition: transform 0.18s ease;
}
.legend-bar--collapsed .legend-bar__chevron {
  transform: rotate(180deg);
}
.legend-bar--collapsed .legend-bar__toggle-label::before {
  content: "펼치기";
}
.legend-bar--collapsed .legend-bar__toggle-label {
  font-size: 0; /* hide "접기" text when collapsed; ::before shows "펼치기" */
}
.legend-bar--collapsed .legend-bar__toggle-label::before {
  font-size: 12px;
}
```

- [ ] **Step 2: Reload and verify visual state**

`http://localhost:8765/?v=p2-2`. Expected:
- A horizontal legend bar sits between the hero and the calendar.
- Five colored dots + category labels, divider, then `★ 중요 일정`.
- A `접기 ▾` button on the right.
- Bottom of the page no longer has a duplicate legend.

- [ ] **Step 3: Commit (markup + CSS together)**

```bash
git add docs/calendar/index.html docs/calendar/style.css
git commit -m "feat(calendar): move legend to top of calendar with collapse toggle"
```

---

### Task 2.3: Wire up the collapse toggle with localStorage

**Files:**
- Modify: `docs/calendar/index.html` (inline `<script>` block, near the top of the IIFE)

- [ ] **Step 1: Add the toggle handler inside the existing IIFE**

In the `<script>` block at the bottom of `index.html`, find the start of the IIFE:

```js
    (function () {
      // 5-category canonical palette — keep in sync with src/cse_bot/category.py
```

Insert this block immediately *before* that palette declaration:

```js
      // ─── Legend collapse toggle (P0-2) ──────────────────────────
      const LEGEND_COLLAPSED_KEY = "legend.collapsed";
      const legendBar = document.getElementById("legend-bar");
      const legendToggle = document.getElementById("legend-toggle");
      if (legendBar && legendToggle) {
        const initiallyCollapsed =
          localStorage.getItem(LEGEND_COLLAPSED_KEY) === "true";
        if (initiallyCollapsed) {
          legendBar.classList.add("legend-bar--collapsed");
          legendToggle.setAttribute("aria-expanded", "false");
        }
        legendToggle.addEventListener("click", () => {
          const collapsed = legendBar.classList.toggle("legend-bar--collapsed");
          legendToggle.setAttribute("aria-expanded", String(!collapsed));
          try {
            localStorage.setItem(LEGEND_COLLAPSED_KEY, String(collapsed));
          } catch (e) {
            // localStorage blocked (private mode) — ignore, state lives in memory
          }
        });
      }
```

- [ ] **Step 2: Verify in browser**

Reload `http://localhost:8765/?v=p2-3`. Click `접기`. The legend chips collapse to height 0, chevron flips, label flips to `펼치기`. Reload — legend stays collapsed.

Click `펼치기`. Legend re-opens. Reload — stays open.

- [ ] **Step 3: Verify keyboard access**

Tab to the toggle button. Press `Enter` or `Space` — toggle fires. Focus ring is visible.

- [ ] **Step 4: Commit**

```bash
git add docs/calendar/index.html
git commit -m "feat(calendar): persist legend collapse state in localStorage"
```

---

## Phase 3 · P0-1 event label readability (D2–D3, ~6 hours)

Replace the single-line title with a category chip + 2-line clamped title, swap FullCalendar's default popover for an accessible one, ensure keyboard focus exposes the full title.

### Task 3.1: Add category mapping & swap chip render

`extendedProps.category` in `events.json` carries the full canonical name (e.g., `"장학/등록"`). FullCalendar's `eventDidMount` is the place to restructure the chip DOM.

**Files:**
- Modify: `docs/calendar/index.html` (inline `<script>`)

- [ ] **Step 1: Add category metadata table**

Inside the IIFE, just below the existing `palette` constant, add:

```js
      // Canonical category → (short chip text, machine-readable token)
      // Keep keys in sync with src/cse_bot/category.py CLASSIFICATION_PALETTE.
      const categoryMeta = {
        "장학/등록":  { short: "장학",   key: "scholarship" },
        "학업/수강":  { short: "학업",   key: "academic" },
        "졸업/진로":  { short: "졸업",   key: "career" },
        "비교과/활동": { short: "비교과", key: "extracurricular" },
        "일반공지":   { short: "공지",   key: "notice" },
      };
      const defaultCategoryMeta = { short: "공지", key: "notice" };

      function metaFor(cat) {
        return categoryMeta[cat] || defaultCategoryMeta;
      }
```

- [ ] **Step 2: Replace the existing `eventDidMount` body**

Find the existing `eventDidMount: function (info) { ... }` and replace its body with:

```js
        eventDidMount: function (info) {
          const cat = info.event.extendedProps.category || "일반공지";
          const meta = metaFor(cat);
          const important = !!info.event.extendedProps.important;
          const stripped = stripPrefix(info.event.title);

          // a11y / native tooltip fallback
          info.el.setAttribute(
            "title",
            (important ? "★ " : "") + info.event.title + ` [${cat}]`
          );
          info.el.setAttribute(
            "aria-label",
            `${meta.short} 카테고리, ${stripped}` + (important ? ", 중요 일정" : "")
          );
          info.el.setAttribute("data-category", meta.key);
          if (important) info.el.classList.add("fc-event-important");

          // Rebuild chip contents: [tag][title (2-line clamp)]
          const titleTarget =
            info.el.querySelector(".fc-event-title") ||
            info.el.querySelector(".fc-list-event-title a") ||
            info.el.querySelector(".fc-list-event-title");
          if (titleTarget) {
            titleTarget.classList.add("event-chip__title");
            titleTarget.textContent = (important ? "★ " : "") + stripped;
          }

          // In grid view, prepend the category tag chip if not present
          const mainEl = info.el.querySelector(".fc-event-main-frame") || info.el.querySelector(".fc-event-main");
          if (mainEl && !mainEl.querySelector(".chip-tag")) {
            const tag = document.createElement("span");
            tag.className = "chip-tag";
            tag.textContent = meta.short;
            mainEl.insertBefore(tag, mainEl.firstChild);
          }
        },
```

- [ ] **Step 3: Verify markup in DOM**

Reload `http://localhost:8765/?v=p1-1`. Open DevTools → Elements → pick a calendar event. Confirm structure roughly:

```html
<a class="fc-daygrid-event …" data-category="scholarship" ...>
  <div class="fc-event-main">
    <span class="chip-tag">장학</span>
    <div class="fc-event-main-frame">
      <div class="fc-event-title event-chip__title">2026.2학기 주거안정장학금 신청 안내</div>
    </div>
  </div>
</a>
```

(Exact wrapper class names may vary by FullCalendar version, but `.chip-tag` and `.event-chip__title` must both be present.)

- [ ] **Step 4: Commit**

```bash
git add docs/calendar/index.html
git commit -m "feat(calendar): emit category chip tag + a11y metadata on events"
```

---

### Task 3.2: Style the category chip + multi-line title

**Files:**
- Modify: `docs/calendar/style.css`

- [ ] **Step 1: Add chip + title styles near the end of style.css**

```css
/* ─── Event chip (P0-1) ───────────────────────────────────────── */

.fc-daygrid-event {
  padding: 3px 6px;
  min-height: 28px;
  line-height: 1.25;
}

.fc-daygrid-event .fc-event-main {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.chip-tag {
  flex-shrink: 0;
  display: inline-block;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.4;
  color: #ffffff;
  background: var(--text-secondary); /* overridden by data-category */
  border-radius: 3px;
  letter-spacing: 0.02em;
  max-width: 60px;
  white-space: nowrap;
}

.fc-daygrid-event[data-category="scholarship"]    .chip-tag { background: #6d3fcf; }
.fc-daygrid-event[data-category="academic"]       .chip-tag { background: #0d8a7e; }
.fc-daygrid-event[data-category="career"]         .chip-tag { background: #c93a7f; }
.fc-daygrid-event[data-category="extracurricular"] .chip-tag { background: #c97d05; }
.fc-daygrid-event[data-category="notice"]         .chip-tag { background: #4b5563; }

.event-chip__title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: keep-all;
  line-height: 1.25;
  font-size: 12px;
  color: var(--text);
}

/* Important: subtle gold outline overlay on the whole chip */
.fc-event-important {
  outline: 1.5px solid rgb(245, 184, 0);
  outline-offset: -1px;
}

/* List view: same chip-tag styling but inline with the dot column */
.fc-list-event .chip-tag {
  margin-right: 8px;
}
```

> Chip background colors are slightly darker than the dot palette so white text hits ≥4.5:1 — values were chosen to pass AA against `#ffffff`.

- [ ] **Step 2: Verify visual**

Reload `?v=p1-2`. Each event chip should now show a small colored badge (장학/학업/졸업/비교과/공지) on the left and a 2-line title on the right. Long titles wrap to 2 lines instead of truncating to ellipsis.

Inspect the DevTools Accessibility tree for one chip — the `aria-label` reads e.g. `"장학 카테고리, 2026.2학기 주거안정장학금 신청 안내, 중요 일정"`.

- [ ] **Step 3: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): category tag chip + two-line title clamp"
```

---

### Task 3.3: Cap to 3 events per cell, use FullCalendar's popover for overflow

The spec asks for `+N건 더보기` at the bottom of overflowing cells. FullCalendar already ships `dayMaxEvents` + `moreLinkClick: "popover"` — use that instead of building a custom panel (DRY, YAGNI, ~30 lines of native behavior).

**Files:**
- Modify: `docs/calendar/index.html` (FullCalendar config block)

- [ ] **Step 1: Update config options**

Inside the `new FullCalendar.Calendar(calendarEl, { ... })` config block, find:

```js
        dayMaxEvents: 3,
        displayEventTime: false,
```

Replace with:

```js
        dayMaxEvents: 3,
        moreLinkClick: "popover",
        moreLinkText: (n) => `+ ${n}건 더보기`,
        displayEventTime: false,
```

- [ ] **Step 2: Style the popover so chips render correctly inside it**

Append to `style.css`:

```css
/* "+N건 더보기" link + popover */
.fc .fc-daygrid-more-link {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
  padding: 2px 4px;
}
.fc .fc-daygrid-more-link:hover {
  color: var(--text);
  background: var(--bg-hover);
  border-radius: var(--r-sm);
}

.fc-popover {
  background: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow-popover) !important;
  border-radius: var(--r-md) !important;
  overflow: hidden;
}
.fc-popover .fc-popover-header {
  background: var(--bg-subtle);
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 12px;
}
.fc-popover .fc-popover-body { padding: 8px; }
```

- [ ] **Step 3: Inject 5+ events on the same day to test**

In DevTools console, run a quick visual probe:

```js
calendar.getEvents().slice(0,5).forEach((e,i)=>calendar.addEvent({
  id: `dbg-${i}`, title: `[테스트] 더미 일정 ${i+1}`, start: "2026-05-29",
  color: "#6b7280", extendedProps:{ category:"일반공지", important:false }
}));
```

Expected: May 29 cell shows 3 chips and a `+ N건 더보기`. Click it → popover lists all events on that day.

Clean up:
```js
calendar.getEvents().filter(e=>e.id.startsWith("dbg-")).forEach(e=>e.remove());
```

- [ ] **Step 4: Commit**

```bash
git add docs/calendar/index.html docs/calendar/style.css
git commit -m "feat(calendar): cap cells at 3 events + styled overflow popover"
```

---

### Task 3.4: Accessible tooltip for keyboard focus

`title=` attributes only show on mouse hover. Keyboard users need an actual tooltip element bound by `aria-describedby`. Implement a single shared tooltip that follows focus.

**Files:**
- Modify: `docs/calendar/index.html` (markup + script)

- [ ] **Step 1: Add the tooltip element near the end of `<body>`**

Just before the existing `<script>` block (or before any other final scripts):

```html
  <div
    id="event-tooltip"
    class="event-tooltip"
    role="tooltip"
    hidden
    aria-hidden="true"
  ></div>
```

- [ ] **Step 2: Append tooltip CSS**

```css
/* ─── Tooltip (P0-1c) ─────────────────────────────────────────── */
.event-tooltip {
  position: absolute;
  z-index: 50;
  max-width: 320px;
  padding: 8px 12px;
  background: rgba(15, 17, 21, 0.92);
  color: #ffffff;
  font-size: 12.5px;
  line-height: 1.4;
  border-radius: var(--r-sm);
  pointer-events: none;
  box-shadow: var(--shadow-popover);
  opacity: 0;
  transition: opacity 0.12s ease;
}
.event-tooltip[data-visible="true"] {
  opacity: 1;
}

/* Disable hover tooltip on touch — focus path still works */
@media (hover: none) {
  .event-tooltip { display: none; }
}
```

- [ ] **Step 3: Wire up show/hide in the IIFE**

Inside the IIFE (after the legend toggle block, before the FullCalendar constructor), add:

```js
      // ─── Shared event tooltip (P0-1c) ────────────────────────────
      const tooltipEl = document.getElementById("event-tooltip");
      let tooltipTimer = null;

      function positionTooltip(anchor) {
        const rect = anchor.getBoundingClientRect();
        const tipRect = tooltipEl.getBoundingClientRect();
        const top = window.scrollY + rect.bottom + 6;
        let left = window.scrollX + rect.left;
        // keep tooltip on-screen
        const maxLeft = window.scrollX + document.documentElement.clientWidth - tipRect.width - 8;
        if (left > maxLeft) left = Math.max(8, maxLeft);
        tooltipEl.style.top = `${top}px`;
        tooltipEl.style.left = `${left}px`;
      }

      function showTooltip(anchor, text) {
        if (!tooltipEl || !text) return;
        clearTimeout(tooltipTimer);
        tooltipTimer = setTimeout(() => {
          tooltipEl.textContent = text;
          tooltipEl.hidden = false;
          tooltipEl.setAttribute("aria-hidden", "false");
          positionTooltip(anchor);
          tooltipEl.setAttribute("data-visible", "true");
        }, 250);
      }

      function hideTooltip() {
        clearTimeout(tooltipTimer);
        if (!tooltipEl) return;
        tooltipEl.removeAttribute("data-visible");
        tooltipEl.hidden = true;
        tooltipEl.setAttribute("aria-hidden", "true");
      }

      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") hideTooltip();
      });
```

- [ ] **Step 4: Bind events to tooltip in `eventDidMount`**

Inside the existing `eventDidMount` (the one rebuilt in Task 3.1), append these listeners just before its closing brace:

```js
          const fullText = (important ? "★ " : "") + stripped + ` · [${cat}]`;
          info.el.setAttribute("aria-describedby", "event-tooltip");
          info.el.addEventListener("mouseenter", () => showTooltip(info.el, fullText));
          info.el.addEventListener("mouseleave", hideTooltip);
          info.el.addEventListener("focus", () => showTooltip(info.el, fullText));
          info.el.addEventListener("blur", hideTooltip);
```

- [ ] **Step 5: Verify**

Reload `?v=p1-4`.
- Mouse hover an event → tooltip appears after 250ms with full title + category.
- Tab to an event from the keyboard → same tooltip appears (focus ring also visible).
- Press `Escape` → tooltip hides.
- Scroll the page → tooltip repositions (it won't, since it's `position: absolute` from `body`; that's fine — the next focus event repositions it).

- [ ] **Step 6: Commit**

```bash
git add docs/calendar/index.html docs/calendar/style.css
git commit -m "feat(calendar): accessible keyboard tooltip for event chips"
```

---

## Phase 4 · P0-3 mobile responsive (D4, ~5 hours)

Add a mobile-first layer that stacks the header, wraps the toolbar, makes the legend horizontally scrollable, and auto-switches to list view under 768px (preserving explicit user choice via `sessionStorage`).

### Task 4.1: Add breakpoint scaffolding + page-level resets

**Files:**
- Modify: `docs/calendar/style.css` (append at end)

- [ ] **Step 1: Append responsive primitives**

```css
/* ─── Responsive layer (P0-3) ─────────────────────────────────── */

html, body { overflow-x: hidden; }

main {
  max-width: 1080px;
  margin: 28px auto;
  padding: 0 20px 80px;
}

/* md: tablet portrait and small laptops */
@media (max-width: 768px) {
  main { margin: 16px auto; padding: 0 14px 64px; }
  #calendar { padding: 14px; }
  .hero { gap: 12px; margin: 4px 0 16px; }
  .hero-word { font-size: 64px; }
  .hero-tag { padding-bottom: 10px; font-size: 12px; }
}

/* sm: phones */
@media (max-width: 480px) {
  main { padding: 0 10px 56px; }
  #calendar { padding: 10px; border-radius: var(--r-md); }
  .hero-word { font-size: 48px; border-bottom-width: 4px; }
  .hero-tag { display: none; } /* keep page airy on small screens */
}
```

- [ ] **Step 2: Verify on emulated viewport**

DevTools → device toolbar → iPhone SE (375×667). Reload `?v=p3-1`. Page width matches viewport (no horizontal scroll). The hero "마감일" shrinks to ~48px and the inline tag is hidden.

- [ ] **Step 3: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): mobile breakpoints + page-width resets"
```

---

### Task 4.2: Stack the header vertically under 768px

**Files:**
- Modify: `docs/calendar/style.css`

- [ ] **Step 1: Append header-stack rules**

```css
@media (max-width: 768px) {
  .site-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    padding: 14px 18px;
  }
  .site-head .meta {
    width: 100%;
    justify-content: space-between;
  }
  .brand-subtitle {
    margin-top: 4px;
    line-height: 1.4;
  }
}
```

- [ ] **Step 2: Verify**

Reload `?v=p3-2` at 375px. Title, subtitle, and the `…건 마감 예정 / ↗ GitHub` row stack vertically — no clipping, no horizontal overflow.

- [ ] **Step 3: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): stack site header on small viewports"
```

---

### Task 4.3: Horizontal-scroll legend bar on mobile

**Files:**
- Modify: `docs/calendar/style.css`

- [ ] **Step 1: Append legend mobile rules**

```css
@media (max-width: 768px) {
  .legend-bar {
    padding: 8px 10px;
    margin: 12px 0 12px;
    overflow: hidden;
  }
  .legend-bar__items {
    flex-wrap: nowrap;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    gap: 14px;
    padding-bottom: 4px;
    -webkit-overflow-scrolling: touch;
  }
  .legend-bar__items::-webkit-scrollbar { height: 4px; }
  .legend-bar__items::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 2px;
  }
  .legend-chip { scroll-snap-align: start; }
  .legend-bar__divider { display: none; }
  .legend-bar__toggle-label { display: none; } /* save space; chevron only */
  .legend-bar__toggle { padding: 6px; }
}
```

- [ ] **Step 2: Verify**

At 375px viewport, the legend bar shows a horizontally scrollable strip of chips. The chevron-only toggle still collapses/expands. No vertical wrapping, no page overflow.

- [ ] **Step 3: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): horizontal-scroll legend chips on mobile"
```

---

### Task 4.4: Toolbar two-row layout + larger touch targets

**Files:**
- Modify: `docs/calendar/style.css` and `docs/calendar/index.html` (FullCalendar config)

- [ ] **Step 1: Append toolbar mobile rules to CSS**

```css
@media (max-width: 768px) {
  .fc .fc-toolbar.fc-header-toolbar {
    flex-direction: column;
    gap: 8px;
    align-items: stretch;
    margin-bottom: 12px;
  }
  .fc .fc-toolbar-chunk {
    display: flex;
    justify-content: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .fc .fc-toolbar-title {
    font-size: 16px;
    text-align: center;
  }
  .fc .fc-button {
    min-height: 44px; /* touch target */
    min-width: 44px;
    padding: 0 12px;
    font-size: 14px;
  }
  .fc .fc-toolbar-chunk:first-child .fc-button-group { width: 100%; }
}
```

- [ ] **Step 2: Verify**

At 375px, the toolbar shows three rows (prev/today/next, then month title, then view toggle), each row centered with at-least 44px-tall buttons.

- [ ] **Step 3: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): mobile toolbar wrap + 44px touch targets"
```

---

### Task 4.5: Auto-switch to list view on mobile, preserve explicit choice

**Files:**
- Modify: `docs/calendar/index.html` (inline `<script>`)

- [ ] **Step 1: Add view-preference helpers near the top of the IIFE**

Just below the `categoryMeta` block from Task 3.1, add:

```js
      // ─── View preference + auto list-view on mobile (P0-3) ──────
      const VIEW_PREF_KEY = "view.preference";
      const MOBILE_MAX_PX = 768;

      function preferredInitialView() {
        const explicit = sessionStorage.getItem(VIEW_PREF_KEY);
        if (explicit === "dayGridMonth" || explicit === "listMonth") return explicit;
        return window.innerWidth <= MOBILE_MAX_PX ? "listMonth" : "dayGridMonth";
      }

      function rememberView(viewName) {
        try { sessionStorage.setItem(VIEW_PREF_KEY, viewName); } catch (e) {}
      }
```

- [ ] **Step 2: Use it in the FullCalendar config**

Find:

```js
        initialView: "dayGridMonth",
```

Replace with:

```js
        initialView: preferredInitialView(),
```

Then find the `loading: function (isLoading) { ... }` block and add a sibling `datesSet` callback right above it:

```js
        datesSet: function (info) {
          rememberView(info.view.type);
        },
```

- [ ] **Step 3: Verify desktop behavior unchanged**

At 1280px: page still opens in 월 (month) view. Switch to 목록 view, refresh — should reopen in 목록 (sessionStorage holds explicit choice).

Close the tab + reopen (sessionStorage clears on tab close). Page reopens in 월 (auto fallback at desktop width).

- [ ] **Step 4: Verify mobile behavior**

At 375px (or new private window emulating): first load → 목록 view automatically. Switch to 월 → refresh → still 월 (explicit choice). Close + reopen tab → back to 목록 (no stored choice).

- [ ] **Step 5: Commit**

```bash
git add docs/calendar/index.html
git commit -m "feat(calendar): auto list view on mobile, sessionStorage preserves choice"
```

---

### Task 4.6: List-view styling polish (touch + sticky day headers)

**Files:**
- Modify: `docs/calendar/style.css`

- [ ] **Step 1: Append list-view rules**

```css
/* ─── List view polish (P0-3c) ────────────────────────────────── */
.fc .fc-list {
  background: var(--bg-card);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  overflow: hidden;
}
.fc .fc-list-day-cushion {
  background: var(--bg-subtle) !important;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 14px;
  position: sticky;
  top: 0;
  z-index: 2;
}
.fc .fc-list-event {
  cursor: pointer;
}
.fc .fc-list-event td {
  padding: 12px 14px;
  font-size: 14px;
  min-height: 44px;
}
.fc .fc-list-event-dot { display: none; } /* dot replaced by chip-tag */
.fc .fc-list-empty {
  color: var(--text-secondary);
  padding: 32px 16px;
  text-align: center;
}

@media (max-width: 480px) {
  .fc .fc-list-event-time {
    display: none; /* dates have no time component anyway */
  }
}
```

- [ ] **Step 2: Verify in list view at 375px**

Switch to 목록 view. Each day section header should stick to the top while you scroll its events. Each event row is ≥ 44px tall (touch-friendly), has the category chip on the left, full title following.

- [ ] **Step 3: Commit**

```bash
git add docs/calendar/style.css
git commit -m "style(calendar): list view sticky headers + 44px event rows"
```

---

## Phase 5 · Validation & release (D5, ~3 hours)

### Task 5.1: Final axe-core sweep (target: 0 contrast violations)

**Files:** none

- [ ] **Step 1: Run axe at the three target viewports**

```bash
npx -y @axe-core/cli http://localhost:8765/ \
  --tags wcag2aa,wcag21aa \
  --save /tmp/axe-final-desktop.json 2>&1 | tail -10
```

For mobile breakpoints, axe-core CLI can't emulate viewport directly — instead resize via Chrome DevTools (Device Toolbar) and run **axe DevTools extension** at 390px and 768px. Save findings to `~/Desktop/axe-mobile-{390,768}.json`.

- [ ] **Step 2: Confirm zero contrast violations**

```bash
jq '[.[] | .violations[] | select(.id=="color-contrast") | .nodes | length] | add // 0' /tmp/axe-final-desktop.json
```

Expected: `0`. If non-zero, inspect the report, identify the offending selector, tweak its color (usually bumping the foreground darker or background lighter), commit a `style(calendar): fix axe contrast on X` fix-up, re-run.

- [ ] **Step 3: Confirm no new violations of other categories**

```bash
jq '[.[] | .violations[].id] | unique' /tmp/axe-final-desktop.json
```

Compare against the Phase 1 baseline. The list should be **same-or-shorter**. Address any newly introduced rule.

- [ ] **Step 4: No commit yet** — report findings into Task 5.4's CHANGELOG entry.

---

### Task 5.2: Cross-viewport screenshot pairs

**Files:** screenshots saved to `~/Desktop/` (not committed)

- [ ] **Step 1: Capture before/after at 360 / 390 / 768 / 1280**

For each viewport, in DevTools device toolbar:

1. Set viewport width (Responsive mode).
2. Reload page with `?v=final`.
3. Cmd+Shift+P → "Capture full size screenshot" → save as `calendar-after-<W>.png` to `~/Desktop/`.
4. Confirm the Phase 0 baseline shot exists for the same widths (recapture if missing — note the visual reference for the spec's diff requirement).

- [ ] **Step 2: Eyeball verification against spec acceptance criteria**

For each width, mentally tick off the spec's "수용 기준":
- 1280px: 2-line labels readable, top legend visible, today button accent visible.
- 768px: list view default, header stacked, toolbar wraps.
- 390px: no horizontal scroll, legend horizontally scrollable, hero shrinks.
- 360px: same as 390px but tighter padding.

Flag any failure → return to the corresponding Phase task for a fix-up commit.

- [ ] **Step 3: No commit** — screenshots stay local (no asset bloat in repo).

---

### Task 5.3: Keyboard-only walkthrough

**Files:** none (manual verification)

- [ ] **Step 1: Verify focus order**

Open the page at 1280px, click in the URL bar, then Tab through:

1. Skip-to-content or first focusable → site head link
2. Hero → no interactive (correct)
3. Legend toggle button
4. Toolbar buttons (prev, next, today, month/list)
5. First event chip in the grid
6. Subsequent events left→right, top→bottom

Each focus stop must have a visible `:focus-visible` outline.

- [ ] **Step 2: Verify tooltip on focus**

Tab onto an event chip → tooltip appears after 250ms. Press Escape → tooltip hides. Tab to next event → tooltip re-appears.

- [ ] **Step 3: Verify popover keyboard access**

Tab to a `+ N건 더보기` link → press Enter → FullCalendar popover opens. Esc closes it. Focus returns to the more-link (FullCalendar default).

- [ ] **Step 4: No commit** — note any gaps for follow-up.

---

### Task 5.4: CHANGELOG + final commit

**Files:**
- Create or modify: `CHANGELOG.md` (repo root)

- [ ] **Step 1: Check whether CHANGELOG.md exists**

```bash
ls CHANGELOG.md 2>/dev/null || echo "missing"
```

If missing, create it with this initial content:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
```

- [ ] **Step 2: Add the v1.1.0 entry**

Insert below `## [Unreleased]`:

```markdown
## [1.1.0] — 2026-05-26

### Calendar UI · P0 batch
- **P0-1** Event chips show category text tag (장학/학업/졸업/비교과/공지) plus a 2-line title clamp; cells cap at 3 events with a styled `+ N건 더보기` popover.
- **P0-1** Accessible tooltip on hover *and* keyboard focus, dismissible via Escape.
- **P0-2** Color legend moved from the calendar footer to a top-anchored bar between hero and grid; collapse state persists in `localStorage`.
- **P0-3** Mobile-responsive layer (≤768px): header stacks vertically, toolbar wraps with 44px touch targets, legend chips scroll horizontally, calendar auto-switches to list view (explicit user choice preserved via `sessionStorage`).
- **P0-4** Text tokens raised to WCAG 2.1 AA contrast (`--text-tertiary` 4.6:1, `--text-disabled` 3.1:1, today-button + header-meta foregrounds reworked); category chip backgrounds tuned so white text passes 4.5:1.

### Tooling
- axe-core sweep added to release checklist (target: 0 contrast violations).
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "chore: changelog entry for v1.1.0 calendar P0 batch"
```

- [ ] **Step 4: Tag the release commit (optional, ask the user first)**

```bash
git tag -a v1.1.0 -m "Calendar P0 improvements"
```

> Don't push the tag without explicit user confirmation — tags are remote-visible.

---

## Self-Review Checklist (executed before handoff)

**Spec coverage** — every numbered section in the spec maps to at least one task:
- §1 P0-1 (a) multi-line → Task 3.2
- §1 P0-1 (b) chip+text → Tasks 3.1, 3.2
- §1 P0-1 (c) tooltip a11y → Task 3.4
- §1 P0-1 cell overflow `+N건` → Task 3.3
- §2 P0-2 top legend → Tasks 2.1, 2.2
- §2 P0-2 toggle + localStorage → Task 2.3
- §2 P0-2 remove bottom legend → Task 2.1 step 2
- §3 P0-3 breakpoints sm/md/lg → Task 4.1
- §3 P0-3 mobile header stack → Task 4.2
- §3 P0-3 mobile toolbar wrap → Task 4.4
- §3 P0-3 mobile legend scroll → Task 4.3
- §3 P0-3 auto list view + sessionStorage → Task 4.5
- §3 P0-3 list view polish → Task 4.6
- §4 P0-4 token bump → Task 1.1
- §4 P0-4 component-specific contrast → Task 1.2
- §4 P0-4 chip text contrast → Task 3.2 (chip background values darkened)
- §5.1 focus-visible + a11y attrs → Tasks 2.3, 3.1, 3.4, 4.4 (touch targets)
- §5.3 perf budget — no new dependencies anywhere ✓
- §5.7 release checklist → Tasks 5.1–5.4

**No placeholders** — every step shows the exact code or command. No TODO / TBD.

**Type/name consistency** — `categoryMeta` keys identical across Tasks 3.1, 3.2, 3.4; `data-category` token values identical across HTML (Task 2.1), JS (Task 3.1), and CSS (Task 3.2); localStorage key strings (`legend.collapsed`, `view.preference`) referenced consistently.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-26-calendar-p0-improvements-plan.md`.
