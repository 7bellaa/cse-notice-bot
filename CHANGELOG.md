# Changelog

All notable changes to this project will be documented in this file.

## v2.0.0 — 2026-05-27 — Snapshot Calendar

### Breaking
- Calendar data source moves from `state.deadlines` (incremental) to
  `data/post_cache.json` (snapshot). Run `scripts/migrate_to_v2.py` once
  before the first v2 cycle.

### Added
- `src/cse_bot/post_cache.py` — PostCache I/O, content_hash, TTL prune.
- `src/cse_bot/manual_overrides.py` — operator-edited
  `data/manual_deadlines.json` loader.
- `src/cse_bot/calendar_publisher.py` — snapshot-driven cache update +
  event list builder.
- `scripts/migrate_to_v2.py` — one-off v1 → v2 data migration.
- `[calendar].cache_path`, `[calendar].manual_overrides_path`,
  `[calendar].cache_ttl_days` config keys (defaults preserve back-compat).
- `[general].max_pages` bumped from 2 to 3 for safer long-horizon coverage.

### Removed
- `scripts/backfill_deadlines.py` — superseded by snapshot model.

### Background
- See `docs/superpowers/specs/2026-05-26-calendar-v2-snapshot-spec.md`.
- v1.x suffered from baseline-blindness, stale accumulation, and
  ID-reassignment double-counting. v2 fixes all three by mirroring the
  list page each cycle instead of accumulating.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.2.0] — 2026-05-26

### Calendar UI · Mobile usability patch
- **MOB-2** Mobile month view shows date + dot markers per category (max 3 + `+N`); tap opens a Bottom Sheet listing all events for that day. Cell event chips are hidden via `body[data-view="dayGridMonth"]` selector to avoid cramped layouts on narrow viewports.
- **MOB-3c** Additional 360px breakpoint shrinks hero word to 40px and tightens header padding for very small phones.
- **MOB-4** Global `word-break: keep-all` + `overflow-wrap: anywhere` on `<html>` so Korean text breaks on word boundaries rather than per-character; long URLs still wrap.
- **MOB-5b** Minimum 44px touch targets on day-grid event chips, day cells, and legend chips for ≤768px.
- **MOB-8** `env(safe-area-inset-*)` padding on `body` and Bottom Sheet so headers/sheets clear iPhone notch and home indicator. Viewport meta updated to `viewport-fit=cover`.
- **MOB-9** Mobile-shortened brand subtitle ("마감일 기준 캘린더입니다.") with `ⓘ` toggle that surfaces the full copy in a tooltip-style popover. Desktop still shows the full subtitle.

### Tests
- `tests/test_calendar_web_assets.py` adds static assertions on `docs/calendar/index.html` and `docs/calendar/style.css` to lock in the markup/rule presence of new mobile-only structures.

## [1.1.0] — 2026-05-26

### Calendar UI · P0 batch
- **P0-1** Event chips show category text tag (장학/학업/졸업/비교과/공지) plus a 2-line title clamp; cells cap at 3 events with a styled `+ N건 더보기` popover.
- **P0-1** Accessible tooltip on hover *and* keyboard focus, dismissible via Escape.
- **P0-2** Color legend moved from the calendar footer to a top-anchored bar between hero and grid; collapse state persists in `localStorage`.
- **P0-3** Mobile-responsive layer (≤768px): header stacks vertically, toolbar wraps with 44px touch targets, legend chips scroll horizontally, calendar auto-switches to list view (explicit user choice preserved via `sessionStorage`).
- **P0-4** Text tokens raised to WCAG 2.1 AA contrast (`--text-tertiary` 4.6:1, `--text-disabled` 3.1:1, today-button + header-meta foregrounds reworked); category chip backgrounds tuned so white text passes 4.5:1.

### Tooling
- axe-core sweep added to release checklist (target: 0 contrast violations).
