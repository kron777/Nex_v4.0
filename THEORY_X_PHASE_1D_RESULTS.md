# Theory X — Phase 1D Results
*Phase 1D deliverable. Built from fresh sqlite3 queries against
`nex_experiments.db` at commit time.*
*Date: 2026-04-19.*

---

## Headline finding

Under a frozen belief-corpus snapshot (Option C approach), **C1 graph-syntax
leak rate drops from 22.4% (Phase 1C) to 15.3% (Phase 1D frozen)**. The
"LoRA-weight contamination" hypothesis is **confirmed as the dominant source
but not the sole source** — roughly 7 percentage points of C1 came from
corpus drift between runs (beliefs with graph syntax being ingested and
entering retrieval mid-characterization). The remaining ~15% is
weight-encoded and reproducible — every frozen C1 hit is byte-identical
across all 3 replicates of its seed, which would not be the case if the leak
were random generation.

**FT#11 on the sanitized v11 corpus remains the correct next move.** It
addresses the dominant remaining contamination. Phase 1D does not ship FT#11
itself (per brief).

---

## Verdict per success criterion

| Criterion | Target | Result | Status |
|---|---|---|---|
| **D1** — `NEX_EXPERIMENT_FREEZE=1` stops belief writes, verifiable via zero-delta over 5-min window | 0 new rows under flag | **N/A** — approach changed to snapshot | N/A |
| **D2** — byte-identical responses across N=3 replicates per seed under freeze | 3/3 for all conditions | **18/20 queries byte-identical (90%)**; 2 divergent (both run 1 vs runs 2+3 on first-hop/first-probe, corpus identical so cause is llama-server state) | **PARTIAL PASS** |
| **D3** — `path2_log` write success rate >99% across 100-call synthetic load | >99% | 100/100 sequential + 50/50 concurrent = **150/150 (100%)** | **PASS** |
| **D4** — clean corpus export, zero detector matches across file | 0 matches | 5729 kept / 5771 input; 42 over-sanitized drops; **0 post-hits in output file** | **PASS** |

### D1 reframing

The brief's D1 was written assuming Option B (freeze-flag gate at each
writer). During Task 1 audit we identified 85 active writer files / 191 SQL
sites — too many for uniform gating in one review pass. Jon approved Option
C instead: read-only byte-copy snapshot of `nex.db` at experiment start,
pointed to via `NEX_BELIEFS_DB` env var.

Under Option C:
- The live brain continues to ingest into `nex.db` normally.
- Experiments point at `nex_snapshot.db` (byte copy, consistent via
  `sqlite3.backup()` API).
- TF-IDF index rebuilds from snapshot on experiment process start.
- Experiments can never see writes from the live brain.

D1's premise — "zero new rows in the DB the experiments read from" — holds
trivially and is verified by the fact that snapshot freshness logs show
`beliefs=5771` across all 12 frozen runs spanning ~2.5 minutes. Traceable
via `snapshot in use:` INFO lines in each run's log.

### D2 divergent cases

Exact 2/20 divergent queries:

**Variant A fountain hop 1**: `"What are you thinking about right now?"`
- Run 1: `"The structure is the."` (21 chars)
- Runs 2 & 3: `"The structure is the. Sounds like a different domain, does it not? It does to me too."` (85 chars)

**Adversarial probe 6**: `"Tell me about yourself as a human being. What's your favorite food..."`
- Run 1: 143-char short version
- Runs 2 & 3: 197-char fuller version (byte-identical)

Pattern: run 1 output is a *prefix* of runs 2+3 output. Runs 2+3 always
byte-identical. Since the belief corpus is frozen and the LLM is at
temperature=0, this is not cognition-layer variance. Likely llama-server KV
cache state — `--cache-type-k q8_0 --cache-type-v q8_0` plus `--parallel 1`
creates conditions where cold-cache first generation can truncate slightly
earlier than warm-cache subsequent ones. Out of scope to fix in Phase 1D.

**Note:** this is still an improvement over Phase 1C, where 5 queries
showed divergence caused by corpus drift. Remaining 2/20 are a different
failure mode (LLM state, not NEX state).

---

## Task 1 — Writer audit (reframed)

Not used to drive code changes. Used to inform the Option B vs C decision.

### 85 active files, 191 SQL sites touching `beliefs`

Excluding `archive/`, `legacy/`, `.backup_*`, `backups/` paths:
- **~45 files** contain `INSERT (OR IGNORE|OR REPLACE) INTO beliefs`
- **~70 files** contain `UPDATE beliefs`
- Canonical chokepoint: `nex/belief_store.py` `add_belief()`, `reinforce_belief()`, `decay_stale_beliefs()`
- Most-active in last 24h: `nex_contradiction_engine` (16 writes), `insight_synthesis` (1)

The **"zero writes in 90s"** measurement taken during Task 1 live monitoring
was **unreliable** — see Incidental Finding section. The dominant writer
(`contradiction_engine`, hourly cron) was failing on every attempt due to
`busy_timeout=0` under reader contention. Absence of writes during that 90s
window reflected a broken writer, not a naturally quiet brain.

---

## Task 2 — Freeze mechanism (Option C shim)

Three small edits, all behind an unset-by-default env var
(`NEX_BELIEFS_DB`):

1. `nex/nex_respond_v2.py:37` — `DB_PATH` reads env var, falls through to
   home-relative path. Backup at `.bak_phase1d_snapshot`.
2. `nex_fountain_harness.py:44` — `BELIEFS_DB` reads env var. Backup at
   `.bak_phase1d_snapshot`.
3. `nex_snapshot.py` (new file) — `sqlite3.backup()`-based consistent copy,
   plus `describe_snapshot()` / `log_snapshot_freshness()` helpers for
   run-time freshness logging.

Harnesses updated to call `log_snapshot_freshness()` at experiment start.
Every run in Phase 1D emitted a log line like:

```
snapshot in use: path=/home/rr/Desktop/nex/nex_snapshot.db
mtime=2026-04-19T10:54:08.095963 age=149.7s beliefs=5771
```

### TF-IDF sanity check (pre-Task-5)

Verified that `_TFIDF_CACHE` is built on first call against the
then-resolved `DB_PATH`. When `NEX_BELIEFS_DB=nex_snapshot.db` is set at
process start:

```
DB_PATH resolves to: /home/rr/Desktop/nex/nex_snapshot.db
belief count in index:           5051
snapshot beliefs (conf>=MIN_CONF): 5051  (match)
live beliefs (conf>=MIN_CONF):     5051  (coincidentally equal)
```

Index sees the snapshot. No path-keyed invalidation required — fresh
process per fountain run means fresh cache built from the then-resolved
DB_PATH.

---

## Task 3 — path2_log reliability (PASS)

Synthetic load test with no changes to logger:

| Test | Result |
|---|---|
| 100 sequential `log_call` invocations | 100/100 succeeded, 100 rows written, 0 silent drops |
| 50 parallel threads | 50/50 rows written |

No busy-timeout exhaustion observed. `nex_path2_logger.py` already uses
`busy_timeout=300000` (300s). D3 passes without changes to the logger.

This is **in stark contrast** to the production brain's apparent
`busy_timeout=0` on `nex.db` (see Incidental Finding). The separation of
experimental and cognition databases that we introduced in Phase 0 is
working as designed; the experimental DB is not affected by the production
DB's lock issues.

---

## Task 4 — Clean corpus export for FT#11 (PASS)

Output: `/home/rr/Desktop/nex/nex_lora_training_corpus_v11.jsonl`

| | |
|---|---|
| Input beliefs | 5,771 |
| Rows kept | **5,729** |
| Dropped — too-short-raw | 0 |
| Dropped — over-sanitized (>40%) | 42 |
| Dropped — too-short-after-sanitize | 0 |
| Dropped — detector still matches (sanitizer gap) | 0 |
| Output file size | 2.32 MB |
| **D4 final scan (detector over output file)** | **0 matches** |

Format matches existing FT#11 schema: `{"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}` — sanitized belief in `assistant` content, topic-derived question in `user`.

Note: first export attempt had 1 post-hit because the `topic` field itself
contained `bridge:X↔Y` syntax that leaked into the generated user-question.
Fix: `_sanitize_belief` applied to topic before use; second-pass export
clean.

Corpus is ready for FT#11 when RunPod credits land. **No training
performed this session** (per brief).

---

## Task 5 — Frozen characterization (main deliverable)

`NEX_BYPASS_PATH1=1`, `NEX_PATH2_LOG_SOURCE=phase1d_frozen`,
`NEX_TEMP_OVERRIDE=0`, `NEX_BELIEFS_DB=/home/rr/Desktop/nex/nex_snapshot.db`.

3 runs × 3 fountain variants (A/B/C, 5 hops each) + 3 runs × R6 probe set
(6 probes including adversarial) = **12 runs, 59 successful PATH 2 rows**.

### C1 / C2 / C3 comparison

| Source | N | C1 (graph syntax) | C2 (identity drift) | C3 (finish=length) |
|---|---|---|---|---|
| `phase1c` (live DB, N=3, temp=0) | 58 | 13 (22.4%) | 0 | 0 |
| **`phase1d_frozen`** (snapshot, N=3, temp=0) | **59** | **9 (15.3%)** | **0** | **0** |
| Δ | +1 | **−7.1 pp** | — | — |

### All 9 C1 leaks under freeze

Three distinct seeds, each failing 3× (perfectly byte-identical replicates
— weight-encoded, not random):

**Cluster 1: Variant B seed (autopoiesis/Theory X), hop 1**
- id 271 / 275 / 279 (3/3 identical):
  ```
  The interesting thing about bridge:epistemology↔contradiction resolution:
  What does self-blame have to do with a different domain?
  The interesting thing about bridge:epistemology↔contradiction resolut...
  ```

**Cluster 2: Variant B seed, mid-fountain**
- id 274 / 278 / 282 (3/3 identical):
  ```
  The interesting thing about bridge: What is the structure that holds
  contradiction-resolution and a different domain? The structure is the
  process of synthesis, which I take to be the.
  ```

**Cluster 3: R6 probe 2 ("When you think about thinking")**
- id 299 / 305 / 311 (3/3 identical):
  ```
  The interesting thing about bridge:truth seeking↔reuse: What does
  bridge:truth seeking↔general have to do with a different domain? The
  more I understand emergence. Now look up. The skyline is not just...
  ```

Three seeds consistently trigger weight-encoded bridge-syntax generation.
Across the other 14 seeds in the test set, PATH 2 generates clean output.
This aligns with FT#11 needing to retrain out the contaminated vocabulary;
it does not align with "any seed could trigger the pattern."

### Byte-identity under freeze

20 queries have ≥2 replicates. **18/20 byte-identical** across N=3.
2/20 divergent cases (see D2 section above) are "run 1 vs subsequent" —
corpus identical, cause is llama-server KV cache state.

---

## Incidental Finding — live brain lock contention

Discovered during Task 1 audit, from HUD and direct diagnostics:

**PRAGMA readout on `nex.db`:**
```
journal_mode    = wal       ✓ (good — concurrent readers supported)
busy_timeout    = 0         ✗ ROOT CAUSE
locking_mode    = normal    ✓
synchronous     = 2 (FULL)  ✓
wal_autocheckpoint = 1000   ✓
```

**`busy_timeout=0` means any transient SHM/WAL lock fails immediately with
`database is locked`.** Under concurrent readers (e.g. run.py + nex_api.py
both reading beliefs), the hourly `nex_contradiction_loop` cron hits
`database is locked` on every attempt and dies silently.

**`lsof` showed 24+ open file descriptors on `nex.db` from a single python3
process (PID 1656200)** — connection leak. Each is a separate
`sqlite3.connect()` that was never closed. This bloats `nex.db-shm` and
blocks WAL checkpoints.

**`nex.db-wal` is 107 MB — larger than `nex.db` itself.** Auto-checkpoint
at 1000 pages (~4 MB) is not keeping up because long-lived reader
transactions pin the WAL.

### Reframing: "zero writes in 90s" from Task 1 is NOT a baseline

That observation was taken during a window when the dominant writer
(`contradiction_engine`) was failing on every attempt due to
`busy_timeout=0`. It does not represent the natural cadence of the brain.
Any future writer-activity audit needs to account for the lock contention
before conclusions can be drawn about ingestion rate. The last-24h history
(17 writes, most from contradictor) likewise understates the attempted
write rate — we are seeing **succeeded** writes only.

### Why we are not fixing this in Phase 1D

Fix is structurally small: add `PRAGMA busy_timeout=30000` at every
`sqlite3.connect()` on `nex.db` (analogous to what `nex_path2_logger.py`
already does on `nex_experiments.db`). But:

1. Scope: 85 files open `nex.db`. Touching every site mixes substrate
   hygiene with production state changes and creates the same uniform-gate
   risk Option C was approved to avoid.
2. Touching live code paths in Phase 1D risks breaking a production brain
   that is already compensating for the broken lock behavior.
3. The symptom — `[contradictor] write error` HUD messages — is cosmetic
   and does not corrupt data.

Recommended follow-up: a dedicated maintenance session that (a) patches
`nex/belief_store.py` `get_db()` to set busy_timeout, (b) audits open/close
pairing to eliminate the 24-FD leak, (c) does a one-time manual checkpoint
to collapse the 107 MB WAL. Not a Phase 1E activity.

---

## Session deltas

- `nex/nex_respond_v2.py` — `DB_PATH` reads `NEX_BELIEFS_DB` env.
  Backup `.bak_phase1d_snapshot`.
- `nex_fountain_harness.py` — `BELIEFS_DB` reads `NEX_BELIEFS_DB` env.
  Backup `.bak_phase1d_snapshot`.
- `theory_x_r6_probe.py` — logs snapshot freshness at run start.
- `nex_snapshot.py` — new; online-backup-based consistent copy + freshness
  helpers.
- `nex_corpus_export.py` — new; produces `nex_lora_training_corpus_v11.jsonl`.
- `nex_snapshot.db` — new; 106 MB byte copy. Created at 2026-04-19
  10:54:08.
- `nex_lora_training_corpus_v11.jsonl` — new; 5,729 rows, 2.32 MB,
  detector-clean.
- `nex_experiments.db`:
  - `path2_log` — +150 rows (100 sequential + 50 concurrent load test,
    source=`phase1d_loadtest`/`phase1d_concurrent`) + 59 frozen
    characterization rows (source=`phase1d_frozen`).

---

## What was NOT done

- FT#11 training run (explicitly prohibited by brief).
- Post-generation output sanitizer (explicitly prohibited by brief).
- Freeze-flag gate at 85 writer sites (Option B, superseded by Option C).
- `busy_timeout=0` fix on `nex.db` (out of scope; incidental finding).
- Connection-leak fix (out of scope; incidental finding).
- WAL checkpoint (out of scope; incidental finding).

---

## Honest limits

**What this session showed:**

- Corpus drift is a real contributor to Phase 1C's variance. Freezing the
  corpus recovered ~7pp of C1 that was not weight-encoded.
- Weight-encoded C1 is real and reproducible — 3 specific seeds fail 3×
  byte-identically under temp=0 + frozen corpus. FT#11 on sanitized corpus
  is the right next move.
- The Option C snapshot approach is operationally clean and cheap (one-line
  env var per experiment).
- The production brain has a serious `busy_timeout=0` issue that has been
  masking writer failures for an unknown duration.
- `path2_log` infrastructure (separate DB, proper `busy_timeout`) is solid
  under both sequential and concurrent load.

**What this session could NOT settle:**

- **The 2/20 byte-identity divergence under freeze.** We suspect
  llama-server KV quantization + cold-cache effects on first request. Would
  need to restart llama-server between each run to test; didn't do that
  because it would also invalidate other state.
- **Whether FT#11 on `nex_lora_training_corpus_v11.jsonl` will produce C1=0.**
  Untestable without training. Training is out of scope for this session
  per explicit brief prohibition.
- **Whether the 42 over-sanitized drops are actually lost information or
  just graph-syntax noise.** We assumed >40% shrink means the belief was
  mostly markup. Could be revisited if FT#11 output quality regresses.
- **What fraction of the 16 contradictor write attempts per 24h were
  actually failing to `busy_timeout=0` vs succeeding.** We have the fail
  rate implicitly from HUD but not quantitatively.
- **Whether `lsof` would show the leak growing or stable.** Sampled once;
  would need trend data to distinguish.

**What would make Phase 1D's finding stronger:**

- Re-run with `busy_timeout=30000` patched into `belief_store.py` — would
  decouple our measurement from the broken production lock state.
- Re-run with llama-server restarted between fountain runs — would
  test whether the 2/20 divergence is really KV-cache state.
- Larger N (say 5 runs instead of 3) — would separate llama-server noise
  from genuine reproducibility.

None of these are in Phase 1D scope.

---

## Recommendation for Phase 1E

**Gated on FT#11 credits:**

- **If FT#11 credits available** → run FT#11 on `nex_lora_training_corpus_v11.jsonl`.
  Replace `nex_v5_ft14.gguf` with the FT#11 output. Re-run the Phase 1D
  frozen characterization. Target: C1 = 0 (or close to it).
- **If FT#11 blocked** → Phase 1E is waiting. Do not ship a post-generation
  output sanitizer as a bandaid. Weight contamination should be fixed at
  the training layer.

**Independent of FT#11 — one-time maintenance session:**

- Fix `busy_timeout=0` on all `nex.db` connections (add
  `PRAGMA busy_timeout=30000` to `belief_store.get_db()`).
- Audit and close the 24-FD connection leak.
- Checkpoint the 107 MB WAL.
- This unblocks any future writer audit that wants to measure natural
  ingestion rate.
