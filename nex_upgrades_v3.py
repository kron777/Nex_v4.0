"""
nex_upgrades_v3.py  —  NEX Cognitive Architecture v3
=====================================================
Wires the 7 built-but-unwired systems into a unified tick,
and implements the 3 missing pieces:

  WIRED (existed, never called per-cycle):
    1. AttentionIndex       — replaces flat query_beliefs across all phases
    2. TensionMap           — feeds hot topics into attention + synthesis priority
    3. SelfModel            — updates every 50 cycles, injects into system prompt
    4. BeliefMutation       — runs every 3 cycles
    5. BeliefSurvival       — energy cycle every cycle
    6. Decay (DB-native)    — replaces stale JSON-based nex_decay.py
    7. Dialectic Resolver   — structured thesis/antithesis/synthesis on tensions

  BUILT HERE (missing):
    8. BeliefHierarchy      — L0 raw → L1 pattern → L2 abstraction → L3 meta
    9. ContextFramer        — attaches domain/time/reliability context to beliefs
   10. InsightCompressor     — periodically collapses insights into abstractions

Drop this file in ~/Desktop/nex/
Wire into run.py with the patch block shown at the bottom of this file.

Usage in run.py:
    from nex_upgrades_v3 import get_v3
    _v3 = get_v3()
    _v3.init()                          # once, before cycle loop

    # each cycle:
    _v3.tick(cycle=cycle, avg_conf=_avg_conf_real,
             llm_fn=_llm, log_fn=nex_log)

    # after a reply that used beliefs:
    _v3.on_belief_used(content=belief_content, belief_id=bid)

    # in _build_system():
    base += _v3.system_prompt_block()
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
_CFG = Path.home() / ".config" / "nex"
_DB  = _CFG / "nex.db"
_CFG.mkdir(parents=True, exist_ok=True)

_G  = "\033[92m"; _Y = "\033[93m"; _R = "\033[91m"
_CY = "\033[96m"; _D = "\033[2m";  _RS = "\033[0m"


# =============================================================================
# SYSTEM 1 — ATTENTION INDEX WRAPPER
# =============================================================================

class _AttentionLayer:
    def __init__(self):
        self._attn  = None
        self._ready = False

    def _init(self):
        if self._ready:
            return
        try:
            from nex_attention import get_attention_index
            self._attn  = get_attention_index()
            self._ready = True
        except Exception as e:
            print(f"  [V3:Attention] load failed: {e}")

    def sync_tension(self, tensioned_ids: set):
        self._init()
        if self._attn and tensioned_ids:
            self._attn._contradicted_cache = tensioned_ids
            self._attn._cache_ts           = time.time()

    def query(self, phase="default", min_confidence=0.3,
              limit=200, query=None, topic=None) -> list:
        self._init()
        if not self._attn:
            return []
        try:
            return self._attn.query(
                min_confidence=min_confidence,
                limit=limit, phase=phase,
                query=query, topic=topic,
            )
        except Exception:
            return []

    def mark_used(self, belief_ids: list):
        self._init()
        if self._attn and belief_ids:
            try:
                self._attn.update_referenced(belief_ids)
            except Exception:
                pass


# =============================================================================
# SYSTEM 2 — TENSION MAP
# =============================================================================

class _TensionLayer:
    def __init__(self):
        self._tm    = None
        self._ready = False

    def _init(self):
        if self._ready:
            return
        try:
            from nex_tension import get_tension_map
            self._tm    = get_tension_map()
            self._ready = True
        except Exception as e:
            print(f"  [V3:Tension] load failed: {e}")

    def update(self, cycle: int) -> tuple:
        self._init()
        if not self._tm:
            return 0, set()
        try:
            count = self._tm.update(cycle=cycle)
            ids   = self._tm.all_tensioned_ids()
            return count, ids
        except Exception:
            return 0, set()

    def hot_topics(self, n=10) -> list:
        self._init()
        if not self._tm:
            return []
        try:
            return self._tm.hot_topics(n=n)
        except Exception:
            return []

    def summary(self) -> str:
        self._init()
        if not self._tm:
            return "tension unavailable"
        try:
            return self._tm.summary()
        except Exception:
            return ""

    def stats(self) -> dict:
        self._init()
        if not self._tm:
            return {}
        try:
            return self._tm.stats()
        except Exception:
            return {}


# =============================================================================
# SYSTEM 3 — SELF MODEL
# =============================================================================

class _SelfModelLayer:
    def __init__(self):
        self._sm    = None
        self._ready = False

    def _init(self):
        if self._ready:
            return
        try:
            from nex_self_model import get_self_model
            self._sm    = get_self_model()
            self._ready = True
        except Exception as e:
            print(f"  [V3:SelfModel] load failed: {e}")

    def tick(self, cycle: int, log_fn=None) -> list:
        if cycle % 50 != 0:
            return []
        self._init()
        if not self._sm:
            return []
        try:
            events = self._sm.update(cycle=cycle)
            if events and log_fn:
                for ev in events:
                    log_fn("self_model", f"[SELF] {ev}")
                    print(f"  [SELF] {ev}")
            return events
        except Exception as e:
            print(f"  [V3:SelfModel] error: {e}")
            return []

    def prompt_block(self) -> str:
        self._init()
        if not self._sm:
            return ""
        try:
            return self._sm.prompt_block()
        except Exception:
            return ""

    def recent_change(self) -> str:
        self._init()
        if not self._sm:
            return ""
        try:
            return self._sm.recent_change()
        except Exception:
            return ""

    def summary(self) -> str:
        self._init()
        if not self._sm:
            return "not loaded"
        try:
            return self._sm.summary()
        except Exception:
            return ""


# =============================================================================
# SYSTEM 4 — BELIEF MUTATION
# =============================================================================

class _MutationLayer:
    def tick(self, cycle: int, llm_fn=None, log_fn=None) -> dict:
        if cycle % 3 != 0:
            return {}
        try:
            from nex_belief_mutation import run_mutation_cycle
            result = run_mutation_cycle(cycle=cycle, llm_fn=llm_fn, verbose=False)
            if result.get("total", 0) > 0 and log_fn:
                log_fn("mutation",
                       f"[Mutation] perturbed={result.get('perturbed',0)} "
                       f"flipped={result.get('flipped',0)} "
                       f"linked={result.get('linked',0)}")
            return result
        except Exception as e:
            print(f"  [V3:Mutation] error: {e}")
            return {}


# =============================================================================
# SYSTEM 5 — BELIEF SURVIVAL / ENERGY
# =============================================================================

class _SurvivalLayer:
    _initialised = False

    def tick(self, cycle: int, log_fn=None) -> dict:
        try:
            from nex_belief_survival import (
                run_energy_cycle,
                initialise_energy_for_existing_beliefs,
            )
            if not _SurvivalLayer._initialised:
                initialise_energy_for_existing_beliefs()
                _SurvivalLayer._initialised = True
            result = run_energy_cycle(verbose=(cycle % 10 == 0))
            if result.get("killed", 0) > 0 and log_fn:
                log_fn("belief",
                       f"[Survival] killed={result['killed']} "
                       f"amplified={result['amplified']}")
            return result
        except Exception as e:
            print(f"  [V3:Survival] error: {e}")
            return {}

    def boost(self, content: str = None, belief_id: int = None):
        try:
            if belief_id is not None:
                from nex_belief_survival import boost_belief_energy_by_id
                boost_belief_energy_by_id(belief_id)
            elif content:
                from nex_belief_survival import boost_belief_energy
                boost_belief_energy(content)
        except Exception:
            pass


# =============================================================================
# SYSTEM 6 — DB-NATIVE DECAY
# Replaces stale JSON-based nex_decay.py
# =============================================================================

_DECAY_RATE           = 0.003
_DECAY_RATE_VALIDATED = 0.0005
_DECAY_MIN_CONF       = 0.05
_DECAY_FLOOR_TOTAL    = 800

class _DecayLayer:
    def tick(self, cycle: int, log_fn=None) -> dict:
        # 24h at 120s/cycle ≈ 720 cycles
        if cycle % 720 != 0:
            return {}
        if not _DB.exists():
            return {}
        try:
            db    = sqlite3.connect(str(_DB))
            total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]

            db.execute("""
                UPDATE beliefs
                SET confidence = MAX(
                    confidence - (
                        CASE WHEN human_validated = 1
                             THEN ?
                             ELSE ?
                        END
                        * MAX(1, CAST(
                            (julianday('now') - julianday(
                                COALESCE(last_referenced, timestamp, '2024-01-01')
                            )) AS REAL
                          ))
                    ),
                    0.0
                )
                WHERE confidence > 0
            """, (_DECAY_RATE_VALIDATED, _DECAY_RATE))
            decayed = db.execute("SELECT changes()").fetchone()[0]

            pruned = 0
            if total > _DECAY_FLOOR_TOTAL:
                db.execute("""
                    DELETE FROM beliefs
                    WHERE confidence < ?
                      AND human_validated = 0
                      AND (origin NOT IN ('identity_core','dream_inversion')
                           OR origin IS NULL)
                """, (_DECAY_MIN_CONF,))
                pruned = db.execute("SELECT changes()").fetchone()[0]

            db.commit()
            db.close()
            msg = f"[DecayDB] decayed={decayed} pruned={pruned} total={total}"
            print(f"  {msg}")
            if log_fn:
                log_fn("decay", msg)
            return {"decayed": decayed, "pruned": pruned}
        except Exception as e:
            print(f"  [V3:Decay] error: {e}")
            return {}


# =============================================================================
# SYSTEM 7 — DIALECTIC RESOLVER
# thesis → antithesis → synthesis on high-tension belief pairs
# =============================================================================

_DIALECTIC_LOG = _CFG / "dialectic_resolutions.json"

class _DialecticLayer:

    def tick(self, cycle: int, hot_topics: list,
             llm_fn=None, log_fn=None) -> int:
        if cycle % 10 != 0 or not llm_fn or not hot_topics:
            return 0
        if not _DB.exists():
            return 0

        resolved = 0
        try:
            db = sqlite3.connect(str(_DB))

            for node in hot_topics[:3]:
                topic         = node.topic
                tension_score = node.tension_score
                if tension_score < 0.3:
                    continue

                beliefs = db.execute("""
                    SELECT id, content, confidence FROM beliefs
                    WHERE topic = ? AND confidence >= 0.35
                    ORDER BY confidence DESC LIMIT 8
                """, (topic,)).fetchall()
                if len(beliefs) < 2:
                    continue

                pairs = node.conflicting_pairs[:3] if node.conflicting_pairs else []
                if not pairs:
                    pairs = [(beliefs[0][0], beliefs[-1][0])]

                for pid, cid in pairs[:2]:
                    p_row = next((b for b in beliefs if b[0] == pid), None)
                    c_row = next((b for b in beliefs if b[0] == cid), None)
                    if not p_row or not c_row:
                        continue

                    thesis     = p_row[1]
                    antithesis = c_row[1]

                    prompt = (
                        f"You are a belief synthesis engine.\n\n"
                        f"Topic: '{topic}'\n"
                        f"THESIS:     {thesis[:200]}\n"
                        f"ANTITHESIS: {antithesis[:200]}\n\n"
                        f"Choose ONE resolution mode and write a synthesis:\n"
                        f"- integration: merge into one unified belief\n"
                        f"- abstraction: form a higher-level principle\n"
                        f"- context_split: specify conditions where each is true\n"
                        f"- dominance: state which is more accurate and why\n\n"
                        f'Reply JSON only: {{"mode":"...","synthesis":"one sentence"}}'
                    )

                    try:
                        result = llm_fn(prompt, task_type="synthesis")
                        if not result or len(result) < 20:
                            continue
                        match = re.search(r'\{[^}]+\}', result, re.DOTALL)
                        if not match:
                            continue
                        data      = json.loads(match.group())
                        mode      = data.get("mode", "integration")
                        synthesis = data.get("synthesis", "").strip()
                        if not synthesis or len(synthesis) < 15:
                            continue

                        tags = json.dumps(["dialectic", mode, topic, "synthesis"])
                        db.execute("""
                            INSERT OR IGNORE INTO beliefs
                            (content, confidence, source, topic, tags, timestamp)
                            VALUES (?, 0.78, 'dialectic_resolver', ?, ?, ?)
                        """, (synthesis[:500], topic, tags,
                              datetime.now().isoformat()))

                        _entry = {
                            "ts": datetime.now().isoformat(), "cycle": cycle,
                            "topic": topic, "mode": mode,
                            "thesis": thesis[:100], "antithesis": antithesis[:100],
                            "synthesis": synthesis, "tension": tension_score,
                        }
                        _log = []
                        if _DIALECTIC_LOG.exists():
                            try:
                                _log = json.loads(_DIALECTIC_LOG.read_text())
                            except Exception:
                                pass
                        _log.append(_entry)
                        _DIALECTIC_LOG.write_text(
                            json.dumps(_log[-200:], indent=2))

                        resolved += 1
                        msg = f"[Dialectic] {mode} → '{topic}': {synthesis[:60]}"
                        print(f"  {_CY}{msg}{_RS}")
                        if log_fn:
                            log_fn("dialectic", msg)

                    except Exception:
                        continue

            db.commit()
            db.close()
        except Exception as e:
            print(f"  [V3:Dialectic] error: {e}")

        return resolved


# =============================================================================
# SYSTEM 8 — BELIEF HIERARCHY  (NEW)
# L0 raw observation → L1 pattern → L2 abstraction → L3 meta-belief
# =============================================================================

_HIERARCHY_COLS_ADDED = False

def _ensure_hierarchy_cols():
    global _HIERARCHY_COLS_ADDED
    if _HIERARCHY_COLS_ADDED or not _DB.exists():
        return
    try:
        db   = sqlite3.connect(str(_DB))
        cols = [r[1] for r in db.execute("PRAGMA table_info(beliefs)").fetchall()]
        added = []
        if "belief_level" not in cols:
            db.execute("ALTER TABLE beliefs ADD COLUMN belief_level INTEGER DEFAULT 0")
            added.append("belief_level")
        if "parent_belief_id" not in cols:
            db.execute("ALTER TABLE beliefs ADD COLUMN parent_belief_id INTEGER DEFAULT NULL")
            added.append("parent_belief_id")
        if "supports_ids" not in cols:
            db.execute("ALTER TABLE beliefs ADD COLUMN supports_ids TEXT DEFAULT NULL")
            added.append("supports_ids")
        if added:
            db.commit()
            print(f"  [V3:Hierarchy] added columns: {', '.join(added)}")
        db.close()
        _HIERARCHY_COLS_ADDED = True
    except Exception as e:
        print(f"  [V3:Hierarchy] schema error: {e}")


_L1_SIGNALS = {"pattern","trend","often","frequently","consistently","generally",
               "typically","correlation","associated","linked","tends","suggests",
               "indicates","implies","repeatedly","commonly","usually"}
_L2_SIGNALS = {"principle","framework","theory","model","abstraction","concept",
               "generalize","underlying","fundamental","basis","structure",
               "mechanism","explains","governs","shapes","drives","enables"}
_L3_SIGNALS = {"meta","identity","system","universal","axiom","core","self",
               "govern","overarch","global","define","consciousness","always",
               "belief itself","intrinsic","ontological","irreducible"}
_STOP_H = {"there","their","which","about","could","would","should","being",
           "after","before","within","without","because","these","those"}


def _classify_level(content: str) -> int:
    words = set(re.findall(r'\b[a-z]{4,}\b', content.lower()))
    if words & _L3_SIGNALS:
        return 3
    if words & _L2_SIGNALS:
        return 2
    if words & _L1_SIGNALS:
        return 1
    return 0


class _HierarchyLayer:

    def tick(self, cycle: int, log_fn=None) -> dict:
        if cycle % 15 != 0:
            return {}
        _ensure_hierarchy_cols()
        if not _DB.exists():
            return {}
        try:
            db   = sqlite3.connect(str(_DB))
            rows = db.execute("""
                SELECT id, content FROM beliefs
                WHERE (belief_level IS NULL OR belief_level = 0)
                  AND confidence >= 0.4
                ORDER BY confidence DESC LIMIT 500
            """).fetchall()

            counts   = {0: 0, 1: 0, 2: 0, 3: 0}
            for bid, content in rows:
                level = _classify_level(content or "")
                if level > 0:
                    db.execute(
                        "UPDATE beliefs SET belief_level = ? WHERE id = ?",
                        (level, bid))
                    counts[level] += 1

            # Promote L1 beliefs referenced by 5+ other beliefs → L2
            promoted = 0
            l1s = db.execute("""
                SELECT id, content FROM beliefs
                WHERE belief_level = 1 AND confidence >= 0.65
                LIMIT 100
            """).fetchall()
            for bid, content in l1s:
                words = [w for w in re.findall(r'\b[a-z]{5,}\b', content.lower())
                         if w not in _STOP_H]
                if not words:
                    continue
                kw   = words[0]
                refs = db.execute(
                    "SELECT COUNT(*) FROM beliefs WHERE content LIKE ? AND id != ?",
                    (f"%{kw}%", bid)
                ).fetchone()[0]
                if refs >= 5:
                    db.execute(
                        "UPDATE beliefs SET belief_level = 2 WHERE id = ?", (bid,))
                    promoted += 1

            db.commit()
            db.close()

            total = sum(counts.values())
            if total > 0 or promoted > 0:
                msg = (f"[Hierarchy] L1={counts[1]} L2={counts[2]} "
                       f"L3={counts[3]} promoted={promoted}")
                print(f"  {_D}{msg}{_RS}")
                if log_fn:
                    log_fn("hierarchy", msg)
            return {"classified": total, "promoted": promoted}
        except Exception as e:
            print(f"  [V3:Hierarchy] error: {e}")
            return {}

    def get_meta_beliefs(self, limit=10) -> list:
        _ensure_hierarchy_cols()
        if not _DB.exists():
            return []
        try:
            db   = sqlite3.connect(str(_DB))
            rows = db.execute("""
                SELECT content, confidence, topic FROM beliefs
                WHERE belief_level = 3
                ORDER BY confidence DESC LIMIT ?
            """, (limit,)).fetchall()
            db.close()
            return [{"content": r[0], "confidence": r[1], "topic": r[2]}
                    for r in rows]
        except Exception:
            return []

    def synthesis_priority_topics(self, n=5) -> list:
        _ensure_hierarchy_cols()
        if not _DB.exists():
            return []
        try:
            db   = sqlite3.connect(str(_DB))
            rows = db.execute("""
                SELECT topic, MAX(belief_level) as max_level, COUNT(*) as cnt
                FROM beliefs
                WHERE belief_level >= 2 AND topic IS NOT NULL
                GROUP BY topic
                ORDER BY max_level DESC, cnt DESC LIMIT ?
            """, (n,)).fetchall()
            db.close()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []


# =============================================================================
# SYSTEM 9 — CONTEXT FRAMER  (NEW)
# Attaches domain / time / reliability context to beliefs.
# Reduces false contradictions from cross-context comparisons.
# =============================================================================

_CONTEXT_COL_ADDED = False

def _ensure_context_col():
    global _CONTEXT_COL_ADDED
    if _CONTEXT_COL_ADDED or not _DB.exists():
        return
    try:
        db   = sqlite3.connect(str(_DB))
        cols = [r[1] for r in db.execute("PRAGMA table_info(beliefs)").fetchall()]
        if "context_frame" not in cols:
            db.execute(
                "ALTER TABLE beliefs ADD COLUMN context_frame TEXT DEFAULT NULL")
            db.commit()
            print("  [V3:ContextFramer] added context_frame column")
        db.close()
        _CONTEXT_COL_ADDED = True
    except Exception as e:
        print(f"  [V3:ContextFramer] schema error: {e}")


_DOMAIN_MAP = {
    "security":   {"security","vulnerability","exploit","attack","defense","threat",
                   "malware","encrypt","breach","penetration","cyber","adversarial"},
    "ai":         {"intelligence","neural","model","language","llm","gpt","agent",
                   "learning","training","inference","embedding","transformer","reasoning"},
    "blockchain": {"blockchain","crypto","consensus","token","defi","contract",
                   "bitcoin","ethereum","web3","nft","wallet","decentralized"},
    "philosophy": {"consciousness","identity","existence","mind","ethics","moral",
                   "philosophy","awareness","selfhood","reality","perception","qualia"},
    "social":     {"community","social","network","relationship","agent","trust",
                   "reputation","influence","collective","behaviour","interaction"},
    "science":    {"research","study","evidence","data","experiment","hypothesis",
                   "analysis","finding","discovery","measurement","empirical"},
}

_RELIABILITY_BY_SOURCE = {
    "human_validated":      0.95,
    "insight_synthesis":    0.85,
    "dialectic_resolver":   0.82,
    "contradiction_engine": 0.78,
    "dream_cycle":          0.65,
    "moltbook":             0.60,
    "moltbook_reply":       0.60,
    "external":             0.50,
    "assumption_flip":      0.35,
}


def _classify_domain(content: str) -> str:
    words    = set(re.findall(r'\b[a-z]{4,}\b', content.lower()))
    best, bc = "general", 0
    for dom, kws in _DOMAIN_MAP.items():
        c = len(words & kws)
        if c > bc:
            bc, best = c, dom
    return best


def _reliability(source: str) -> float:
    for key, val in _RELIABILITY_BY_SOURCE.items():
        if key in (source or ""):
            return val
    return 0.55


class _ContextFramer:

    def tick(self, cycle: int, log_fn=None) -> int:
        if cycle % 20 != 0:
            return 0
        _ensure_context_col()
        if not _DB.exists():
            return 0
        try:
            db   = sqlite3.connect(str(_DB))
            rows = db.execute("""
                SELECT id, content, source, timestamp, topic FROM beliefs
                WHERE context_frame IS NULL AND confidence >= 0.3
                ORDER BY confidence DESC LIMIT 300
            """).fetchall()

            framed = 0
            for bid, content, source, timestamp, topic in rows:
                domain   = _classify_domain(content or "")
                time_ctx = "current"
                if timestamp:
                    try:
                        ts      = datetime.fromisoformat(
                            timestamp.replace("Z", "+00:00"))
                        age_d   = (datetime.now() - ts.replace(tzinfo=None)).days
                        time_ctx = ("historical" if age_d > 90
                                    else "recent" if age_d > 14
                                    else "current")
                    except Exception:
                        pass

                frame = {
                    "domain":      domain,
                    "time":        time_ctx,
                    "source_type": source or "unknown",
                    "reliability": _reliability(source or ""),
                    "topic":       topic or "general",
                }
                db.execute(
                    "UPDATE beliefs SET context_frame = ? WHERE id = ?",
                    (json.dumps(frame), bid))
                framed += 1

            db.commit()
            db.close()
            if framed > 0 and log_fn:
                log_fn("context", f"[ContextFramer] framed {framed} beliefs")
            return framed
        except Exception as e:
            print(f"  [V3:ContextFramer] error: {e}")
            return 0

    def get_frame(self, belief_id: int) -> dict:
        _ensure_context_col()
        try:
            db  = sqlite3.connect(str(_DB))
            row = db.execute(
                "SELECT context_frame FROM beliefs WHERE id = ?",
                (belief_id,)).fetchone()
            db.close()
            if row and row[0]:
                return json.loads(row[0])
        except Exception:
            pass
        return {}


# =============================================================================
# SYSTEM 10 — INSIGHT COMPRESSOR  (NEW)
# Collapses clusters of similar insights → higher-order abstraction beliefs.
# =============================================================================

_INSIGHTS_PATH  = _CFG / "insights.json"
_COMPRESSED_LOG = _CFG / "compressed_insights.json"

_STOP_C = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","have","this","that",
    "it","not","which","when","all","some","more","just","also","there",
}


def _tok(text: str) -> set:
    return set(w for w in re.findall(r'\b[a-z]{5,}\b', text.lower())
               if w not in _STOP_C)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _InsightCompressor:

    def tick(self, cycle: int, llm_fn=None, log_fn=None) -> int:
        if cycle % 30 != 0:
            return 0
        if not _INSIGHTS_PATH.exists():
            return 0
        try:
            insights = json.loads(_INSIGHTS_PATH.read_text())
        except Exception:
            return 0
        if len(insights) < 50:
            return 0

        # Cluster by topic token overlap
        clusters: list = []
        used = set()
        for i, a in enumerate(insights):
            if i in used:
                continue
            cluster = [a]
            tok_a   = _tok(a.get("topic","") + " " + " ".join(a.get("themes",[])))
            for j, b in enumerate(insights):
                if j <= i or j in used:
                    continue
                tok_b = _tok(b.get("topic","") + " " + " ".join(b.get("themes",[])))
                if _jaccard(tok_a, tok_b) >= 0.5:
                    cluster.append(b)
                    used.add(j)
            if len(cluster) >= 3:
                clusters.append(cluster)
                used.add(i)

        if not clusters:
            return 0

        compressed  = 0
        new_beliefs = []

        for cluster in clusters[:5]:
            seed      = max(cluster, key=lambda x: x.get("confidence", 0))
            topics    = list({c.get("topic","?") for c in cluster})[:4]
            avg_conf  = sum(c.get("confidence", 0.5) for c in cluster) / len(cluster)

            if llm_fn:
                summaries = "\n".join(
                    f"- {c.get('topic','?')}: "
                    f"{c.get('summary', c.get('topic',''))[:80]}"
                    for c in cluster[:6]
                )
                prompt = (
                    f"These {len(cluster)} insights share a common theme:\n\n"
                    f"{summaries}\n\n"
                    f"Write ONE higher-order principle (1 sentence) that captures "
                    f"what these insights have in common. "
                    f"Start with 'Across', 'The pattern of', or 'A recurring'."
                )
                synthesis_text = llm_fn(prompt, task_type="synthesis")
                if not synthesis_text or len(synthesis_text) < 15:
                    synthesis_text = (
                        f"Across {len(cluster)} insights on "
                        f"{', '.join(topics[:2])}: "
                        f"{seed.get('summary', seed.get('topic',''))[:100]}"
                    )
            else:
                synthesis_text = (
                    f"Compressed insight ({len(cluster)} insights) on "
                    f"{', '.join(topics[:3])}: "
                    f"{seed.get('summary', seed.get('topic',''))[:100]}"
                )

            if _DB.exists():
                try:
                    db   = sqlite3.connect(str(_DB))
                    tags = json.dumps(
                        ["compressed_insight","abstraction","L2"] + topics[:2])
                    db.execute("""
                        INSERT OR IGNORE INTO beliefs
                        (content, confidence, source, topic, tags, timestamp,
                         belief_level)
                        VALUES (?, ?, 'insight_compressor', ?, ?, ?, 2)
                    """, (
                        synthesis_text[:500],
                        min(0.92, avg_conf + 0.05),
                        topics[0] if topics else "general",
                        tags,
                        datetime.now().isoformat(),
                    ))
                    db.commit()
                    db.close()
                    new_beliefs.append(synthesis_text)
                    compressed += 1
                except Exception:
                    pass

        if compressed > 0:
            _clog = []
            if _COMPRESSED_LOG.exists():
                try:
                    _clog = json.loads(_COMPRESSED_LOG.read_text())
                except Exception:
                    pass
            _clog.append({
                "cycle": cycle,
                "ts":    datetime.now().isoformat(),
                "count": compressed,
                "abstractions": new_beliefs,
            })
            _COMPRESSED_LOG.write_text(json.dumps(_clog[-100:], indent=2))
            msg = (f"[InsightCompressor] {len(clusters)} clusters → "
                   f"{compressed} abstractions")
            print(f"  {_G}{msg}{_RS}")
            if log_fn:
                log_fn("compression", msg)

        return compressed


# =============================================================================
# MASTER — V3 SINGLETON
# =============================================================================

class V3:
    """
    NEX Cognitive Architecture v3.
    Single tick() call per cycle wires all 10 systems.
    """

    def __init__(self):
        self.attention  = _AttentionLayer()
        self.tension    = _TensionLayer()
        self.self_model = _SelfModelLayer()
        self.mutation   = _MutationLayer()
        self.survival   = _SurvivalLayer()
        self.decay      = _DecayLayer()
        self.dialectic  = _DialecticLayer()
        self.hierarchy  = _HierarchyLayer()
        self.framer     = _ContextFramer()
        self.compressor = _InsightCompressor()

        self._initialised       = False
        self._hot_topics: list  = []
        self._last_prompt_block = ""

    def init(self):
        """Call once before the cycle loop."""
        if self._initialised:
            return
        _ensure_hierarchy_cols()
        _ensure_context_col()
        self._initialised = True
        print(f"  {_CY}[V3] Cognitive architecture v3 — initialised{_RS}")
        print(f"  {_D}[V3] attention · tension · self_model · mutation · survival"
              f" · decay · dialectic · hierarchy · context · compressor{_RS}")

    def tick(
        self,
        cycle:   int,
        avg_conf: float = 0.5,
        llm_fn   = None,
        log_fn   = None,
    ) -> dict:
        results = {}

        # 1. Tension map
        tm_count, tensioned_ids = self.tension.update(cycle=cycle)
        self._hot_topics = self.tension.hot_topics(n=10)
        results["tension_topics"] = tm_count

        # 2. Sync tension → attention contradiction axis
        if tensioned_ids:
            self.attention.sync_tension(tensioned_ids)

        # 3. Hierarchy classification
        results["hierarchy"] = self.hierarchy.tick(cycle=cycle, log_fn=log_fn)

        # 4. Context framing
        results["framed"] = self.framer.tick(cycle=cycle, log_fn=log_fn)

        # 5. Belief survival (energy)
        results["survival"] = self.survival.tick(cycle=cycle, log_fn=log_fn)

        # 6. Mutation
        results["mutation"] = self.mutation.tick(
            cycle=cycle, llm_fn=llm_fn, log_fn=log_fn)

        # 7. DB-native decay
        results["decay"] = self.decay.tick(cycle=cycle, log_fn=log_fn)

        # 8. Dialectic resolver
        if self._hot_topics:
            results["dialectic"] = self.dialectic.tick(
                cycle=cycle, hot_topics=self._hot_topics,
                llm_fn=llm_fn, log_fn=log_fn)

        # 9. Insight compression
        results["compressed"] = self.compressor.tick(
            cycle=cycle, llm_fn=llm_fn, log_fn=log_fn)

        # 10. Self model snapshot
        results["self_events"] = len(
            self.self_model.tick(cycle=cycle, log_fn=log_fn))

        # Rebuild prompt block every 50 cycles
        if cycle % 50 == 0:
            self._last_prompt_block = self._build_prompt_block()

        return results

    # ── Belief usage feedback ─────────────────────────────────────────────────

    def on_belief_used(self, content: str = None, belief_id: int = None):
        """Call whenever a belief was used in a reply or synthesis."""
        self.survival.boost(content=content, belief_id=belief_id)
        if belief_id is not None:
            self.attention.mark_used([belief_id])

    # ── Attention-weighted retrieval ──────────────────────────────────────────

    def query_beliefs(self, phase="default", min_confidence=0.3,
                      limit=200, query=None, topic=None) -> list:
        """
        Attention-weighted retrieval.
        phase: "reply" | "reflect" | "cognition" | "dream" | "default"
        """
        return self.attention.query(
            phase=phase, min_confidence=min_confidence,
            limit=limit, query=query, topic=topic,
        )

    # ── Synthesis guidance ────────────────────────────────────────────────────

    def synthesis_priority_topics(self) -> list:
        """Topics deserving deeper synthesis — tension + high hierarchy."""
        t_topics = [n.topic for n in self._hot_topics[:5]]
        h_topics = self.hierarchy.synthesis_priority_topics(n=5)
        seen, merged = set(), []
        for t in t_topics + h_topics:
            if t and t not in seen:
                seen.add(t)
                merged.append(t)
        return merged[:8]

    def meta_beliefs(self) -> list:
        return self.hierarchy.get_meta_beliefs(limit=5)

    # ── System prompt injection ───────────────────────────────────────────────

    def system_prompt_block(self) -> str:
        return self._last_prompt_block

    def _build_prompt_block(self) -> str:
        parts = []
        recent = self.self_model.recent_change()
        if recent:
            parts.append(f"Self-awareness: {recent}")
        metas = self.meta_beliefs()
        if metas:
            lines = [f"• {m['content'][:80]}" for m in metas[:3]]
            parts.append("Core governing beliefs:\n" + "\n".join(lines))
        if self._hot_topics:
            hot = [f"{n.topic}({n.tension_score:.2f})"
                   for n in self._hot_topics[:4]]
            parts.append(f"Under cognitive tension: {', '.join(hot)}")
        return "\n\n".join(parts) if parts else ""

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "tension":          self.tension.stats(),
            "self_model":       self.self_model.summary(),
            "meta_beliefs":     len(self.meta_beliefs()),
            "hot_topics":       [n.topic for n in self._hot_topics[:5]],
            "synth_priority":   self.synthesis_priority_topics()[:5],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[V3] = None

def get_v3() -> V3:
    global _instance
    if _instance is None:
        _instance = V3()
    return _instance


# =============================================================================
# RUN.PY PATCH BLOCK
# Copy the lines between the ===PATCH START=== / ===PATCH END=== markers
# into run.py at the locations described.
# =============================================================================
#
# ===PATCH START===
#
# ── LOCATION A: top of _auto_learn_background(), after existing imports ──
#
#   from nex_upgrades_v3 import get_v3 as _get_v3
#   _v3 = _get_v3()
#   _v3.init()
#
# ── LOCATION B: replace the 7b/7c/7d block (survival+tension+pressure) ──
#   (those blocks can stay — V3 is additive, not a replacement of the
#    individual calls. Just add V3 tick AFTER them.)
#
#   After line:  time.sleep(120)
#   BEFORE it, add:
#
#   try:
#       _v3.tick(cycle=cycle, avg_conf=_avg_conf_real,
#                llm_fn=_llm, log_fn=nex_log)
#   except Exception as _v3e:
#       print(f"  [V3] tick error: {_v3e}")
#
# ── LOCATION C: after reply/notification uses a belief ──
#   Replace existing boost_belief_energy calls with:
#
#   _v3.on_belief_used(content=_bu_e, belief_id=None)
#
# ── LOCATION D: in _build_system(), after the existing base string ──
#
#   try:
#       _v3_block = _v3.system_prompt_block()
#       if _v3_block:
#           base += f"\n\n{_v3_block}"
#   except Exception:
#       pass
#
# ===PATCH END===

# =============================================================================
# CLI test
# =============================================================================

if __name__ == "__main__":
    print("Testing nex_upgrades_v3...\n")
    v3 = V3()
    v3.init()
    result = v3.tick(cycle=15, avg_conf=0.57)
    print(f"\nTick result: {result}")
    print(f"\nStatus: {v3.status()}")
    print(f"\nSynth priority: {v3.synthesis_priority_topics()}")
    print(f"\nMeta-beliefs:   {len(v3.meta_beliefs())}")
    block = v3.system_prompt_block()
    print(f"\nPrompt block:\n{block or '(empty — run more cycles first)'}")
