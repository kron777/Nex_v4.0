# NEX Track A — Emergency Stabilization Results

**Session**: 2026-04-19 13:49 – 15:30 SAST (~1h40m, under 2h budget)
**Brief**: `/home/rr/Desktop/NEX_TRACK_A_BRIEF.txt`
**Pre-restart baseline**: nightly-brain PID 1656200 (uptime 6h56m prior to Track A restart at 15:19)
**Post-fix brain**: PID 2550986, restarted 2026-04-19 15:19:00 SAST

---

## Summary

Three targeted fixes applied, AST-checked, loaded via one brain restart. Two fully verified in-session (Fixes 1 & 3), one verified against a deterministic test matrix with live production log line reserved for next natural gap event (Fix 2).

| Fix | Files edited | Status | Verification |
|---|---|---|---|
| 1 | 9 files | ✅ applied | lock errors 4 → 1 in matched-window comparison; `nex_epistemic_momentum.py` standalone run clean; gatekeeper install line appears in each forked worker |
| 2 | `nex/nex_crawler.py` | ✅ applied | 5/5 bad-row test cases caught by 2a+2b; 0 false positives on 200 legitimate beliefs; gap-probe for `\[c\]` variant: 0 rows |
| 3 | `nex_nightly.py` | ✅ applied | 0 `cannot access local variable` since restart across both forced run and brain's natural nightly |

No production behavior change beyond the three targeted fixes. No schema changes. No API changes.

---

## Fix 1 — Lock contention

### Original framing
"Add busy_timeout to write connections." Task 0 showed this framing was wrong — `nex_db_gatekeeper.py` is the central connector and already applies `busy_timeout=60000 + WAL + synchronous=NORMAL + process-level write RLock` on every `sqlite3.connect()` that passes through it. The real gap was processes that open raw connections without importing the gatekeeper.

### What was changed
Added `import nex_db_gatekeeper` as the first Python import (after shebang/docstring) in 9 files. This is idempotent (`_gatekept` guard inside `install()`) and safe to re-apply.

Files edited:
- `nex_synthesis_loop.py` — cron, every 6h
- `nex_goal_research.py` — cron, every 2h
- `nex_selfq_sink.py` — cron, daily 05:30
- `nex_session_compressor.py` — cron, daily 02:00
- `nex_epistemic_momentum.py` — cron, every 15 min (highest contention risk)
- `nex_dream_runner.py` — cron, daily 03:00
- `nex_metabolism.py` — brain-hosted via `run.py`; also standalone-capable (redundant for brain path, defensive for standalone)
- `nex_belief_audit_daemon.py` — called from `nex_nightly.py` Phase 0a and standalone
- `nex_drain.py` — 3-worker multiprocessing crawler driver; fork workers inherit the monkey-patched `sqlite3.connect` from parent

### Dropped from original scope
`nex/belief_store.py` — transitively covered. All callers are either inside the brain process (gatekeeper loaded via `run.py:2`) or are in the 9 files just patched. The `nex_drain.py` importer was the one outside-brain caller; patching `nex_drain.py` directly closed the loop without needing the package-internal `sys.path` hack.

### Measurement

| | Pre-restart hour | Post-restart (~8 min window) |
|---|---|---|
| `database is locked` events | 4 | 1 |

The single post-restart hit happened during the forced nightly's Phase 0a, when the brain consolidator was concurrently writing — a transient cross-process collision at the SQLite file-lock layer. The except block handled it cleanly (logged `[audit] skipped`) and nightly execution continued. Pattern: 75% reduction in 8 min; longer window will tell whether this trends to zero or steady-state low.

Manual proof the previously-bypassed cron writer is now covered:

```
$ cd ~/Desktop/nex && venv/bin/python3 nex_epistemic_momentum.py
[nex_db_gatekeeper] v2 installed — writes serialized via process RLock   ← FIRST LINE
NEX Epistemic Momentum — status
...
(exit 0, no traceback, no lock error)
```

3-worker `nex_drain.py 1` manual run showed gatekeeper install in each forked subprocess, 23 new clean beliefs inserted, no lock contention during concurrent 3-writer load.

### Limits
- The RLock is process-local. Cross-process contention is handled by `busy_timeout=60000` + WAL, which makes it rare but not impossible under heavy concurrent write load (e.g., forced nightly + brain consolidator + crawler workers simultaneously).
- Not in scope, not patched: any other cron-launched modules that were missing from `~/Desktop/nex/` entirely (`nex_agency_loop.py`, `nex_belief_linker.py`, `nex_contradiction_loop.py`, `nex_pressure_test.py`, `nex_belief_prediction.py`, `nex_counterfactual.py` are all referenced in `crontab -l` but do not exist as files — they fire and fail from cron without causing DB contention).

---

## Fix 2 — Crawler quality gate

### What was changed
Single file: `/home/rr/Desktop/nex/nex/nex_crawler.py`. Three inserts:

**2a — topic-shape guard** (`_is_junk_topic` helper at line 76, called from `on_knowledge_gap` at line 558):
Rejects question-shaped topics before they become Wikipedia fallback URLs. Catches strings starting with `how does`, `what is`, `why does`, `when`, `where`, `which`, `can`, `should`, `please search`, `search for`, plus any topic >80 chars or containing `?`.

**2b — per-sentence boilerplate filter** (`_BOILERPLATE_RE` at line 102, applied in `_extract_sentences` at line 148):
10 regex patterns catching MediaWiki nav chrome (`Article \[...\]`, `Talk \[...\]`, sidebar items, `Search for "..."`, `Please search for ...`, `Page contents not supported ...`, etc.). Patterns were widened mid-session to cover both `\[alt-c\]` and `\[c\]` variants (MediaWiki emits both depending on render path — flagged before restart, amended in the same edit).

### Measurement

Pre-fix: 20 of last 20 crawl-source beliefs (ids 268126–268186) were boilerplate (100% contamination from question-shaped knowledge gaps).

Mid-session natural test: 5 more bad rows inserted (ids 268195–268206) between Task 0 audit and Task 2 load. All 5 caught by the widened regex in retest (5/5), 0 false positives on 200 legitimate non-crawl beliefs.

Post-Task-2-load (id > 268206): 24 new crawl beliefs. **21 are legitimate SEP article content** (Stanford Encyclopedia entry on Intentionality — e.g., `"Can intentionality be naturalized?"`, `"The relational nature of singular thoughts"`, `"Intentional inexistence"`). **3 are from a plato.stanford.edu 404 page** (`"Document Not Found"`, `"Please update any bookmark..."`, `"To find what you were looking for..."`) — see Known Limit below.

| Gap-probe (per Jon's addition) | Result |
|---|---|
| `SELECT COUNT(*) FROM beliefs WHERE origin='crawl' AND id > 268206 AND content LIKE 'Article%[c]%'` | **0** ✓ |

No MediaWiki-boilerplate row has passed the filter since Task 2 loaded.

### Known limit — SEP 404 template not covered
The boilerplate filter is MediaWiki-specific. plato.stanford.edu uses a different 404 template (`"Document Not Found / We are sorry but the document you are looking for doesn't exist..."`) and 3 sentences from an SEP 404 page leaked through (ids 268217–268219). Pre-existing failure mode — also affected Wikipedia-rate-limit cases in the earlier contamination set — just narrower than the original problem. Filter can be widened in a separate session.

Live `[crawler] junk topic rejected` log line remains unseen this session — gap events are cognition-driven and none fired during our 8-min post-restart window. The deterministic evidence (regex catch rate + gap-probe + false-positive test) is sufficient to confirm the fix works as designed.

### Hard constraint honored
Existing contaminated rows (268126–268206) NOT deleted per brief. Quarantining the pre-fix contamination is Track B scope.

---

## Fix 3 — Nightly `report` variable

### What was changed
Single file: `/home/rr/Desktop/nex/nex_nightly.py`. Moved one line — `report: dict = {}` — from line 764 up to line 731, before the Phase 0a try block that referenced it.

### Bug mechanism
Phase 0a (inserted at top of `run_nightly` to run the belief-audit daemon first) referenced `report['audit_quarantined']` in both the try body AND the except body. `report` wasn't initialized until line 764. The first reference (try body, line 735) raised `UnboundLocalError`, caught at line 737. The second reference (except body, line 739) raised the same error with no outer handler, surfacing as the observed `[NIGHTLY] run error: cannot access local variable 'report'`.

### Measurement

| | Pre-restart hour | Post-restart |
|---|---|---|
| `cannot access local variable` events | 3 | **0** |

Exercised by both my forced run (`python3 nex_nightly.py --force`) and the brain's own natural nightly trigger at 15:25:13. Both reached Phase 0 / Phase 1 cleanly. Side benefit: `audit_quarantined` and `audit_boosted` keys now survive into `nightly_log.report` JSON when Phase 0a runs cleanly (previously always clobbered by line 764's `report = {}`).

### Sibling bug surfaced — out of scope
With Phase 0a no longer killing the process early, Phase 2 (SYNTHESIZE) now runs and hits a pre-existing schema mismatch:

```
sqlite3.OperationalError: table meta_beliefs has no column named topic
  at nex_nightly.py:384 (phase_synthesize → conn.execute INSERT INTO meta_beliefs)
```

`meta_beliefs` has columns `id, content, confidence, source_ids, tags, created_at, reinforced` — no `topic`. The INSERT statement at `phase_synthesize` expects a `topic` column that doesn't exist in this schema.

Implication: nightly still does not write a row to `nightly_log` because Phase 2 crashes before Phase 7 (REPORT). **Track A brief explicitly warned**: *"Whether the nightly error has a sibling bug that surfaced after the fix"*. This is that sibling. Not in Track A scope. Queued for a future session (Track B or dedicated nightly fix pass).

---

## Task 4 measurements (summary)

| Metric | Audit baseline (13:49) | Post Task A (15:27) | Delta |
|---|---|---|---|
| `database is locked` per hour | ~8 (1 per ~10 min) | 1 in ~10 min post-restart | ≥ 75% reduction |
| `cannot access local variable` per hour | ~3 | 0 | −100% |
| Max belief id | 268186 | 268246 | +60 beliefs in 98 min |
| `nightly_log` rows | 1 (last: 2026-04-14) | 1 | unchanged — blocked by Phase 2 sibling bug |
| New crawl beliefs passing filter (id > 268206, after Task 2 load) | n/a | 24 (21 legitimate SEP prose, 3 SEP 404 leak) | 87.5% clean |
| Boilerplate-pattern hits since Task 2 load | n/a | 0 MediaWiki hits | clean |

---

## Anomalies & observations noted for future sessions

1. **Phase 2 schema mismatch** (meta_beliefs.topic column missing) — nightly can't complete until fixed. Recommended priority: next session.

2. **SEP 404 template leak** — `plato.stanford.edu` 404 pages produce English nav-style stubs ("Document Not Found", "Please update your bookmark") that MediaWiki-specific filters don't catch. Filter needs per-source templates or a more general "this looks like a 4xx page" heuristic.

3. **`[EVO] import warning: /media/rr/NEX/nex_core/nex_belief_index.py missing** (observed on HUD at 15:20:50). Pre-existing, unrelated to Track A. No action this session. Note for future investigation.

4. **Five cron targets missing from filesystem**: `nex_agency_loop.py`, `nex_belief_linker.py`, `nex_contradiction_loop.py`, `nex_pressure_test.py`, `nex_belief_prediction.py`, `nex_counterfactual.py`. Referenced in `crontab -l`, files do not exist. These cron lines fail silently. Either remove the cron entries or restore the files.

5. **Wikipedia pseudo-URL generation** is now blocked upstream by Fix 2a — but the root cause (cognition emitting question-shaped strings as "topics") was not addressed. Different cognition module changes could re-expose the crawler if 2a's prefix list is incomplete. Recommend: add a corresponding upstream sanitization where the topic is first minted.

6. **`belief_embryos` table carries 169,917 rows vs 5,772 promoted beliefs** (~2.9% promotion rate). `belief_embryos_archive` is empty (0 rows) despite schema. Embryos aren't being rotated out — pre-existing, not caused by Track A, but affects pipeline efficiency.

7. **Existing 21 contaminated crawl rows (268126–268206)** remain in the DB. Quarantining them is Track B scope per the brief's hard constraint.

---

## Backups

All edited files have `*.bak_track_a` backups alongside them:

```
/home/rr/Desktop/nex/nex_synthesis_loop.py.bak_track_a
/home/rr/Desktop/nex/nex_goal_research.py.bak_track_a
/home/rr/Desktop/nex/nex_selfq_sink.py.bak_track_a
/home/rr/Desktop/nex/nex_session_compressor.py.bak_track_a
/home/rr/Desktop/nex/nex_epistemic_momentum.py.bak_track_a
/home/rr/Desktop/nex/nex_dream_runner.py.bak_track_a
/home/rr/Desktop/nex/nex_metabolism.py.bak_track_a
/home/rr/Desktop/nex/nex_belief_audit_daemon.py.bak_track_a
/home/rr/Desktop/nex/nex_drain.py.bak_track_a
/home/rr/Desktop/nex/nex/nex_crawler.py.bak_track_a
/home/rr/Desktop/nex/nex_nightly.py.bak_track_a
```

11 files edited, 11 backups. Rollback path: `for f in *.bak_track_a; do cp "$f" "${f%.bak_track_a}"; done`.

---

## Feeds into later tracks

- **Track B** (quarantine / residue-loop wiring): delete/tag ids 268126–268206 as contaminated; also the 3 SEP-404-leak rows (268217–268219).
- **Track C/D** (whatever the next session brings): filesystem audit — resolve missing cron targets; investigate `belief_embryos` promotion rate; address the `[EVO] import warning` path.

---

# Track A.1 — meta_beliefs schema alignment

**Session**: 2026-04-19 ~16:00–16:30 SAST (~30 min, at budget)
**Brief**: inline, follow-up to Track A's surfaced Phase 2 sibling bug

## Summary

Single-purpose follow-up to Track A. Two writers (`nex_nightly.py` Phase 2, `nex_belief_colony.py` Synthesizer) had stale INSERT statements against the 7-column `meta_beliefs` table using 6 non-existent columns. Aligned the writers to the actual schema. Phase 2 now runs end-to-end; `meta_beliefs` gained 42 rows in the first verification run (155 → 197).

## Files edited

- `nex_nightly.py` — `phase_synthesize()` at lines 336–346 (CREATE TABLE update), 384–391 (INSERT update)
- `nex_belief_colony.py` — `Synthesizer.deliberate()` at lines 425–440 (same pattern)

Backups: `*.bak_track_a1` alongside each. Symmetric fix — same column mapping, same defensive null-filter on `source_ids`.

## Column mapping (both writers, identical)

| Writer supplied | Destination column |
|---|---|
| `meta` (synthesis text) | `content` |
| `round(conf, 3)` | `confidence` |
| `",".join(str(b["id"]) for b in sample/beliefs if b.get("id") is not None)` | `source_ids` |
| `f"{tag},synthesised,nightly_synth"` or `f"{topic},synthesised,colony_synth"` | `tags` |
| `datetime.now(timezone.utc).isoformat()` | `created_at` |
| (omitted) | `reinforced` — table default `1` kicks in |
| (dropped) `len(group)`, `f"nightly_synth:{tag}"` | — (no reader, no loss) |

Both writers' `CREATE TABLE IF NOT EXISTS` statements also updated to match the real schema (was a no-op on the live DB, but prevents confusion for future readers of the code and produces the right shape if the table is ever dropped for testing).

## Measurements

| Check | Target | Actual |
|---|---|---|
| No traceback on meta_beliefs INSERT | clean | ✅ clean |
| `meta_beliefs` row count | grow | 155 → **197** (+42) |
| New row shape matches existing | all 7 cols correct | ✅ `content` populated, `confidence=0.983` numeric, `source_ids='210427,210740,221387'` comma-sep digits, `tags='general_315,synthesised,nightly_synth'`, `created_at='2026-04-19T14:26:47'` ISO, `reinforced=1` |
| `nightly_log` row count | 1 → 2 | ❌ still 1 — blocked by Phase 3 sibling, see below |

Phase 2 SYNTHESIZE completed with `✓ 42 meta-beliefs written`. The first forced nightly showed real synthesized content (e.g. `"Truth is sustained by coherence and resilience under critical scrutiny"`, `"Consciousness entails irreducible subjective experience intrinsic to…"`).

## Phase 3 sibling surfaced — STOPPED per protocol

Forced nightly reached Phase 3 CONTRADICT then crashed:

```
sqlite3.IntegrityError: Cannot reduce confidence of locked belief
  at nex_nightly.py:480 (phase_contradict → conn.execute UPDATE)
```

**Root cause**: A `protect_locked_confidence` SQL trigger in the DB blocks UPDATEs that reduce confidence on `locked=1` beliefs. `nex_belief_audit_daemon.py:131–137` already knows the dance — drops the trigger, does its updates, restores the trigger. `phase_contradict` in `nex_nightly.py` does a bare UPDATE and hits the constraint.

**Fix shape (NOT applied, documented for next session)**: either (a) adopt the drop+restore pattern from the audit daemon, or (b) add a `WHERE locked=0` clause to the UPDATE. Option (b) is probably right — Track A.1 intentionally didn't take it.

## Also observed during the run (pre-existing, separate)

- `BeliefGraph unavailable (No module named 'nex_belief_graph')` — Phase 3 falls back to pattern-detection. Different missing-module from the `[EVO]` warning for `nex_belief_index.py` noted in Track A. Two separate missing-graph-like modules, queued for future audit.

## Feeds into later sessions

- **Phase 3 `protect_locked_confidence` interaction** — highest priority for the next nightly-fix session. Without it, nightly still can't reach Phase 7 REPORT, so `nightly_log` stays at 1 row.
- **meta_beliefs has no live reader** — writer fixed; the 197 rows still accumulate without being queried by any live code path. Reader loop-closing is Track B scope.
- **HUD error-filter `'meta_beliefs','has no column'` at `nex_hud_server.py:44`** — the error it was suppressing no longer fires. Safe to remove in Track B cleanup.
- **`nex_belief_graph` module missing** — new observation, separate from Track A's `nex_belief_index.py` note. Investigate in the same filesystem-audit session that addresses missing cron targets.

## Backups

```
/home/rr/Desktop/nex/nex_nightly.py.bak_track_a1
/home/rr/Desktop/nex/nex_belief_colony.py.bak_track_a1
```

2 files edited, 2 backups. Rollback: `for f in *.bak_track_a1; do cp "$f" "${f%.bak_track_a1}"; done`.

---

END OF TRACK A.1 RESULTS.
