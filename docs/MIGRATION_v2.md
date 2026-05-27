# v1.x → v2.0.0 Migration

One-time data migration for machines that ran the watermark-based v1
calendar before the v2 snapshot pipeline shipped (2026-05-27). Skip this
doc entirely if your machine started on v2.

## Why

v1 stored the calendar inside `data/state.json` as an incremental list
that grew (and missed events) over time. v2 mirrors the bulletin board
list page into `data/post_cache.json` every cycle, with manual overrides
in `data/manual_deadlines.json`. The migration script copies the
existing v1 deadlines into the v2 cache so the first v2 cycle does not
regress the calendar.

See `docs/superpowers/specs/2026-05-26-calendar-v2-snapshot-spec.md` for
the full design rationale (§0 documents the v1 failure modes:
baseline-blindness, stale accumulation, ID-reassignment double-counting).

## Runbook

```bash
# 1. Backup current state (defensive — script is safe to re-run)
cp data/state.json data/state.json.v1-backup
cp docs/calendar/events.json /tmp/events-pre-v2.json   # if present

# 2. Dry-run to confirm migration count
.venv/bin/python scripts/migrate_to_v2.py --dry-run

# 3. Apply migration
.venv/bin/python scripts/migrate_to_v2.py

# 4. Kick a cycle so warm cache populates content_hash
launchctl kickstart -k gui/$(id -u)/com.user.cse-bot
sleep 30
tail -50 logs/launchd.stderr.log     # expect 'calendar.cache_update' lines

# 5. Diff events.json — v2 should be a superset of v1
diff <(jq -S . /tmp/events-pre-v2.json) <(jq -S . docs/calendar/events.json)
```

The first v2 cycle re-summarises every migrated post once (~$0.01 Gemini
Flash Lite per spec §4.2); warm-cache behaviour resumes from the next
cycle and daily Gemini calls drop below 10.
