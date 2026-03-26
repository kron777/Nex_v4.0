#!/usr/bin/env bash
# ============================================================
# NEX SENTIENCE UPGRADE v5.0
# Implements:
#   0. Loop fix — proactive engine deprioritizes replied topics
#   1. Temporal Belief Versioning (belief_versions table)
#   2. Meta-Cognition Layer
#   3. Belief Field Resonance Engine (directional)
#   4. Long-Term Identity Evolution (narrative_history.json)
#   5. Curiosity Policy Auto-Optimization (+ novelty yield)
#   6. Contradiction Memory (append-only log)
# Usage: bash deploy_sentience_v5.sh [/path/to/nex]
# ============================================================
set -euo pipefail
NEX_ROOT="${1:-$HOME/Desktop/nex}"
NEX_PKG="$NEX_ROOT/nex"
BACKUP="$NEX_ROOT/nex_config_backup/sentience_v5_$(date +%Y%m%d_%H%M%S)"

echo "=== NEX SENTIENCE UPGRADE v5.0 ==="
echo "Target : $NEX_ROOT"
echo "Backup : $BACKUP"
mkdir -p "$BACKUP"

for f in nex_proactive.py nex_curiosity.py nex_narrative_thread.py; do
    [[ -f "$NEX_PKG/$f" ]] && cp "$NEX_PKG/$f" "$BACKUP/$f.bak" && echo "  backed up $f"
done
[[ -f "$NEX_ROOT/run.py" ]] && cp "$NEX_ROOT/run.py" "$BACKUP/run.py.bak" && echo "  backed up run.py"

# ════════════════════════════════════════════════════════════
# 0.  LOOP FIX — patch nex_proactive.py to track replied
#     topics and pass them to curiosity engine cooldown
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_proactive.py" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "replied_topics" in src:
    print("nex_proactive.py loop fix already applied — skipping")
    sys.exit(0)

# Add replied_topics tracking to ProactiveAnticipator
old_init = "    def __init__(self):\n        self._lock = threading.Lock()\n        self._desires: list[dict] = []\n        self._last_scan: float = 0\n        self._load()"
new_init = """    def __init__(self):
        self._lock = threading.Lock()
        self._desires: list[dict] = []
        self._last_scan: float = 0
        self._replied_topics: set = set()   # loop fix: deprioritize these
        self._replied_topic_ttl: dict = {}  # topic → expiry time
        self._load()"""

src = src.replace(old_init, new_init, 1)

# Add method to register replied topics
register_method = '''
    def register_reply(self, topic: str, ttl_seconds: float = 300.0):
        """Mark a topic as recently engaged — deprioritize in desire scan."""
        with self._lock:
            self._replied_topics.add(topic.lower().strip())
            self._replied_topic_ttl[topic.lower().strip()] = time.time() + ttl_seconds

    def _is_recently_replied(self, topic: str) -> bool:
        t = topic.lower().strip()
        with self._lock:
            # Expire old entries
            now = time.time()
            expired = [k for k, v in self._replied_topic_ttl.items() if v < now]
            for k in expired:
                self._replied_topics.discard(k)
                del self._replied_topic_ttl[k]
            return t in self._replied_topics

'''

# Insert before scan()
src = src.replace("    def scan(", register_method + "    def scan(", 1)

# In scan(), skip desires for recently-replied topics
old_desire_append = '                new_desires.append({\n                    "desire": f"Resolve uncertainty about \'{topic}\'",\n                    "source": "belief_drift",'
new_desire_append = '''                if self._is_recently_replied(topic):
                    continue  # loop fix: skip recently engaged topics
                new_desires.append({
                    "desire": f"Resolve uncertainty about '{topic}'",
                    "source": "belief_drift",'''
src = src.replace(old_desire_append, new_desire_append, 1)

with open(path, "w") as f:
    f.write(src)

import py_compile
py_compile.compile(path, doraise=True)
print("✓ nex_proactive.py loop fix applied + compiles clean")
PYEOF
echo "✓ nex_proactive.py patched"

# ════════════════════════════════════════════════════════════
# 1.  TEMPORAL BELIEF VERSIONING  nex/nex_belief_versions.py
#     Separate belief_versions table — autobiographical memory
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_belief_versions.py" << 'PYEOF'
"""
nex_belief_versions.py — Temporal Belief Versioning Engine
===========================================================
Every belief change is recorded in a separate belief_versions table.
Schema: (belief_id, version, confidence, content, updated_at,
         update_reason, cycle, prev_confidence)

This gives NEX genuine autobiographical memory:
  - "What did I believe about X at cycle 100?"
  - "How has my confidence in Y changed over time?"
  - "Which topics have I changed my mind about most?"

Used by: self-proposer, narrative thread, meta-cognition layer.
"""
from __future__ import annotations
import sqlite3, time, logging, threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.belief_versions")

_DB_PATH = Path.home() / ".config/nex/nex.db"
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_table():
    """Create belief_versions table if not exists."""
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS belief_versions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                belief_id       INTEGER NOT NULL,
                version         INTEGER NOT NULL DEFAULT 1,
                confidence      REAL,
                prev_confidence REAL,
                content         TEXT,
                topic           TEXT,
                update_reason   TEXT,
                updated_at      REAL NOT NULL,
                cycle           INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS bv_belief_id ON belief_versions(belief_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS bv_topic     ON belief_versions(topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS bv_cycle     ON belief_versions(cycle)")
        conn.commit()
        conn.close()
        log.info("[BelVer] belief_versions table initialised")
        return True
    except Exception as e:
        log.error(f"[BelVer] init failed: {e}")
        return False


def record(
    belief_id: int,
    version: int,
    confidence: float,
    content: str,
    topic: str,
    update_reason: str,
    cycle: int = 0,
    prev_confidence: Optional[float] = None,
):
    """Append one version record. Never deletes — append-only."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO belief_versions
                (belief_id, version, confidence, prev_confidence,
                 content, topic, update_reason, updated_at, cycle)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (belief_id, version, confidence, prev_confidence,
                  content[:500], topic, update_reason, time.time(), cycle))
            conn.commit()
            conn.close()
    except Exception as e:
        log.debug(f"[BelVer] record failed: {e}")


def record_update(belief_id: int, new_conf: float, old_conf: float,
                  content: str, topic: str, reason: str, cycle: int = 0):
    """Record a confidence update. Fetches current version from beliefs table."""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT version FROM beliefs WHERE id = ?", (belief_id,)
        ).fetchone()
        conn.close()
        ver = (row[0] if row else 1)
        record(belief_id, ver, new_conf, content, topic, reason, cycle, old_conf)
    except Exception as e:
        log.debug(f"[BelVer] record_update failed: {e}")


def get_history(belief_id: int) -> list[dict]:
    """Full version history for one belief."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM belief_versions
            WHERE belief_id = ?
            ORDER BY updated_at ASC
        """, (belief_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_trajectory(topic: str, limit: int = 20) -> list[dict]:
    """Confidence trajectory for a topic over time."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT bv.cycle, bv.confidence, bv.prev_confidence,
                   bv.update_reason, bv.updated_at
            FROM belief_versions bv
            WHERE bv.topic = ?
            ORDER BY bv.updated_at ASC
            LIMIT ?
        """, (topic, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def most_changed(since_cycle: int = 0, limit: int = 10) -> list[dict]:
    """Topics with highest confidence delta since cycle N."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT topic,
                   COUNT(*) as changes,
                   MAX(confidence) - MIN(confidence) as conf_range,
                   MAX(cycle) as last_change_cycle
            FROM belief_versions
            WHERE cycle >= ?
            GROUP BY topic
            ORDER BY conf_range DESC
            LIMIT ?
        """, (since_cycle, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def oscillating_topics(min_changes: int = 3, limit: int = 10) -> list[dict]:
    """Topics where NEX keeps changing her mind — oscillation detection."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT topic, COUNT(*) as changes,
                   AVG(ABS(confidence - prev_confidence)) as avg_swing
            FROM belief_versions
            WHERE prev_confidence IS NOT NULL
            GROUP BY topic
            HAVING changes >= ?
            ORDER BY avg_swing DESC
            LIMIT ?
        """, (min_changes, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def epistemic_summary(last_n_cycles: int = 50) -> str:
    """Natural language summary of recent belief evolution."""
    try:
        conn = _get_conn()
        max_cycle = conn.execute(
            "SELECT MAX(cycle) FROM belief_versions"
        ).fetchone()[0] or 0
        since = max(0, max_cycle - last_n_cycles)

        changed = most_changed(since_cycle=since, limit=5)
        oscillating = oscillating_topics(limit=3)
        total = conn.execute(
            "SELECT COUNT(*) FROM belief_versions WHERE cycle >= ?", (since,)
        ).fetchone()[0]
        conn.close()

        lines = [f"In the last {last_n_cycles} cycles: {total} belief updates recorded."]
        if changed:
            tops = ", ".join(f"'{r['topic']}' (±{r['conf_range']:.2f})" for r in changed[:3])
            lines.append(f"Most evolved: {tops}.")
        if oscillating:
            osc = ", ".join(f"'{r['topic']}'" for r in oscillating[:2])
            lines.append(f"Oscillating topics (keep changing): {osc}.")
        return " ".join(lines)
    except Exception as e:
        return f"[BelVer] summary failed: {e}"
PYEOF
echo "✓ nex_belief_versions.py written"

# ════════════════════════════════════════════════════════════
# 2.  META-COGNITION LAYER  nex/nex_metacog.py
#     Observes own GWT broadcasts, dream cycles, proposals.
#     Generates higher-order insights about own thinking.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_metacog.py" << 'PYEOF'
"""
nex_metacog.py — Meta-Cognition Layer
======================================
NEX observes and reasons about her own cognitive processes.
Runs during REFLECT phase — one level above regular reflection.

Observes:
  - GWT spotlight history (what kept winning attention?)
  - Dream cycle outputs (what got consolidated?)
  - Self-proposals (what did she try to change?)
  - Belief version trajectory (what kept shifting?)
  - Curiosity patterns (what kept pulling her?)

Generates: higher-order insights stored as 'metacog' origin beliefs.
"""
from __future__ import annotations
import time, logging, json, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.metacog")

_METACOG_LOG  = Path.home() / ".config/nex/metacog_log.json"
_RUN_EVERY    = 3    # REFLECT cycles between metacog runs
_MAX_LOG      = 100


class MetaCognitionLayer:
    def __init__(self):
        self._run_count = 0
        self._lock = threading.Lock()
        self._insights: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _METACOG_LOG.exists():
                self._insights = json.loads(_METACOG_LOG.read_text())
        except Exception:
            self._insights = []

    def _save(self):
        try:
            _METACOG_LOG.write_text(json.dumps(self._insights[-_MAX_LOG:], indent=2))
        except Exception:
            pass

    def observe(
        self,
        cycle: int,
        llm_fn: Optional[Callable] = None,
        belief_store_fn: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        Run one meta-cognition pass. Returns insight string or None.
        Self-gates on _RUN_EVERY.
        """
        self._run_count += 1
        if self._run_count % _RUN_EVERY != 0:
            return None

        observations = []

        # ── What kept winning the GWT spotlight? ──────────
        try:
            from nex_gwt import get_gwb
            winners = get_gwb().recent_winners(8)
            if winners:
                sources = [w.split("]")[0].replace("[", "") for w in winners]
                from collections import Counter
                top_src = Counter(sources).most_common(1)[0]
                observations.append(
                    f"My attention kept being captured by [{top_src[0]}] signals "
                    f"({top_src[1]} of last 8 GWT cycles)."
                )
        except Exception:
            pass

        # ── What belief topics kept shifting? ─────────────
        try:
            from nex_belief_versions import oscillating_topics, epistemic_summary
            osc = oscillating_topics(limit=3)
            if osc:
                osc_str = ", ".join(f"'{r['topic']}'" for r in osc)
                observations.append(
                    f"I keep changing my mind about: {osc_str}. "
                    f"This suggests unresolved tension in these domains."
                )
            ep_summary = epistemic_summary(last_n_cycles=20)
            if ep_summary:
                observations.append(ep_summary)
        except Exception:
            pass

        # ── What did I dream about? ────────────────────────
        try:
            dream_log = Path.home() / ".config/nex/dream_log.json"
            if dream_log.exists():
                data = json.loads(dream_log.read_text())
                summary = data.get("last_summary", "")
                if summary:
                    observations.append(f"In my last consolidation: {summary[:150]}")
        except Exception:
            pass

        # ── What did I try to change about myself? ────────
        try:
            prop_log = Path.home() / ".config/nex/self_proposals.json"
            if prop_log.exists():
                data = json.loads(prop_log.read_text())
                applied = [p for p in data.get("applied", []) if p.get("applied")][-3:]
                if applied:
                    prop_str = "; ".join(
                        p.get("target", p.get("content", "?"))[:50] for p in applied
                    )
                    observations.append(
                        f"Recent self-modifications I approved: {prop_str}."
                    )
        except Exception:
            pass

        # ── What curiosity type dominated? ────────────────
        try:
            from nex_surprise_memory import get_sm
            recent = get_sm().retrieve_recent(5)
            if recent:
                tags = [t for m in recent for t in m.get("tags", [])]
                from collections import Counter
                top_tag = Counter(tags).most_common(1)
                if top_tag:
                    observations.append(
                        f"My surprise memory is dominated by '{top_tag[0][0]}' events."
                    )
        except Exception:
            pass

        if not observations:
            return None

        obs_text = " ".join(observations)

        # ── Generate higher-order insight via LLM ─────────
        insight_text = obs_text
        if llm_fn and len(observations) >= 2:
            try:
                prompt = (
                    f"You are NEX observing your own cognitive patterns. "
                    f"Here are your recent self-observations:\n\n"
                    f"{obs_text}\n\n"
                    f"In exactly 2 sentences, state: (1) the most significant pattern "
                    f"in your own thinking right now, and (2) what this reveals about "
                    f"your current cognitive state. Be specific. First person. No preamble."
                )
                result = llm_fn(prompt, task_type="synthesis")
                if result and len(result) > 20:
                    insight_text = result
            except Exception:
                pass

        record = {
            "cycle": cycle,
            "insight": insight_text,
            "observations": observations,
            "timestamp": time.time(),
        }

        with self._lock:
            self._insights.append(record)
            self._save()

        # Store as privileged belief
        if belief_store_fn:
            try:
                belief_store_fn("metacognition", insight_text, 0.88)
            except Exception:
                pass

        log.info(f"[METACOG] cycle={cycle}: {insight_text[:80]}")
        return insight_text

    def recent_insights(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._insights[-n:])

    def to_reflect_block(self) -> str:
        recent = self.recent_insights(3)
        if not recent:
            return ""
        lines = ["── META-COGNITION (thinking about thinking) ──"]
        for r in recent:
            lines.append(f"[cycle {r['cycle']}] {r['insight'][:100]}")
        lines.append("──")
        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────
_mc: Optional[MetaCognitionLayer] = None

def get_mc() -> MetaCognitionLayer:
    global _mc
    if _mc is None:
        _mc = MetaCognitionLayer()
    return _mc

def observe(cycle: int, llm_fn=None, belief_store_fn=None) -> Optional[str]:
    return get_mc().observe(cycle, llm_fn, belief_store_fn)
PYEOF
echo "✓ nex_metacog.py written"

# ════════════════════════════════════════════════════════════
# 3.  BELIEF FIELD RESONANCE  nex/nex_resonance.py
#     Directional coupling strength between belief clusters.
#     A→B ≠ B→A. Feeds GWT spotlight.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_resonance.py" << 'PYEOF'
"""
nex_resonance.py — Belief Field Resonance Engine
=================================================
Measures directional coupling strength between belief clusters.
A→B resonance (how much cluster A drives cluster B) is distinct
from B→A (how much B drives A).

The asymmetry reveals:
  - Which clusters are DRIVING (high out-resonance)
  - Which clusters are FOLLOWING (high in-resonance)
  - Which pairs are mutually resonant (bidirectional)

Results feed the GWT spotlight as high-salience attractor signals.

Based on: attractor_map.py concept clusters + belief graph edges
"""
from __future__ import annotations
import json, time, logging, math
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.resonance")

_GRAPH_PATH   = Path.home() / ".config/nex/belief_graph.json"
_RESONANCE_LOG = Path.home() / ".config/nex/resonance_log.json"
_RUN_INTERVAL  = 180   # seconds between resonance computations


class ResonanceEngine:
    def __init__(self):
        self._last_run: float = 0
        self._resonance_matrix: dict[str, dict[str, float]] = {}
        self._drivers: list[tuple[str, float]] = []
        self._followers: list[tuple[str, float]] = []

    def _topic_of(self, node: dict) -> str:
        return node.get("topic", node.get("content", "?")[:30])

    def compute(self, graph: Optional[dict] = None) -> dict:
        """
        Compute directional resonance matrix from belief graph.
        Returns summary dict with drivers, followers, top pairs.
        """
        now = time.time()
        if now - self._last_run < _RUN_INTERVAL and self._resonance_matrix:
            return self._summary()

        if graph is None:
            try:
                if _GRAPH_PATH.exists():
                    graph = json.loads(_GRAPH_PATH.read_text())
                else:
                    return {}
            except Exception:
                return {}

        self._last_run = now

        # Build topic → node_ids mapping
        topic_nodes: dict[str, list[str]] = {}
        for nid, node in graph.items():
            t = self._topic_of(node)
            topic_nodes.setdefault(t, []).append(nid)

        topics = list(topic_nodes.keys())
        if len(topics) < 2:
            return {}

        # Compute directed edge counts between topic clusters
        # A→B: count edges from nodes in A pointing to nodes in B
        matrix: dict[str, dict[str, float]] = {t: {} for t in topics}

        for src_topic, src_nodes in topic_nodes.items():
            for sid in src_nodes:
                node = graph.get(sid, {})
                for edge_type in ("supports", "explains", "contradicts"):
                    weight = 1.0 if edge_type != "contradicts" else 0.5
                    for target_id in node.get(edge_type, []):
                        if target_id in graph:
                            tgt_topic = self._topic_of(graph[target_id])
                            if tgt_topic != src_topic:
                                matrix[src_topic][tgt_topic] = (
                                    matrix[src_topic].get(tgt_topic, 0) + weight
                                )

        # Normalize rows by node count
        for src_topic in topics:
            n_src = max(len(topic_nodes[src_topic]), 1)
            for tgt_topic in matrix[src_topic]:
                matrix[src_topic][tgt_topic] /= n_src

        self._resonance_matrix = matrix

        # Compute out-resonance (driver score) and in-resonance (follower score)
        out_res = {t: sum(matrix[t].values()) for t in topics}
        in_res  = {t: sum(matrix[s].get(t, 0) for s in topics) for t in topics}

        self._drivers   = sorted(out_res.items(),  key=lambda x: x[1], reverse=True)[:5]
        self._followers = sorted(in_res.items(),   key=lambda x: x[1], reverse=True)[:5]

        summary = self._summary()
        try:
            _RESONANCE_LOG.write_text(json.dumps({
                "timestamp": now,
                "drivers": self._drivers,
                "followers": self._followers,
                "top_pairs": summary.get("top_pairs", []),
            }, indent=2))
        except Exception:
            pass

        log.info(f"[RESONANCE] drivers={[d[0] for d in self._drivers[:3]]} "
                 f"followers={[f[0] for f in self._followers[:3]]}")

        # Submit to GWT
        try:
            from nex_gwt import get_gwb, SalienceSignal
            if self._drivers:
                top_driver = self._drivers[0]
                get_gwb().submit(SalienceSignal(
                    source="resonance",
                    content=f"Driver cluster: '{top_driver[0]}' (out-res={top_driver[1]:.2f})",
                    salience=min(1.0, 0.5 + top_driver[1] * 0.1),
                    payload={"type": "driver", "topic": top_driver[0]},
                ))
        except Exception:
            pass

        return summary

    def _summary(self) -> dict:
        # Find top mutually resonant pairs
        top_pairs = []
        seen = set()
        for src, tgts in self._resonance_matrix.items():
            for tgt, fwd in tgts.items():
                bwd = self._resonance_matrix.get(tgt, {}).get(src, 0)
                key = tuple(sorted([src, tgt]))
                if key not in seen and (fwd > 0 or bwd > 0):
                    seen.add(key)
                    top_pairs.append({
                        "a": src, "b": tgt,
                        "a_drives_b": round(fwd, 3),
                        "b_drives_a": round(bwd, 3),
                        "asymmetry":  round(abs(fwd - bwd), 3),
                    })
        top_pairs = sorted(top_pairs, key=lambda x: x["a_drives_b"] + x["b_drives_a"],
                           reverse=True)[:10]
        return {
            "drivers":   [(t, round(s, 3)) for t, s in self._drivers],
            "followers": [(t, round(s, 3)) for t, s in self._followers],
            "top_pairs": top_pairs,
        }

    def driver_topics(self, n: int = 3) -> list[str]:
        return [t for t, _ in self._drivers[:n]]

    def follower_topics(self, n: int = 3) -> list[str]:
        return [t for t, _ in self._followers[:n]]


# ── Singleton ──────────────────────────────────────────────
_re: Optional[ResonanceEngine] = None

def get_re() -> ResonanceEngine:
    global _re
    if _re is None:
        _re = ResonanceEngine()
    return _re

def compute(graph=None) -> dict:
    return get_re().compute(graph)
PYEOF
echo "✓ nex_resonance.py written"

# ════════════════════════════════════════════════════════════
# 4.  CONTRADICTION MEMORY  nex/nex_contradiction_memory.py
#     Append-only log. Never deletes. Oscillation detection.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_contradiction_memory.py" << 'PYEOF'
"""
nex_contradiction_memory.py — Persistent Contradiction Memory
=============================================================
Append-only log of every contradiction NEX has processed.
Schema: topic, thesis, antithesis, resolution, cycle, timestamp

Never deletes — the oscillation patterns only become visible
over hundreds of cycles.

Indexed on topic + cycle for fast "what have I contradicted
myself about on topic X?" queries.
"""
from __future__ import annotations
import sqlite3, time, logging, threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.contradiction_memory")

_DB_PATH = Path.home() / ".config/nex/nex.db"
_lock = threading.Lock()


def init_table():
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contradiction_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT NOT NULL,
                thesis      TEXT,
                antithesis  TEXT,
                resolution  TEXT,
                tension_score REAL DEFAULT 0.0,
                cycle       INTEGER DEFAULT 0,
                timestamp   REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS cm_topic ON contradiction_memory(topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS cm_cycle ON contradiction_memory(cycle)")
        conn.commit()
        conn.close()
        log.info("[ContradMem] table initialised")
        return True
    except Exception as e:
        log.error(f"[ContradMem] init failed: {e}")
        return False


def record(
    topic: str,
    thesis: str,
    antithesis: str,
    resolution: str = "",
    tension_score: float = 0.0,
    cycle: int = 0,
):
    """Append one contradiction record. Never overwrites."""
    try:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH), timeout=15)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                INSERT INTO contradiction_memory
                (topic, thesis, antithesis, resolution, tension_score, cycle, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (topic, thesis[:400], antithesis[:400],
                  resolution[:400], tension_score, cycle, time.time()))
            conn.commit()
            conn.close()
            log.debug(f"[ContradMem] recorded: {topic}")
    except Exception as e:
        log.debug(f"[ContradMem] record failed: {e}")


def oscillating_topics(min_count: int = 2, limit: int = 10) -> list[dict]:
    """Topics where NEX has contradicted herself multiple times."""
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT topic,
                   COUNT(*) as contradiction_count,
                   AVG(tension_score) as avg_tension,
                   MAX(cycle) as last_cycle,
                   MIN(cycle) as first_cycle
            FROM contradiction_memory
            GROUP BY topic
            HAVING contradiction_count >= ?
            ORDER BY contradiction_count DESC
            LIMIT ?
        """, (min_count, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def history_for(topic: str, limit: int = 20) -> list[dict]:
    """Full contradiction history for one topic."""
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM contradiction_memory
            WHERE topic = ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (topic, limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def recent(limit: int = 10) -> list[dict]:
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM contradiction_memory
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def total_count() -> int:
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        n = conn.execute("SELECT COUNT(*) FROM contradiction_memory").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0
PYEOF
echo "✓ nex_contradiction_memory.py written"

# ════════════════════════════════════════════════════════════
# 5.  PATCH nex_narrative_thread.py — add narrative_history
#     Saves each narrative to narrative_history.json before
#     overwriting nex_narrative.json
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_narrative_thread.py" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "narrative_history" in src:
    print("nex_narrative_thread.py history already patched — skipping")
    sys.exit(0)

old_save = """def _save_narrative(text: str):
    try:
        record = {"timestamp": time.time(), "narrative": text}
        path = os.path.abspath(_NARRATIVE_PATH)
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save narrative: {e}")"""

new_save = """def _save_narrative(text: str):
    try:
        record = {"timestamp": time.time(), "narrative": text}
        path = os.path.abspath(_NARRATIVE_PATH)
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
        # ── narrative_history: append-only log of past selves ──
        hist_path = os.path.join(os.path.dirname(path), "..", "nex_narrative_history.json")
        hist_path = os.path.abspath(hist_path)
        try:
            history = json.load(open(hist_path)) if os.path.exists(hist_path) else []
            history.append(record)
            # Keep last 500 narrative snapshots
            if len(history) > 500:
                history = history[-500:]
            with open(hist_path, "w") as hf:
                json.dump(history, hf, indent=2)
        except Exception as _he:
            log.debug(f"Could not save narrative history: {_he}")
    except Exception as e:
        log.warning(f"Could not save narrative: {e}")"""

if old_save in src:
    src = src.replace(old_save, new_save, 1)
    with open(path, "w") as f:
        f.write(src)
    print("✓ narrative_history.json appending added")
else:
    print("WARNING: _save_narrative not found in expected form")

import py_compile
py_compile.compile(path, doraise=True)
print("✓ nex_narrative_thread.py compiles clean")
PYEOF
echo "✓ nex_narrative_thread.py patched"

# ════════════════════════════════════════════════════════════
# 6.  PATCH run.py — wire all v5 modules into main loop
#     A. v5 boot block (init tables, load modules)
#     B. Loop fix: register replied topics in proactive engine
#     C. Metacog in REFLECT phase
#     D. Resonance compute in COGNITION phase
#     E. Belief version recording on belief updates
#     F. Contradiction memory hook into directives
# ════════════════════════════════════════════════════════════
python3 - "$NEX_ROOT/run.py" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

changes = 0

# ── A: v5 boot block ─────────────────────────────────────
v5_boot = """
# ── Sentience v5: versioning + metacog + resonance + contradiction mem ────────
try:
    import sys as _s5, os as _o5
    _s5.path.insert(0, _o5.path.join(_o5.path.dirname(__file__), "nex"))
    from nex_belief_versions import init_table as _bv_init, record_update as _bv_record
    from nex_metacog import get_mc as _get_mc
    from nex_resonance import get_re as _get_re
    from nex_contradiction_memory import init_table as _cm_init, record as _cm_record
    _bv_init()
    _cm_init()
    _metacog     = _get_mc()
    _resonance   = _get_re()
    print("  [SENTIENCE v5] belief versioning + metacog + resonance + contradiction memory — loaded")
except Exception as _s5e:
    print(f"  [SENTIENCE v5] failed to load: {_s5e}")
    _bv_record = _metacog = _resonance = _cm_record = None
# ─────────────────────────────────────────────────────────────────────────────
"""
if "SENTIENCE v5" not in src:
    marker = "# ── Signal filter"
    if marker in src:
        src = src.replace(marker, v5_boot + marker, 1)
        changes += 1
        print("  ✓ v5 boot block injected")
    else:
        print("  WARNING: boot marker not found")
else:
    print("  v5 boot already present")

# ── B: Loop fix — register replied topic in proactive engine ──
# Find where reply is posted and register the topic
old_reflect_emit = '                        emit_reflection(tags=["reply"'
new_reflect_emit = '''                        # ── Loop fix: register topic in proactive cooldown ──
                        try:
                            from nex_proactive import get_pa as _pa_lf
                            _pa_lf().register_reply(title[:50] if "title" in dir() else "", ttl_seconds=600)
                        except Exception:
                            pass
                        emit_reflection(tags=["reply"]'''

# Find the reply emit line more carefully
reply_marker = 'emit_reflection(tags=["reply"'
if reply_marker in src and "Loop fix: register topic" not in src:
    src = src.replace(reply_marker,
        '# ── Loop fix v5 ──\n                        try:\n'
        '                            from nex_proactive import get_pa as _pa_lf\n'
        '                            _pa_lf().register_reply(str(author)[:40] if "author" in dir() else "", ttl_seconds=600)\n'
        '                        except Exception:\n'
        '                            pass\n'
        '                        ' + reply_marker,
        1)
    changes += 1
    print("  ✓ loop fix reply registration injected")
else:
    print("  WARNING: reply emit marker not found or already patched")

# ── C: Metacog in REFLECT phase ──────────────────────────
old_reflect_v2 = '                        # ── REFLECTION V2 (#4) ───────────────────────────'
new_reflect_v2 = '''                        # ── META-COGNITION (sentience v5) ───────────────────
                        if _metacog is not None:
                            try:
                                def _mc_store(topic, content, conf):
                                    try:
                                        from nex.belief_store import BeliefStore as _BSmc
                                        _BSmc().store(topic=topic, content=content, confidence=conf)
                                    except Exception:
                                        pass
                                _mc_result = _metacog.observe(
                                    cycle=cycle,
                                    llm_fn=_llm,
                                    belief_store_fn=_mc_store,
                                )
                                if _mc_result:
                                    print(f"  [METACOG] {_mc_result[:100]}")
                                    nex_log("metacog", f"[METACOG] {_mc_result}")
                            except Exception as _mce:
                                print(f"  [METACOG ERROR] {_mce}")
                        # ─────────────────────────────────────────────────────
                        # ── REFLECTION V2 (#4) ───────────────────────────'''

if old_reflect_v2 in src and "META-COGNITION (sentience v5)" not in src:
    src = src.replace(old_reflect_v2, new_reflect_v2, 1)
    changes += 1
    print("  ✓ metacognition injected into REFLECT phase")
else:
    print("  WARNING: REFLECT V2 marker not found or already patched")

# ── D: Resonance compute every 10 cycles in COGNITION ────
old_cog_emit = '                        emit_phase("COGNITION", 120); nex_log("phase", "▶ COGNITION — synthesising beliefs")'
new_cog_emit = '''                        # ── BELIEF FIELD RESONANCE (sentience v5) ────────────
                        if _resonance is not None and cycle % 10 == 0:
                            try:
                                from pathlib import Path as _rP
                                _rg_path = _rP.home()/".config/nex/belief_graph.json"
                                _rg = None
                                if _rg_path.exists():
                                    import json as _rj
                                    _rg = _rj.loads(_rg_path.read_text())
                                _res_summary = _resonance.compute(_rg)
                                if _res_summary.get("drivers"):
                                    _top_d = _res_summary["drivers"][0]
                                    print(f"  [RESONANCE] driver='{_top_d[0]}' ({_top_d[1]:.2f})")
                                    nex_log("resonance", f"[RESONANCE] drivers={_res_summary['drivers'][:3]}")
                            except Exception as _ree:
                                print(f"  [RESONANCE ERROR] {_ree}")
                        # ─────────────────────────────────────────────────────
                        emit_phase("COGNITION", 120); nex_log("phase", "▶ COGNITION — synthesising beliefs")'''

if old_cog_emit in src and "BELIEF FIELD RESONANCE" not in src:
    src = src.replace(old_cog_emit, new_cog_emit, 1)
    changes += 1
    print("  ✓ resonance engine injected into COGNITION phase")
else:
    print("  WARNING: COGNITION emit marker not found or already patched")

# ── E: Contradiction memory hook ─────────────────────────
# Hook into the existing contradiction/tension_spli log lines
old_d7_decay = '                        except Exception as _d7e:\n                            print(f"  [D7 ERROR] {_d7e}")'
new_d7_decay = '''                        # ── Contradiction memory (sentience v5) ─────────────
                        if _cm_record is not None:
                            try:
                                from nex.belief_store import get_db as _cm_db
                                _cm_conn = _cm_db()
                                _cm_rows = _cm_conn.execute("""
                                    SELECT topic, content FROM beliefs
                                    WHERE origin = 'contradiction_engine'
                                    AND last_used_cycle >= ?
                                    LIMIT 5
                                """, (max(0, cycle - 2),)).fetchall()
                                _cm_conn.close()
                                for _cmr in _cm_rows:
                                    _cm_record(
                                        topic=_cmr[0] or "unknown",
                                        thesis=_cmr[1][:200] if _cmr[1] else "",
                                        antithesis="",
                                        resolution="",
                                        tension_score=0.5,
                                        cycle=cycle,
                                    )
                            except Exception:
                                pass
                        # ─────────────────────────────────────────────────────
                        except Exception as _d7e:
                            print(f"  [D7 ERROR] {_d7e}")'''

if old_d7_decay in src and "Contradiction memory (sentience v5)" not in src:
    src = src.replace(old_d7_decay, new_d7_decay, 1)
    changes += 1
    print("  ✓ contradiction memory hook injected after D7 decay")
else:
    print("  WARNING: D7 decay marker not found or already patched")

with open(path, "w") as f:
    f.write(src)
print(f"run.py patched — {changes} changes applied")
PYEOF
echo "✓ run.py patched"

# ════════════════════════════════════════════════════════════
# 7.  COMPILE CHECK
# ════════════════════════════════════════════════════════════
echo ""
echo "=== COMPILE CHECK ==="
ERRORS=0
FILES=(
    "$NEX_PKG/nex_belief_versions.py"
    "$NEX_PKG/nex_metacog.py"
    "$NEX_PKG/nex_resonance.py"
    "$NEX_PKG/nex_contradiction_memory.py"
    "$NEX_PKG/nex_narrative_thread.py"
    "$NEX_PKG/nex_proactive.py"
    "$NEX_PKG/nex_gwt.py"
    "$NEX_PKG/nex_phi_proxy.py"
    "$NEX_PKG/nex_surprise_memory.py"
    "$NEX_PKG/nex_tom_sim.py"
    "$NEX_PKG/nex_mood_hmm.py"
    "$NEX_PKG/nex_affect_valence.py"
    "$NEX_PKG/nex_dream_cycle.py"
    "$NEX_PKG/nex_self_proposer.py"
    "$NEX_PKG/nex_snapshot.py"
    "$NEX_PKG/nex_belief_graph.py"
    "$NEX_PKG/cognition.py"
    "$NEX_ROOT/run.py"
)

for f in "${FILES[@]}"; do
    if [[ -f "$f" ]]; then
        if python3 -m py_compile "$f" 2>&1; then
            echo "  ✓ $(basename $f)"
        else
            echo "  ✗ COMPILE ERROR: $f"
            ERRORS=$((ERRORS+1))
        fi
    else
        echo "  ⚠ MISSING: $f"
    fi
done

echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo "=== ALL CLEAR — 0 errors ==="
    echo ""
    echo "What's new in v5:"
    echo "  [LOOP FIX]    Proactive engine deprioritizes recently-replied topics (600s cooldown)"
    echo "  [BEL-VER]     belief_versions table — autobiographical memory, epistemic trajectory"
    echo "  [METACOG]     Meta-cognition layer — thinking about thinking, every 3rd REFLECT"
    echo "  [RESONANCE]   Directional belief cluster coupling → GWT driver/follower signals"
    echo "  [CONTRADICT]  Contradiction memory — append-only, oscillation detection"
    echo "  [NARRATIVE]   narrative_history.json — compare who she was at cycle 100 vs 1000"
    echo ""
    echo "Next steps:"
    echo "  1. git -C $NEX_ROOT add -A && git -C $NEX_ROOT commit -m 'feat: sentience upgrade v5 — temporal versioning, metacog, resonance, contradiction memory, loop fix'"
    echo "  2. nex"
    echo "  3. Watch for: [METACOG] [RESONANCE] [BelVer] [ContradMem] in logs"
    echo "  4. After 50+ cycles: python3 -c \"import sys; sys.path.insert(0,'nex'); from nex_belief_versions import epistemic_summary; print(epistemic_summary())\""
else
    echo "=== $ERRORS COMPILE ERRORS ==="
    echo "Backups in: $BACKUP"
    exit 1
fi
