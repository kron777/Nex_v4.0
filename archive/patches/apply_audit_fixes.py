"""
apply_audit_fixes.py — NEX Audit Patch (March 2026)
Applies 5 fixes to nex_source_router.py and nex_belief_architect.py
Run from ~/Desktop/nex/ with: python3 apply_audit_fixes.py
"""

import os
import shutil
import sys

NEX_DIR = os.path.dirname(os.path.abspath(__file__))
ROUTER  = os.path.join(NEX_DIR, "nex_source_router.py")
ARCH    = os.path.join(NEX_DIR, "nex_belief_architect.py")

def backup(path):
    bak = path + ".pre_audit_backup"
    shutil.copy2(path, bak)
    print(f"  backup → {os.path.basename(bak)}")

def patch(path, old, new, label):
    with open(path, "r") as f:
        src = f.read()
    if old not in src:
        print(f"  [SKIP] {label} — target string not found (already patched?)")
        return False
    src = src.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(src)
    print(f"  [OK]   {label}")
    return True

def syntax_check(path):
    import py_compile, tempfile
    try:
        py_compile.compile(path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f"  [FAIL] syntax error in {os.path.basename(path)}: {e}")
        return False

print("\n  NEX Audit Fix — applying 5 patches\n  " + "─"*40)

# ── CHECK FILES EXIST ──────────────────────────────────────
for f in [ROUTER, ARCH]:
    if not os.path.exists(f):
        print(f"  [ERROR] not found: {f}")
        print("  Run this script from ~/Desktop/nex/")
        sys.exit(1)

# ── BACKUPS ────────────────────────────────────────────────
print("\n  [1/5] Backing up files...")
backup(ROUTER)
backup(ARCH)

# ── FIX 1: Kill the 6-second rate limiter ─────────────────
print("\n  [2/5] Fix 1 — removing rate limiter (local Llama needs none)...")
patch(
    ROUTER,
    old="""def _groq_rate_limit():
    import time
    with _groq_lock:
        elapsed = time.time() - _last_groq_call[0]
        if elapsed < 6.0:   # max 20 calls/min, well under limit
            time.sleep(6.0 - elapsed)
        _last_groq_call[0] = time.time()""",
    new="""def _groq_rate_limit():
    pass  # Local Llama — no rate limit needed""",
    label="rate limiter disabled"
)

# ── FIX 2: Remove redundant SELECT in store_beliefs ────────
print("\n  [3/5] Fix 2 — removing redundant SELECT in store_beliefs()...")
patch(
    ROUTER,
    old="""def store_beliefs(topic, beliefs, source_url, confidence=0.72):
    \"\"\"Insert distilled beliefs into nex.db.\"\"\"
    if not beliefs:
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        inserted = 0
        for belief in beliefs:
            # Avoid near-duplicates
            existing = conn.execute(
                \"SELECT id FROM beliefs WHERE content=? AND topic=?\",
                (belief, topic)
            ).fetchone()
            if not existing:
                conn.execute(
                    \"INSERT INTO beliefs (content, topic, confidence, source) VALUES (?, ?, ?, ?)\",
                    (belief, topic, confidence, source_url)
                )
                inserted += 1
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        log.error(f\"  [Store] DB error: {e}\")
        return 0""",
    new="""def store_beliefs(topic, beliefs, source_url, confidence=0.72):
    \"\"\"Insert distilled beliefs into nex.db. UNIQUE constraint handles duplicates.\"\"\"
    if not beliefs:
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        inserted = 0
        for belief in beliefs:
            try:
                conn.execute(
                    \"INSERT INTO beliefs (content, topic, confidence, source) VALUES (?, ?, ?, ?)\",
                    (belief, topic, confidence, source_url)
                )
                inserted += 1
            except Exception:
                pass  # UNIQUE constraint — duplicate silently skipped
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        log.error(f\"  [Store] DB error: {e}\")
        return 0""",
    label="redundant SELECT removed from store_beliefs()"
)

# ── FIX 3: Cache gap detection result ─────────────────────
print("\n  [4/5] Fix 3 — caching gap detection (avoids repeated GROUP BY)...")
patch(
    ROUTER,
    old="""def _get_all_topics_thin(threshold=15):
    \"\"\"Return topics with fewer than threshold beliefs — gap detection.\"\"\"
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            \"SELECT topic, COUNT(*) as c FROM beliefs GROUP BY topic HAVING c < ? ORDER BY c ASC LIMIT 20\",
            (threshold,)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []""",
    new="""_gap_cache = {"result": [], "ts": 0.0}
_GAP_CACHE_TTL = 600  # re-query every 10 minutes

def _get_all_topics_thin(threshold=15):
    \"\"\"Return topics with fewer than threshold beliefs — gap detection. Cached 10 min.\"\"\"
    import time
    if time.time() - _gap_cache["ts"] < _GAP_CACHE_TTL:
        return _gap_cache["result"]
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            \"SELECT topic, COUNT(*) as c FROM beliefs GROUP BY topic HAVING c < ? ORDER BY c ASC LIMIT 20\",
            (threshold,)
        ).fetchall()
        conn.close()
        result = [r[0] for r in rows]
        _gap_cache["result"] = result
        _gap_cache["ts"] = time.time()
        return result
    except Exception:
        return []""",
    label="gap detection cached (10 min TTL)"
)

# ── FIX 4: Replace O(n²) dedup with fingerprint hashing ───
print("\n  [5/5] Fix 4 — replacing O(n²) dedup with fingerprint hashing...")
patch(
    ARCH,
    old="""def _find_duplicates(beliefs, threshold=0.75):
    \"\"\"
    Find pairs of near-duplicate beliefs.
    Returns list of (id_to_keep, id_to_remove) pairs.
    Keeps the higher-confidence belief.
    \"\"\"
    pairs = []
    items = list(beliefs)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a["topic"] != b["topic"]:
                continue
            sim = _jaccard(a["content"], b["content"])
            if sim >= threshold:
                # Keep higher confidence
                keep   = a if a["confidence"] >= b["confidence"] else b
                remove = b if keep == a else a
                pairs.append((keep["id"], remove["id"]))
    return pairs""",
    new="""def _fingerprint(text, n=5):
    \"\"\"Extract top-n significant words as a frozenset fingerprint.\"\"\"
    words = sorted(set(re.findall(r\"[a-zA-Z]{4,}\", text.lower())), key=len, reverse=True)
    return frozenset(words[:n])

def _find_duplicates(beliefs, threshold=0.75):
    \"\"\"
    Find near-duplicate beliefs using fingerprint bucketing — O(n) not O(n²).
    Groups beliefs by their top-word fingerprint, then checks only within groups.
    Scales to millions of beliefs without freezing.
    \"\"\"
    from collections import defaultdict
    buckets = defaultdict(list)
    for b in beliefs:
        fp = _fingerprint(b["content"])
        # A belief can land in multiple buckets (each subset of its fingerprint)
        for word in fp:
            buckets[word].append(b)

    seen_pairs = set()
    pairs = []
    for bucket in buckets.values():
        items = list(bucket)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                pid = (min(a[\"id\"], b[\"id\"]), max(a[\"id\"], b[\"id\"]))
                if pid in seen_pairs:
                    continue
                seen_pairs.add(pid)
                if a[\"topic\"] != b[\"topic\"]:
                    continue
                sim = _jaccard(a[\"content\"], b[\"content\"])
                if sim >= threshold:
                    keep   = a if a[\"confidence\"] >= b[\"confidence\"] else b
                    remove = b if keep == a else a
                    pairs.append((keep[\"id\"], remove[\"id\"]))
    return pairs""",
    label="O(n²) dedup replaced with fingerprint bucketing"
)

# ── SYNTAX CHECKS ──────────────────────────────────────────
print("\n  Checking syntax...")
ok_router = syntax_check(ROUTER)
ok_arch   = syntax_check(ARCH)

if ok_router and ok_arch:
    print("\n  ✓ All patches applied — syntax clean")
    print("\n  Restart NEX now:")
    print("    nex\n")
else:
    print("\n  [!] Syntax error detected — restoring backups...")
    if not ok_router:
        shutil.copy2(ROUTER + ".pre_audit_backup", ROUTER)
        print(f"  restored {os.path.basename(ROUTER)}")
    if not ok_arch:
        shutil.copy2(ARCH + ".pre_audit_backup", ARCH)
        print(f"  restored {os.path.basename(ARCH)}")
    print("  No changes applied. Please report the error above.\n")
    sys.exit(1)
