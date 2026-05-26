# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.1.0] — 2026-05-26

### Calendar UI · P0 batch
- **P0-1** Event chips show category text tag (장학/학업/졸업/비교과/공지) plus a 2-line title clamp; cells cap at 3 events with a styled `+ N건 더보기` popover.
- **P0-1** Accessible tooltip on hover *and* keyboard focus, dismissible via Escape.
- **P0-2** Color legend moved from the calendar footer to a top-anchored bar between hero and grid; collapse state persists in `localStorage`.
- **P0-3** Mobile-responsive layer (≤768px): header stacks vertically, toolbar wraps with 44px touch targets, legend chips scroll horizontally, calendar auto-switches to list view (explicit user choice preserved via `sessionStorage`).
- **P0-4** Text tokens raised to WCAG 2.1 AA contrast (`--text-tertiary` 4.6:1, `--text-disabled` 3.1:1, today-button + header-meta foregrounds reworked); category chip backgrounds tuned so white text passes 4.5:1.

### Tooling
- axe-core sweep added to release checklist (target: 0 contrast violations).
