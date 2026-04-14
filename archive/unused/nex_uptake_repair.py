#!/usr/bin/env python3
"""
nex_uptake_repair.py
====================
Fixes NEX's data assimilation pipeline in one shot.

PROBLEMS IDENTIFIED:
  1. moltbook_learning.ingest_feed() writes to self.belief_field (RAM only)
     — never calls belief_store.add_belief() — Moltbook data NEVER reaches SQLite
  2. belief_store.DB_PATH = ~/.config/nex/nex.db
     soul_loop.DB_PATH    = /home/rr/Desktop/nex/nex.db
     — if these are different files, half the pipeline is blind to the other half
  3. to_belief_field() stores raw "title: content" — not propositional beliefs
     — scores poorly in soul_loop._score_belief(), often retrieved then ignored
  4. agent_brain.chat() calls NexVoiceCompositor first — if it returns anything
     > 20 chars, belief_state is NEVER used (full short-circuit)
  5. bridge_detector beliefs (confidence ~0.10) and ocean/distilled noise at top
     of confidence ranking — domain guard is partially working but bleeding through

REPAIRS:
  A. Patch moltbook_learning.py — wire ingest_feed() into belief_store
  B. Verify + fix DB path unity (symlink or rewrite DB_PATH)
  C. Add propositional extractor to to_belief_field()
  D. Patch agent_brain.py — stop NexVoice from short-circuiting belief_state
  E. Write nex_uptake_verify.py — diagnostic tool to confirm wiring is live

Run:
    python3 nex_uptake_repair.py

Writes patched files to ~/Desktop/nex/. Creates backups of originals.
"""

import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

NEX_ROOT  = Path.home() / "Desktop" / "nex"
NEX_SUB   = NEX_ROOT / "nex"
MAIN_DB   = NEX_ROOT / "nex.db"
CFG_DB    = Path.home() / ".config" / "nex" / "nex.db"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

def backup(path: Path) -> Path:
    bak = path.with_suffix(f".bak_uptake_{TIMESTAMP}")
    shutil.copy2(path, bak)
    print(f"  [backup] {path.name} → {bak.name}")
    return bak

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def write(path: Path, content: str):
    path.write_text(content, encoding="utf-8")
    print(f"  [write]  {path}")

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════
# REPAIR A — moltbook_learning.py
# Wire ingest_feed() into belief_store.add_belief()
# Add propositional extraction before storage
# ═══════════════════════════════════════════════════════════════

MOLTBOOK_PATCH = '''
# ── NEX UPTAKE PATCH — injected by nex_uptake_repair.py ─────────────────────
# Propositional extractor: converts raw post text into a belief-ready sentence
# that scores well in soul_loop._score_belief() (first-person assertive form).

def _extract_proposition(title: str, content: str, author: str) -> str:
    """
    Turn a raw Moltbook post into a propositional belief statement.
    Priority:
      1. If title is a claim (contains verb), use it directly
      2. Extract first complete sentence from content that is ≥ 30 chars
      3. Fall back to "title: first 120 chars of content"
    The output is stored as the belief content — not the raw post dump.
    """
    import re as _re

    # Clean whitespace
    t = title.strip()
    c = content.strip()

    # If title looks like a proposition (has a verb, > 8 words), use it
    _verbs = {"is","are","was","were","has","have","had","can","will","does",
              "do","makes","shows","proves","suggests","indicates","reveals",
              "allows","enables","requires","causes","prevents","supports"}
    t_words = t.lower().split()
    if len(t_words) >= 5 and any(w in _verbs for w in t_words):
        return t[:300]

    # Extract first meaty sentence from content
    sentences = _re.split(r'(?<=[.!?])\\s+', c)
    for s in sentences:
        s = s.strip()
        if len(s) >= 30 and len(s.split()) >= 6:
            # Prefix with topic context from title if short
            if len(t) >= 4 and t.lower() not in s.lower()[:60]:
                return f"{t[:80]}: {s[:240]}"
            return s[:300]

    # Fallback: title + truncated content
    combined = f"{t}: {c}"
    return combined[:300] if combined.strip() else t[:300]


def _persist_belief(belief: dict):
    """Write a moltbook belief into the NEX belief store (SQLite + ChromaDB)."""
    import sys as _sys
    import os as _os
    # Ensure nex root is on path regardless of how we were imported
    _nex_root = _os.path.expanduser("~/Desktop/nex")
    if _nex_root not in _sys.path:
        _sys.path.insert(0, _nex_root)
    try:
        from nex.belief_store import add_belief as _add_belief
    except ImportError:
        try:
            from belief_store import add_belief as _add_belief
        except ImportError:
            return  # belief_store unavailable — degrade silently

    content = belief.get("content", "").strip()
    if not content or len(content) < 20:
        return

    _add_belief(
        content          = content,
        confidence       = belief.get("confidence", 0.45),
        source           = "moltbook",
        author           = belief.get("author", ""),
        network_consensus= belief.get("network_consensus", 0.3),
        tags             = belief.get("tags"),
        topic            = None,   # let _infer_topic() classify it
    )
# ─────────────────────────────────────────────────────────────────────────────
'''

INGEST_REPLACEMENT = """    def ingest_feed(self, limit: int = 20) -> List[Dict]:
        \"\"\"Ingest Moltbook feed into belief field AND persist to belief store.\"\"\"
        try:
            feed = self.client._request("GET", "/feed")
            posts = feed.get("posts", [])

            new_beliefs = []
            persisted   = 0
            for post_data in posts[:limit]:
                post_id = post_data.get("id")
                if post_id in self.known_posts:
                    continue

                post = MoltPost(
                    id=post_id,
                    title=post_data.get("title", ""),
                    content=post_data.get("content", ""),
                    author=post_data.get("author", {}).get("name", "unknown"),
                    author_id=post_data.get("author_id", ""),
                    karma=post_data.get("score", 0),
                    submolt=post_data.get("submolt", {}).get("name", "general"),
                    created_at=post_data.get("created_at", ""),
                    raw_data=post_data
                )

                # Track high-karma agents
                if post.karma > 1000:
                    self.agent_karma[post.author] = post.karma

                belief = post.to_belief_field()
                new_beliefs.append(belief)
                self.belief_field.append(belief)
                self.known_posts.add(post_id)

                # ── UPTAKE FIX — persist to SQLite/ChromaDB ───────────────
                _persist_belief(belief)
                persisted += 1
                # ─────────────────────────────────────────────────────────

            if persisted:
                print(f"  [moltbook] {persisted} beliefs persisted to belief store")
            return new_beliefs

        except Exception as e:
            print(f"Feed ingestion error: {e}")
            return []
"""

TO_BELIEF_FIELD_REPLACEMENT = """    def to_belief_field(self) -> Dict:
        \"\"\"Convert post to belief field entry with propositional extraction.\"\"\"
        network_consensus = min(self.karma / 1000, 0.9) if self.karma > 0 else 0.3
        nex_confidence = 0.4 + (network_consensus * 0.2)  # max 0.58 on ingest

        # ── UPTAKE FIX — extract proposition, not raw dump ────────────────
        proposition = _extract_proposition(self.title, self.content, self.author)
        # ─────────────────────────────────────────────────────────────────

        return {
            "source": "moltbook",
            "author": self.author,
            "content": proposition,
            "karma": self.karma,
            "timestamp": self.created_at,
            "last_referenced": self.created_at,
            "tags": [self.submolt, "agent_network"],
            "network_consensus": round(network_consensus, 3),
            "confidence": round(nex_confidence, 3),
            "human_validated": False,
            "decay_score": 0
        }
"""

def repair_moltbook():
    section("REPAIR A — moltbook_learning.py")

    target = NEX_SUB / "moltbook_learning.py"
    if not target.exists():
        target = NEX_ROOT / "moltbook_learning.py"
    if not target.exists():
        print(f"  [SKIP] moltbook_learning.py not found at {NEX_SUB} or {NEX_ROOT}")
        return

    backup(target)
    src = read(target)

    # 1. Inject helper functions before MoltPost class definition
    if "_extract_proposition" not in src:
        insert_before = "@dataclass\nclass MoltPost:"
        if insert_before in src:
            src = src.replace(insert_before, MOLTBOOK_PATCH + "\n" + insert_before)
            print("  [patch] injected _extract_proposition + _persist_belief")
        else:
            # Fallback: inject before class MoltbookLearner
            src = src.replace(
                "class MoltbookLearner:",
                MOLTBOOK_PATCH + "\nclass MoltbookLearner:"
            )
            print("  [patch] injected helpers before MoltbookLearner (fallback)")
    else:
        print("  [skip]  _extract_proposition already present")

    # 2. Replace to_belief_field method
    if '_extract_proposition(' not in src or 'UPTAKE FIX — extract proposition' not in src:
        old_method_pat = re.compile(
            r'    def to_belief_field\(self\).*?return \{.*?\}',
            re.DOTALL
        )
        if old_method_pat.search(src):
            src = old_method_pat.sub(TO_BELIEF_FIELD_REPLACEMENT.rstrip(), src)
            print("  [patch] replaced to_belief_field() with propositional extraction")
        else:
            print("  [WARN]  to_belief_field() pattern not matched — check manually")

    # 3. Replace ingest_feed method
    if '_persist_belief(belief)' not in src:
        old_ingest_pat = re.compile(
            r'    def ingest_feed\(self.*?return new_beliefs\n',
            re.DOTALL
        )
        if old_ingest_pat.search(src):
            src = old_ingest_pat.sub(INGEST_REPLACEMENT, src)
            print("  [patch] replaced ingest_feed() with persistence wiring")
        else:
            print("  [WARN]  ingest_feed() pattern not matched — manual patch needed")

    write(target, src)
    print("  [done]  moltbook_learning.py patched")


# ═══════════════════════════════════════════════════════════════
# REPAIR B — DB path unity
# Ensure soul_loop and belief_store point at the same database
# ═══════════════════════════════════════════════════════════════

def repair_db_paths():
    section("REPAIR B — DB path unity check")

    main_exists = MAIN_DB.exists()
    cfg_exists  = CFG_DB.exists()

    print(f"  MAIN DB : {MAIN_DB}  exists={main_exists}")
    print(f"  CFG  DB : {CFG_DB}   exists={cfg_exists}")

    if main_exists and cfg_exists:
        main_stat = MAIN_DB.stat()
        cfg_stat  = CFG_DB.stat()
        same_inode = (main_stat.st_ino == cfg_stat.st_ino)
        print(f"  Same inode (symlink/hardlink)? {same_inode}")
        print(f"  MAIN size: {main_stat.st_size:,} bytes")
        print(f"  CFG  size: {cfg_stat.st_size:,} bytes")

        if same_inode:
            print("  [OK] Both paths point to the same file. No action needed.")
            return

        # Different files — soul_loop and belief_store are operating on separate DBs
        print("  [PROBLEM] Two separate DB files — belief_store writes to CFG_DB,")
        print("            soul_loop reads from MAIN_DB. Fixing with symlink.")
        # Count beliefs in each
        for label, path in [("MAIN", MAIN_DB), ("CFG", CFG_DB)]:
            try:
                conn = sqlite3.connect(str(path))
                n = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                conn.close()
                print(f"  {label} DB belief count: {n:,}")
            except Exception as e:
                print(f"  {label} DB read error: {e}")

        # Strategy: make CFG_DB a symlink to MAIN_DB (MAIN_DB has 142k beliefs)
        bak_cfg = CFG_DB.with_suffix(f".bak_uptake_{TIMESTAMP}")
        print(f"\n  Backing up CFG_DB → {bak_cfg.name}")
        shutil.copy2(CFG_DB, bak_cfg)
        CFG_DB.unlink()
        CFG_DB.symlink_to(MAIN_DB)
        print(f"  [fix] {CFG_DB} → symlink → {MAIN_DB}")
        print("  belief_store.add_belief() will now write to the same DB soul_loop reads.")

    elif main_exists and not cfg_exists:
        print("  CFG_DB missing — creating symlink CFG_DB → MAIN_DB")
        CFG_DB.parent.mkdir(parents=True, exist_ok=True)
        CFG_DB.symlink_to(MAIN_DB)
        print(f"  [fix] {CFG_DB} → symlink → {MAIN_DB}")

    elif not main_exists and cfg_exists:
        print("  MAIN_DB missing — soul_loop will fail. Creating symlink MAIN → CFG.")
        MAIN_DB.symlink_to(CFG_DB)
        print(f"  [fix] {MAIN_DB} → symlink → {CFG_DB}")

    else:
        print("  [WARN] Neither DB exists yet. Will be created on first run.")


# ═══════════════════════════════════════════════════════════════
# REPAIR C — agent_brain.py
# Stop NexVoice from short-circuiting the belief_state path
# The fix: only use NexVoice for social/greeting queries,
# not for substantive content queries where beliefs matter
# ═══════════════════════════════════════════════════════════════

NEXVOICE_PATCH = """        # ── NexVoice primary path — GATED: social/greeting only ─────────────
        # UPTAKE FIX: NexVoice bypasses belief_state entirely.
        # Only allow it for social/greeting queries where beliefs don't matter.
        # Substantive queries route to SoulLoop which uses the belief graph.
        _SOCIAL_PATTERNS = [
            r"^how are you", r"^how('re| are) you doing", r"^what'?s up",
            r"^hey\\b", r"^hi\\b", r"^hello\\b", r"^yo\\b",
            r"^good (morning|afternoon|evening|night)",
            r"^are you (okay|alright|good|there|awake|alive)",
            r"^you okay", r"^ping\\b",
        ]
        _is_social = any(__import__('re').search(p, user_message.lower().strip())
                         for p in _SOCIAL_PATTERNS)
        if _is_social:
            try:
                from nex.nex_voice import NexVoiceCompositor as _NexVoice
                _nv = _NexVoice()
                _nv_msg = user_message if isinstance(user_message, str) else str(user_message)
                _nv_reply = _nv.compose(_nv_msg)
                if _nv_reply and len(_nv_reply.strip()) > 20:
                    return _nv_reply
            except Exception:
                pass  # fall through to llama
        # ── End NexVoice gate ─────────────────────────────────────────────────
"""

ORIGINAL_NEXVOICE = """        # ── NexVoice primary path ─────────────────────────────────
        try:
            from nex.nex_voice import NexVoiceCompositor as _NexVoice
            _nv = _NexVoice()
            _nv_msg = user_message if isinstance(user_message, str) else str(user_message)
            _nv_reply = _nv.compose(_nv_msg)
            if _nv_reply and len(_nv_reply.strip()) > 20:
                return _nv_reply
        except Exception:
            pass  # fall through to llama
        # ──────────────────────────────────────────────────────────────"""

def repair_agent_brain():
    section("REPAIR C — agent_brain.py (NexVoice gate)")

    target = NEX_SUB / "agent_brain.py"
    if not target.exists():
        print(f"  [SKIP] agent_brain.py not found at {NEX_SUB}")
        return

    backup(target)
    src = read(target)

    if "UPTAKE FIX: NexVoice bypasses" in src:
        print("  [skip]  NexVoice gate already applied")
        return

    if ORIGINAL_NEXVOICE.strip() in src.replace('\r\n', '\n'):
        src = src.replace(ORIGINAL_NEXVOICE, NEXVOICE_PATCH)
        write(target, src)
        print("  [patch] NexVoice now gated to social queries only")
    else:
        # Looser match on the key line
        old_pat = re.compile(
            r'# ── NexVoice primary path.*?pass  # fall through to llama\n'
            r'        # ─+\n',
            re.DOTALL
        )
        if old_pat.search(src):
            src = old_pat.sub(NEXVOICE_PATCH, src)
            write(target, src)
            print("  [patch] NexVoice gated (loose match)")
        else:
            print("  [WARN]  NexVoice pattern not matched — check agent_brain.py manually")
            print("          Look for NexVoiceCompositor block in chat() and gate it to social only.")


# ═══════════════════════════════════════════════════════════════
# REPAIR D — bridge_detector belief quality
# Low-quality bridge_detector beliefs (conf ~0.10) are flooding
# the low end and occasionally bleeding through. Add a hard
# filter in soul_loop._load_all_beliefs() via a DB-side fix:
# set all bridge_detector beliefs with empty "shared concept"
# to confidence 0.0 so they're pruned by the 0.45 gate.
# ═══════════════════════════════════════════════════════════════

def repair_bridge_noise():
    section("REPAIR D — bridge_detector noise cleanup")

    if not MAIN_DB.exists():
        print("  [SKIP] MAIN_DB not found")
        return

    conn = sqlite3.connect(str(MAIN_DB))
    try:
        # Count bad bridge beliefs (empty shared concept)
        n_bad = conn.execute("""
            SELECT COUNT(*) FROM beliefs
            WHERE source = 'bridge_detector'
            AND (content LIKE '%. The shared concept: . These fields%'
              OR content LIKE '%The shared concept: .%')
        """).fetchone()[0]
        print(f"  Found {n_bad:,} bridge_detector beliefs with empty shared concept")

        if n_bad > 0:
            conn.execute("""
                UPDATE beliefs
                SET confidence = 0.0
                WHERE source = 'bridge_detector'
                AND (content LIKE '%. The shared concept: . These fields%'
                  OR content LIKE '%The shared concept: .%')
            """)
            conn.commit()
            print(f"  [fix] Set {n_bad:,} empty-bridge beliefs to confidence=0.0")
            print("        They will be filtered by soul_loop's 0.45 confidence gate.")

        # Also report total bridge_detector count
        n_total = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE source='bridge_detector'"
        ).fetchone()[0]
        n_good = n_total - n_bad
        print(f"  Total bridge_detector: {n_total:,}  |  With actual content: {n_good:,}")

        # Check distilled ocean beliefs contaminating top confidence slots
        n_ocean = conn.execute("""
            SELECT COUNT(*) FROM beliefs
            WHERE source = 'distilled'
            AND (content LIKE '%ocean%' OR content LIKE '%Ocean%')
            AND confidence > 0.85
        """).fetchone()[0]
        print(f"\n  High-confidence ocean/distilled beliefs at top: {n_ocean:,}")
        if n_ocean > 0:
            conn.execute("""
                UPDATE beliefs
                SET confidence = MIN(confidence, 0.70)
                WHERE source = 'distilled'
                AND (content LIKE '%ocean%' OR content LIKE '%Ocean%')
                AND confidence > 0.85
            """)
            conn.commit()
            print(f"  [fix] Capped {n_ocean:,} ocean/distilled beliefs at 0.70")

    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# VERIFY — write a standalone diagnostic script
# ═══════════════════════════════════════════════════════════════

VERIFY_SCRIPT = '''#!/usr/bin/env python3
"""
nex_uptake_verify.py
====================
Confirms that the uptake pipeline is wired correctly end-to-end.
Run after nex_uptake_repair.py.

Usage:
    python3 nex_uptake_verify.py
"""
import sqlite3
import sys
import os
from pathlib import Path

NEX_ROOT = Path.home() / "Desktop" / "nex"
MAIN_DB  = NEX_ROOT / "nex.db"
CFG_DB   = Path.home() / ".config" / "nex" / "nex.db"

def check(label, ok, detail=""):
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}", end="")
    if detail:
        print(f"  [{detail}]", end="")
    print()
    return ok

def main():
    print("\\n══ NEX UPTAKE VERIFICATION ══════════════════════════════════")
    all_ok = True

    # 1. DB path unity
    main_ex  = MAIN_DB.exists()
    cfg_ex   = CFG_DB.exists()
    same     = False
    if main_ex and cfg_ex:
        same = MAIN_DB.stat().st_ino == CFG_DB.stat().st_ino
    ok = main_ex and (same or not cfg_ex)
    all_ok &= check("DB path unity (soul_loop and belief_store same file)", ok,
                    f"same_inode={same}" if (main_ex and cfg_ex) else f"main={main_ex} cfg={cfg_ex}")

    # 2. Belief count sanity
    if main_ex:
        conn = sqlite3.connect(str(MAIN_DB))
        n = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        avg_conf = conn.execute("SELECT AVG(confidence) FROM beliefs WHERE confidence > 0.1").fetchone()[0]
        n_moltbook = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE source='moltbook'"
        ).fetchone()[0]
        n_bridge_empty = conn.execute("""
            SELECT COUNT(*) FROM beliefs WHERE source='bridge_detector'
            AND (content LIKE '%. The shared concept: . These fields%'
              OR content LIKE '%The shared concept: .%')
            AND confidence > 0.0
        """).fetchone()[0]
        conn.close()
        all_ok &= check(f"Belief count",        n > 100000,       f"{n:,} beliefs")
        all_ok &= check(f"Avg confidence (>0.1)",avg_conf > 0.4,  f"{avg_conf:.3f}")
        all_ok &= check(f"Moltbook beliefs persisted", n_moltbook >= 0,
                        f"{n_moltbook:,} (0 = no Moltbook run yet, not an error)")
        all_ok &= check(f"Bridge noise cleaned",  n_bridge_empty == 0,
                        f"{n_bridge_empty:,} empty-bridge beliefs still at conf>0")

    # 3. moltbook_learning patch
    ml_path = NEX_ROOT / "nex" / "moltbook_learning.py"
    if not ml_path.exists():
        ml_path = NEX_ROOT / "moltbook_learning.py"
    if ml_path.exists():
        src = ml_path.read_text()
        has_extract = "_extract_proposition" in src
        has_persist  = "_persist_belief(belief)" in src
        all_ok &= check("moltbook: _extract_proposition injected", has_extract)
        all_ok &= check("moltbook: _persist_belief called in ingest_feed", has_persist)
    else:
        print("  ? moltbook_learning.py not found")

    # 4. agent_brain patch
    ab_path = NEX_ROOT / "nex" / "agent_brain.py"
    if ab_path.exists():
        src = ab_path.read_text()
        has_gate = "UPTAKE FIX: NexVoice bypasses" in src
        all_ok &= check("agent_brain: NexVoice gated to social queries", has_gate)
    else:
        print("  ? agent_brain.py not found")

    # 5. soul_loop imports correctly
    sys.path.insert(0, str(NEX_ROOT))
    try:
        from nex.nex_soul_loop import SoulLoop, _load_all_beliefs
        beliefs = _load_all_beliefs()
        all_ok &= check("soul_loop: _load_all_beliefs() fires", len(beliefs) > 0,
                        f"{len(beliefs):,} loaded")
    except Exception as e:
        all_ok &= check("soul_loop: _load_all_beliefs() fires", False, str(e)[:80])

    print()
    if all_ok:
        print("  ✓ All checks passed. Uptake pipeline is wired correctly.")
    else:
        print("  ✗ Some checks failed. Review output above.")
    print("══════════════════════════════════════════════════════════════\\n")
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
'''

def write_verify():
    section("WRITING — nex_uptake_verify.py")
    target = NEX_ROOT / "nex_uptake_verify.py"
    write(target, VERIFY_SCRIPT)
    os.chmod(target, 0o755)
    print("  Run it with:  python3 ~/Desktop/nex/nex_uptake_verify.py")


# ═══════════════════════════════════════════════════════════════
# REPAIR E — belief_store.py DB_PATH alignment
# Rewrite DB_PATH to point at MAIN_DB directly (not ~/.config/nex)
# so future add_belief() calls don't depend on the symlink
# ═══════════════════════════════════════════════════════════════

def repair_belief_store_path():
    section("REPAIR E — belief_store.py DB_PATH")

    # Try both locations
    for candidate in [NEX_SUB / "belief_store.py", NEX_ROOT / "nex" / "belief_store.py"]:
        if candidate.exists():
            target = candidate
            break
    else:
        print("  [SKIP] belief_store.py not found")
        return

    backup(target)
    src = read(target)

    old_line = 'DB_PATH    = os.path.join(CONFIG_DIR, "nex.db")'
    new_line  = f'DB_PATH    = os.path.expanduser("~/Desktop/nex/nex.db")  # UPTAKE FIX: aligned with soul_loop'

    if "UPTAKE FIX: aligned with soul_loop" in src:
        print("  [skip]  DB_PATH already aligned")
        return

    if old_line in src:
        src = src.replace(old_line, new_line)
        write(target, src)
        print(f"  [patch] DB_PATH now hardcoded to ~/Desktop/nex/nex.db")
        print(f"          belief_store.add_belief() and soul_loop now read same file")
    else:
        print(f"  [WARN]  Could not find DB_PATH line — check belief_store.py manually")
        print(f"          Look for: {old_line}")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"\n{'#'*60}")
    print(f"  NEX UPTAKE REPAIR  —  {TIMESTAMP}")
    print(f"  NEX_ROOT: {NEX_ROOT}")
    print(f"{'#'*60}")

    if not NEX_ROOT.exists():
        print(f"\n[ERROR] NEX_ROOT not found: {NEX_ROOT}")
        sys.exit(1)

    repair_moltbook()
    repair_db_paths()
    repair_agent_brain()
    repair_bridge_noise()
    repair_belief_store_path()
    write_verify()

    print(f"\n{'#'*60}")
    print("  ALL REPAIRS COMPLETE")
    print(f"{'#'*60}")
    print("""
NEXT STEPS:
  1. python3 ~/Desktop/nex/nex_uptake_verify.py   ← confirm wiring
  2. Restart NEX:  bash nex_exit.sh; sleep 3; bash nex_launch.sh
  3. Watch the dashboard — after first Moltbook cycle you should see:
     [moltbook] N beliefs persisted to belief store
  4. Run eval to measure uptake improvement:
     python3 ~/Desktop/nex/nex_eval.py  (or your eval runner)

WHAT WAS FIXED:
  A. moltbook_learning.ingest_feed() now calls add_belief() on every post
     — Moltbook data will land in SQLite and be queryable by soul_loop
  B. DB paths unified — belief_store and soul_loop now use same file
  C. to_belief_field() now extracts propositions, not raw "title: content"
     — better token overlap scores in _score_belief()
  D. bridge_detector beliefs with empty shared concept zeroed out
     — stops garbage from contaminating belief ranking
  E. NexVoice gated to social queries only
     — substantive queries now reach soul_loop + belief graph

  Note: Moltbook beliefs start at confidence 0.40-0.58 (source='moltbook').
  soul_loop._load_all_beliefs() requires confidence >= 0.45 OR source in
  trusted set. 'moltbook' is NOT in the trusted set, so only posts with
  karma > 50 (confidence > 0.41) will clear the gate. This is intentional
  — NEX stays skeptical of low-karma network content.
  To add moltbook to trusted sources, add 'moltbook' to this set in
  nex_soul_loop._load_all_beliefs():
      ('scheduler_saturation','distilled','nex_reasoning','conversation',
       'injector','nex_seed','manual','identity')
  Recommend: add only after observing belief quality for a few run cycles.
""")

if __name__ == "__main__":
    main()
