#!/usr/bin/env python3
"""
nex_active_inference.py  —  NEX Active Inference / Free Energy Minimization
════════════════════════════════════════════════════════════════════════════
Replaces passive gap detection with a predictive belief-driven loop.

Free Energy Principle (simplified for NEX):
  F  = divergence between expected world model and actual belief state
  EFE(topic) = predicted reduction in F if NEX learns about topic
  Action     = learn topic with lowest (most negative) EFE

Current system is reactive:  gap appears → queue for crawl
This system is predictive:   compute EFE for all candidates →
                              queue topics that will reduce surprise MOST
                              before they're needed

Components:
  BeliefStateModel    — live snapshot of NEX's belief distribution
  PredictionEngine    — predicts likely future queries from history + patterns
  EFECalculator       — scores each candidate topic by expected free energy
  ActionSelector      — picks top-K, feeds into CuriosityQueue
  ActiveInferenceDaemon — background thread; runs when NEX is idle

Wire-in (run.py):
    from nex_active_inference import ActiveInferenceDaemon as _AID
    _aif = _AID()
    _aif.start()
    print("  [AIF] active inference loop started")
"""

from __future__ import annotations
import json
import math
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── paths ─────────────────────────────────────────────────────────────────────
NEX_DIR  = Path.home() / "Desktop" / "nex"
DB_PATH  = NEX_DIR / "nex.db"
CFG_DIR  = Path.home() / ".config" / "nex"
AIF_STATE_PATH = CFG_DIR / "nex_aif_state.json"
CFG_DIR.mkdir(parents=True, exist_ok=True)

# ── constants ─────────────────────────────────────────────────────────────────
IDLE_THRESHOLD_S   = 300     # NEX is "idle" if no chat in last 5 min
IDLE_LOOP_INTERVAL = 1800    # run AIF loop every 30 min while idle
BUSY_LOOP_INTERVAL = 7200    # run every 2h when active
MAX_QUEUE_INJECTION = 5      # max topics to inject per AIF cycle
CANDIDATE_POOL_SIZE = 50     # topics to score per cycle
EFE_ALPHA = 0.5              # weight of epistemic value
EFE_BETA  = 0.3              # weight of pragmatic value
EFE_GAMMA = 0.2              # weight of cost / queue depth

# ── stop words ────────────────────────────────────────────────────────────────
_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","have","has","had",
    "do","does","did","will","would","could","should","may","might","this",
    "that","these","those","it","its","i","you","we","they","what","which",
    "who","how","when","where","why","not","no","so","if","then","than",
    "more","most","just","also","about","like","think","know","people",
    "general","belief","topic","response","content","system","model",
}

def _clean_topic(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower().strip())[:60]

def _topic_words(t: str) -> set:
    return {w for w in _clean_topic(t).split() if w not in _STOP and len(w) >= 3}


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — BELIEF STATE MODEL
# Snapshot of NEX's current knowledge distribution
# ══════════════════════════════════════════════════════════════════════════════

class BeliefStateModel:
    """
    NEX's generative model of her own belief state.
    Maps topic → (avg_confidence, belief_count, world_model_flag)
    Cached and refreshed every TTL seconds.
    """

    TTL = 600   # refresh every 10 min

    def __init__(self):
        self._state:      dict[str, dict] = {}
        self._wm_topics:  set[str]        = set()
        self._loaded_at:  float           = 0.0
        self._total_beliefs: int          = 0

    def _open_db(self) -> Optional[sqlite3.Connection]:
        for p in [DB_PATH, CFG_DIR / "nex.db"]:
            if p.exists():
                conn = sqlite3.connect(str(p), timeout=5)
                conn.execute("PRAGMA journal_mode=WAL")
                return conn
        return None

    def _text_col(self, conn: sqlite3.Connection) -> str:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
        return "content" if "content" in cols else ("belief" if "belief" in cols else "text")

    def refresh(self):
        conn = self._open_db()
        if not conn:
            return

        try:
            tc   = self._text_col(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
            has_tags   = "tags"   in cols
            has_source = "source" in cols
            has_topic  = "topic"  in cols

            state: dict[str, dict] = defaultdict(lambda: {
                "conf_sum": 0.0, "count": 0, "world_model": False
            })

            # Load beliefs with topic grouping
            if has_topic:
                rows = conn.execute(f"""
                    SELECT topic, AVG(confidence), COUNT(*),
                           {('MAX(CASE WHEN source LIKE ' + repr('world_model:%') + ' THEN 1 ELSE 0 END)') if has_source else '0'}
                    FROM beliefs
                    WHERE topic IS NOT NULL AND topic != ''
                    GROUP BY topic
                    HAVING COUNT(*) >= 2
                """).fetchall()
                for topic, avg_conf, cnt, is_wm in rows:
                    key = _clean_topic(topic)
                    if not key: continue
                    state[key]["conf_sum"]   = avg_conf * cnt
                    state[key]["count"]      = cnt
                    state[key]["world_model"] = bool(is_wm)
            else:
                # Fall back: extract pseudo-topics from tags
                tag_col = "tags" if has_tags else None
                if tag_col:
                    rows = conn.execute(f"""
                        SELECT {tag_col}, confidence,
                               {'source' if has_source else repr('')}
                        FROM beliefs
                        WHERE {tag_col} IS NOT NULL AND {tag_col} != ''
                        LIMIT 5000
                    """).fetchall()
                    for tags_str, conf, src in rows:
                        for tag in (tags_str or "").split(","):
                            key = _clean_topic(tag)
                            if not key or key in _STOP: continue
                            state[key]["conf_sum"]   += conf or 0.5
                            state[key]["count"]      += 1
                            if src and src.startswith("world_model:"):
                                state[key]["world_model"] = True

            # Finalise averages
            self._state = {}
            for key, d in state.items():
                if d["count"] < 2: continue
                avg = d["conf_sum"] / d["count"]
                self._state[key] = {
                    "avg_conf":    round(avg, 3),
                    "count":       d["count"],
                    "uncertainty": round(1.0 - avg, 3),
                    "world_model": d["world_model"],
                }
                if d["world_model"]:
                    self._wm_topics.add(key)

            self._total_beliefs = conn.execute(
                "SELECT COUNT(*) FROM beliefs"
            ).fetchone()[0]
            self._loaded_at = time.time()

        except Exception as e:
            print(f"  [AIF] BeliefStateModel.refresh error: {e}", flush=True)
        finally:
            conn.close()

    def ensure_fresh(self):
        if time.time() - self._loaded_at > self.TTL:
            self.refresh()

    def uncertainty(self, topic: str) -> float:
        """Return uncertainty score 0-1 for a topic (1 = totally unknown)."""
        self.ensure_fresh()
        d = self._state.get(_clean_topic(topic))
        if d is None:
            return 1.0   # unknown topic = max uncertainty
        return d["uncertainty"]

    def is_world_model(self, topic: str) -> bool:
        return _clean_topic(topic) in self._wm_topics

    def weakest_topics(self, n: int = 20) -> list[tuple[str, float]]:
        """Return topics sorted by highest uncertainty (lowest confidence)."""
        self.ensure_fresh()
        ranked = sorted(
            self._state.items(),
            key=lambda x: x[1]["uncertainty"],
            reverse=True
        )
        return [(t, d["uncertainty"]) for t, d in ranked[:n]
                if not d["world_model"]]   # world_model topics are anchors, not gaps

    def unknown_topics_from_text(self, text: str) -> list[str]:
        """Return words in text that NEX has no beliefs about."""
        self.ensure_fresh()
        words = _topic_words(text)
        return [w for w in words if w not in self._state and len(w) > 4]

    def snapshot(self) -> dict:
        return {
            "topic_count":    len(self._state),
            "total_beliefs":  self._total_beliefs,
            "wm_topics":      len(self._wm_topics),
            "weakest":        self.weakest_topics(5),
            "loaded_at":      self._loaded_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — PREDICTION ENGINE
# What topics is NEX likely to face next?
# ══════════════════════════════════════════════════════════════════════════════

class PredictionEngine:
    """
    Predicts likely future query topics based on:
      1. Recent conversation history (session_history table)
      2. Time-of-day patterns (morning = more philosophical, evening = more practical)
      3. Dominant belief topics (she'll be asked about what she knows most about)
      4. World-model gaps (topics adjacent to world_model beliefs but thin)
    """

    def __init__(self, belief_model: BeliefStateModel):
        self.bsm = belief_model

    def _open_db(self) -> Optional[sqlite3.Connection]:
        for p in [DB_PATH, CFG_DIR / "nex.db"]:
            if p.exists():
                return sqlite3.connect(str(p), timeout=5)
        return None

    def _recent_query_topics(self, n_sessions: int = 20) -> list[str]:
        """Extract topics from recent user queries."""
        topics = []
        conn = self._open_db()
        if not conn: return topics
        try:
            rows = conn.execute("""
                SELECT content FROM session_history
                WHERE role = 'user'
                ORDER BY id DESC LIMIT ?
            """, (n_sessions * 3,)).fetchall()
            conn.close()
            for row in rows:
                text = row[0] or ""
                topics.extend(_topic_words(text))
        except Exception:
            try: conn.close()
            except: pass
        return topics

    def _wm_adjacent_gaps(self) -> list[str]:
        """
        Find topics adjacent to world_model beliefs that are thin.
        These are priority gaps — they border what NEX treats as foundational.
        """
        self.bsm.ensure_fresh()
        adjacent = []
        for wm_topic in list(self.bsm._wm_topics)[:10]:
            words = _topic_words(wm_topic)
            for word in words:
                if word not in self.bsm._state:
                    adjacent.append(word)
                elif self.bsm._state[word]["uncertainty"] > 0.5:
                    adjacent.append(word)
        return adjacent

    def _time_weight(self, topic: str) -> float:
        """Slight time-of-day bias toward different topic types."""
        hour = datetime.now().hour
        philosophical = {"consciousness","mind","reality","existence","meaning",
                         "truth","knowledge","wisdom","identity","freedom"}
        practical = {"action","habit","practice","learning","skill","memory",
                     "decision","strategy","problem","solution"}
        words = _topic_words(topic)
        if 5 <= hour <= 11:    # morning → philosophical
            return 1.15 if words & philosophical else 1.0
        elif 18 <= hour <= 23: # evening → practical
            return 1.15 if words & practical else 1.0
        return 1.0

    def predict_candidates(self, pool_size: int = CANDIDATE_POOL_SIZE) -> list[tuple[str, float]]:
        """
        Return candidate topics with prior probability weights.
        Higher weight = more likely to be queried.
        """
        scored: dict[str, float] = defaultdict(float)

        # Source 1: weakest topics (high uncertainty = high surprise potential)
        for topic, unc in self.bsm.weakest_topics(20):
            scored[topic] += unc * 2.0

        # Source 2: recent query topics not yet well-covered
        for word in self._recent_query_topics():
            unc = self.bsm.uncertainty(word)
            if unc > 0.4:   # only if genuinely weak
                scored[word] += unc * 1.5

        # Source 3: world-model adjacent gaps (priority)
        for word in self._wm_adjacent_gaps():
            scored[word] += 2.5   # bonus for being adjacent to world-model

        # Apply time-of-day weight
        final = []
        for topic, base_score in scored.items():
            tw = self._time_weight(topic)
            final.append((topic, round(base_score * tw, 3)))

        final.sort(key=lambda x: -x[1])
        return final[:pool_size]


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — EFE CALCULATOR
# Expected Free Energy for each candidate action
# ══════════════════════════════════════════════════════════════════════════════

class EFECalculator:
    """
    Computes Expected Free Energy for each candidate learning action.

    EFE(topic) = -α * epistemic_value(topic)
                 -β * pragmatic_value(topic)
                 +γ * cost(topic)

    Lower EFE = better action to take.

    epistemic_value: how much will learning this reduce NEX's uncertainty?
    pragmatic_value: how often/urgently will this topic be needed?
    cost:            how expensive is this to learn (queue depth proxy)?
    """

    def __init__(self, belief_model: BeliefStateModel):
        self.bsm         = belief_model
        self._queue_depth = 0

    def _connectivity_bonus(self, topic: str) -> float:
        """
        Topics connected to many other topics have higher epistemic value —
        learning them updates more of the belief graph.
        Approximate by word overlap with existing topics.
        """
        self.bsm.ensure_fresh()
        topic_words = _topic_words(topic)
        if not topic_words: return 0.0
        connections = sum(
            1 for existing in self.bsm._state
            if len(_topic_words(existing) & topic_words) >= 1
        )
        return min(1.0, connections / 10.0)

    def _pragmatic_value(self, topic: str, prior: float) -> float:
        """
        How much does NEX 'prefer' to know this topic?
        Driven by: prior probability (from prediction) + homeostasis drives.
        """
        # Try to get homeostasis drive weights
        drive_weight = 1.0
        try:
            import sys as _s
            _s.path.insert(0, str(NEX_DIR))
            from nex_homeostasis import get_homeostasis
            hm = get_homeostasis()
            drives = hm.drives.snapshot()["levels"]
            # exploration drive → higher pragmatic value for unknown topics
            # coherence drive → higher pragmatic value for world-model-adjacent
            exploration = drives.get("exploration", 0.5)
            coherence   = drives.get("coherence", 0.5)
            unc = self.bsm.uncertainty(topic)
            if unc > 0.7:
                drive_weight = 1.0 + exploration * 0.4
            else:
                drive_weight = 1.0 + coherence * 0.2
        except Exception:
            pass

        return round(prior * drive_weight, 3)

    def compute_efe(self, topic: str, prior: float) -> float:
        """
        Compute EFE for a single topic. Lower = better action.
        Returns a float (can be negative — means high value).
        """
        uncertainty     = self.bsm.uncertainty(topic)
        connectivity    = self._connectivity_bonus(topic)
        epistemic_value = uncertainty * (1.0 + connectivity)

        pragmatic_value = self._pragmatic_value(topic, prior)

        # Cost: proportional to queue depth (don't over-queue)
        cost = min(1.0, self._queue_depth / 20.0)

        efe = (
            -EFE_ALPHA * epistemic_value
            -EFE_BETA  * pragmatic_value
            +EFE_GAMMA * cost
        )
        return round(efe, 4)

    def score_candidates(
        self,
        candidates: list[tuple[str, float]],
        queue_depth: int = 0,
    ) -> list[tuple[str, float]]:
        """
        Score all candidates by EFE.
        Returns list of (topic, efe) sorted ascending (lowest EFE first = best).
        """
        self._queue_depth = queue_depth
        scored = []
        for topic, prior in candidates:
            efe = self.compute_efe(topic, prior)
            scored.append((topic, efe))
        scored.sort(key=lambda x: x[1])   # ascending: lowest EFE = best
        return scored


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — ACTION SELECTOR
# Picks top-K actions, feeds into CuriosityQueue
# ══════════════════════════════════════════════════════════════════════════════

class ActionSelector:
    """
    Selects the best learning actions from the EFE-ranked list
    and injects them into the CuriosityQueue with appropriate priority.
    """

    def __init__(self, belief_model: BeliefStateModel):
        self.bsm = belief_model

    def _get_queue(self):
        """Lazy import CuriosityQueue to avoid circular imports."""
        try:
            import sys as _s
            _s.path.insert(0, str(NEX_DIR / "nex"))
            _s.path.insert(0, str(NEX_DIR))
            from nex_curiosity import CuriosityQueue
            return CuriosityQueue()
        except Exception as e:
            print(f"  [AIF] CuriosityQueue unavailable: {e}", flush=True)
            return None

    def _queue_depth(self, queue) -> int:
        try:
            return queue.status()["pending"]
        except Exception:
            return 0

    def select_and_inject(
        self,
        ranked: list[tuple[str, float]],
        max_inject: int = MAX_QUEUE_INJECTION,
    ) -> list[str]:
        """
        Inject top-ranked topics into CuriosityQueue.
        Returns list of topics successfully queued.
        """
        queue = self._get_queue()
        if queue is None:
            return []

        queued = []
        for topic, efe in ranked[:max_inject * 3]:   # try more than needed
            if len(queued) >= max_inject:
                break

            # Don't queue world_model topics (they're anchors, not gaps)
            if self.bsm.is_world_model(topic):
                continue

            # Map EFE to priority
            if efe < -0.6:   priority_reason = "aif_urgent"
            elif efe < -0.3: priority_reason = "aif_high"
            else:            priority_reason = "aif_normal"

            try:
                added = queue.enqueue(
                    topic=topic,
                    reason=priority_reason,
                    confidence=round(1.0 - self.bsm.uncertainty(topic), 2),
                )
                if added:
                    queued.append(topic)
            except Exception as e:
                print(f"  [AIF] enqueue error for '{topic}': {e}", flush=True)

        return queued


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 5 — ACTIVE INFERENCE ENGINE
# Orchestrates all layers, persists state
# ══════════════════════════════════════════════════════════════════════════════

class ActiveInferenceEngine:
    """
    Main AIF orchestrator. Runs one complete FE-minimization cycle:
      predict → score → select → inject → log
    """

    def __init__(self):
        self.bsm      = BeliefStateModel()
        self.predict  = PredictionEngine(self.bsm)
        self.efe_calc = EFECalculator(self.bsm)
        self.selector = ActionSelector(self.bsm)
        self._cycle   = 0

    def run_cycle(self) -> dict:
        """
        Execute one AIF cycle. Returns report dict.
        """
        self._cycle += 1
        t0 = time.time()

        # Refresh belief state
        self.bsm.refresh()
        snap = self.bsm.snapshot()

        # Predict candidates
        candidates = self.predict.predict_candidates(CANDIDATE_POOL_SIZE)
        if not candidates:
            return {"cycle": self._cycle, "status": "no_candidates",
                    "elapsed": 0.0}

        # Score by EFE
        # Get current queue depth for cost calculation
        queue_depth = 0
        try:
            q = self.selector._get_queue()
            if q: queue_depth = self._queue_depth_from_queue(q)
        except Exception:
            pass

        ranked = self.efe_calc.score_candidates(candidates, queue_depth)

        # Select and inject best actions
        injected = self.selector.select_and_inject(ranked, MAX_QUEUE_INJECTION)

        elapsed = round(time.time() - t0, 2)

        report = {
            "cycle":          self._cycle,
            "timestamp":      datetime.now().isoformat(),
            "belief_state":   snap,
            "candidates_scored": len(ranked),
            "top_efe":        ranked[:5] if ranked else [],
            "injected":       injected,
            "elapsed_s":      elapsed,
        }

        # Persist state
        self._save_state(report)

        print(f"  [AIF] cycle={self._cycle}  "
              f"candidates={len(candidates)}  "
              f"injected={injected}  "
              f"elapsed={elapsed}s", flush=True)

        return report

    def _queue_depth_from_queue(self, queue) -> int:
        try: return queue.status()["pending"]
        except: return 0

    def _save_state(self, report: dict):
        try:
            history = []
            if AIF_STATE_PATH.exists():
                try:
                    history = json.loads(AIF_STATE_PATH.read_text())
                except Exception:
                    pass
            history.append(report)
            history = history[-50:]   # keep last 50 cycles
            AIF_STATE_PATH.write_text(json.dumps(history, indent=2, default=str))
        except Exception:
            pass

    def free_energy(self) -> float:
        """
        Compute current free energy of the belief state.
        F = mean uncertainty across all topics (weighted by count).
        Lower = better (less surprise expected).
        """
        self.bsm.ensure_fresh()
        if not self.bsm._state:
            return 1.0
        weighted_sum = sum(
            d["uncertainty"] * math.log(1 + d["count"])
            for d in self.bsm._state.values()
        )
        weight_total = sum(
            math.log(1 + d["count"])
            for d in self.bsm._state.values()
        )
        return round(weighted_sum / max(weight_total, 1), 4)

    def status(self) -> dict:
        return {
            "cycle":        self._cycle,
            "free_energy":  self.free_energy(),
            "belief_state": self.bsm.snapshot(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 6 — DAEMON
# Background thread: runs AIF when idle, slower when busy
# ══════════════════════════════════════════════════════════════════════════════

def _last_chat_age_s() -> float:
    """Return seconds since last user chat message."""
    for db_p in [DB_PATH, CFG_DIR / "nex.db"]:
        if not db_p.exists(): continue
        try:
            conn = sqlite3.connect(str(db_p), timeout=3)
            row  = conn.execute("""
                SELECT MAX(id) FROM session_history WHERE role='user'
            """).fetchone()
            conn.close()
            if row and row[0]:
                # Use rowid as rough proxy for recency
                return 0.0   # can't compute exact time without ts column easily
        except Exception:
            pass
    # Fallback: check session_state.json
    try:
        ss = json.loads((CFG_DIR / "session_state.json").read_text())
        last = ss.get("last_chat_time", 0)
        if last: return time.time() - last
    except Exception:
        pass
    return 9999.0   # assume idle if unknown


class ActiveInferenceDaemon:
    """
    Background daemon. Runs AIF cycles on schedule.
    Faster when NEX is idle, slower when active.

    Wire-in (run.py):
        from nex_active_inference import ActiveInferenceDaemon as _AID
        _aif = _AID()
        _aif.start()
    """

    def __init__(self):
        self.engine  = ActiveInferenceEngine()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="nex-aif"
        )
        self._stop   = threading.Event()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        # Initial delay — let everything else start up first
        self._stop.wait(180)

        while not self._stop.is_set():
            try:
                idle_s   = _last_chat_age_s()
                is_idle  = idle_s > IDLE_THRESHOLD_S
                interval = IDLE_LOOP_INTERVAL if is_idle else BUSY_LOOP_INTERVAL

                report = self.engine.run_cycle()

                fe = self.engine.free_energy()
                print(
                    f"  [AIF] free_energy={fe:.4f}  "
                    f"mode={'idle' if is_idle else 'active'}  "
                    f"next_in={interval//60}min",
                    flush=True
                )

            except Exception as e:
                print(f"  [AIF] loop error: {e}", flush=True)
                interval = BUSY_LOOP_INTERVAL

            self._stop.wait(interval)

    def status(self) -> dict:
        return self.engine.status()


# ── ALSO: enhanced CuriosityEngine drop-in ────────────────────────────────────
def enhance_curiosity_engine(curiosity_engine):
    """
    Monkey-patches an existing CuriosityEngine instance to use AIF
    for its check_beliefs() call instead of the passive low-conf scan.

    Usage in run.py after curiosity is initialised:
        from nex_active_inference import enhance_curiosity_engine
        enhance_curiosity_engine(curiosity)
    """
    engine = ActiveInferenceEngine()

    original_check = curiosity_engine.check_beliefs

    def aif_check_beliefs(belief_store) -> int:
        """Run AIF cycle AND original passive check — best of both."""
        # AIF cycle
        try:
            report   = engine.run_cycle()
            injected = len(report.get("injected", []))
        except Exception:
            injected = 0

        # Also run original passive scan as safety net
        try:
            passive = original_check(belief_store)
        except Exception:
            passive = 0

        return injected + passive

    original_desire = curiosity_engine.generate_desires

    def aif_generate_desires(cycle_num: int) -> int:
        """Replace desire generation with EFE-ranked topics."""
        try:
            engine.bsm.refresh()
            candidates = engine.predict.predict_candidates(20)
            ranked     = engine.efe_calc.score_candidates(candidates)
            injected   = engine.selector.select_and_inject(ranked, 3)
            return len(injected)
        except Exception:
            return original_desire(cycle_num)

    curiosity_engine.check_beliefs    = aif_check_beliefs
    curiosity_engine.generate_desires = aif_generate_desires
    curiosity_engine._aif_engine      = engine
    print("  [AIF] CuriosityEngine enhanced with active inference", flush=True)
    return curiosity_engine


# ── standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEX Active Inference")
    parser.add_argument("--status",    action="store_true")
    parser.add_argument("--cycle",     action="store_true")
    parser.add_argument("--free-energy", action="store_true")
    args = parser.parse_args()

    engine = ActiveInferenceEngine()

    if args.status:
        print(json.dumps(engine.status(), indent=2, default=str))
    elif args.free_energy:
        fe = engine.free_energy()
        print(f"Current free energy: {fe:.4f}  (0=perfect, 1=maximum surprise)")
    else:
        print("Running one AIF cycle...")
        report = engine.run_cycle()
        print(json.dumps(report, indent=2, default=str))
