"""
nex_throw_net.py — The Throw-Net Engine
════════════════════════════════════════
Nex's autonomous self-improvement methodology.
Not a new AI system — a conductor over what she already has.

Methodology (A→D):
  A — Time Fetch:    source router sweeps past/present/pending
  B — Neti-Neti:     reasoner eliminates what conflicts with identity
  C — Logic Distill: NBRE works knowns vs unknowns, solution precipitates
  D — Refinement:    auto-validate candidates against actual architecture

Trigger modes:
  1. Autonomous — needs_llm=True on 5+ consecutive queries same topic
  2. Scheduled  — MetabolismDaemon slow cycle, nightly
  3. Manual     — Telegram /thrownet "constraint description"

Deploy:
  cp nex_throw_net.py ~/Desktop/nex/nex/
  python3 ~/Desktop/nex/nex/nex_throw_net.py --install
  Then add to MetabolismDaemon slow cycle and Telegram handler.
"""

import os
import sys
import json
import math
import time
import sqlite3
import logging
import argparse
import threading
import traceback
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Optional

# ── Path setup ───────────────────────────────────────────────────────────────
_NEX_ROOT = os.path.expanduser("~/Desktop/nex")
_NEX_PKG  = os.path.join(_NEX_ROOT, "nex")
_DB_PATH  = os.path.join(_NEX_ROOT, "nex.db")

for _p in [_NEX_ROOT, _NEX_PKG]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

log = logging.getLogger("throw_net")
logging.basicConfig(
    level=logging.INFO,
    format="[throw_net] %(message)s"
)

# ═══════════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════════

SCHEMA = """
CREATE TABLE IF NOT EXISTS throw_net_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_ts      TEXT    NOT NULL,
    constraint_text TEXT    NOT NULL,
    trigger_mode    TEXT    NOT NULL DEFAULT 'manual',
    trigger_topic   TEXT,
    status          TEXT    NOT NULL DEFAULT 'running',
    fetch_results   TEXT,
    candidates_raw  TEXT,
    candidates_refined TEXT,
    top_candidate   TEXT,
    surfaced        INTEGER DEFAULT 0,
    approved        INTEGER DEFAULT 0,
    outcome_notes   TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS throw_net_triggers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT    NOT NULL,
    llm_misses  INTEGER DEFAULT 1,
    last_seen   TEXT    DEFAULT (datetime('now')),
    fired       INTEGER DEFAULT 0
);
"""

def install_schema(db_path: str = _DB_PATH) -> bool:
    try:
        con = sqlite3.connect(db_path)
        con.executescript(SCHEMA)
        con.commit()
        con.close()
        log.info("Schema installed: throw_net_sessions, throw_net_triggers")
        return True
    except Exception as e:
        log.error(f"Schema install failed: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════
# TRIGGER DETECTOR
# Watches NBRE shadow output for constraint signals
# ═══════════════════════════════════════════════════════════════════

class TriggerDetector:
    """
    Monitors the NBRE needs_llm signal per topic.
    When a topic accumulates 5+ LLM misses → fires Throw-Net.
    """
    MISS_THRESHOLD = 4

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path

    # Topics too short or generic to warrant ThrowNet sessions
    _TOPIC_STOP = {
        "general","building","music","ghost","world","hidden","culture",
        "science","history","nature","art","society","what","how","why",
        "the","and","for","with","from","that","this","have","not",
    }

    def record_miss(self, topic: str) -> bool:
        """Record one needs_llm=True for a topic. Returns True if threshold crossed."""
        # Quality gate — don't fire ThrowNet on generic or short topics
        if not topic or len(topic) < 5 or topic.lower() in self._TOPIC_STOP:
            return False
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute("""
                INSERT INTO throw_net_triggers (topic, llm_misses, last_seen)
                VALUES (?, 1, datetime('now'))
                ON CONFLICT(topic) DO UPDATE SET
                    llm_misses = llm_misses + 1,
                    last_seen  = datetime('now')
            """, (topic,))
            con.commit()
            cur.execute("""
                SELECT llm_misses, fired FROM throw_net_triggers WHERE topic = ?
            """, (topic,))
            row = cur.fetchone()
            con.close()
            if row:
                misses, fired = row
                if misses >= self.MISS_THRESHOLD and not fired:
                    return True
            return False
        except Exception as e:
            log.error(f"record_miss error: {e}")
            return False

    def mark_fired(self, topic: str):
        try:
            con = sqlite3.connect(self.db_path)
            con.execute("""
                UPDATE throw_net_triggers SET fired = 1 WHERE topic = ?
            """, (topic,))
            con.commit()
            con.close()
        except Exception as e:
            log.error(f"mark_fired error: {e}")

    def reset_topic(self, topic: str):
        """Call after a successful Throw-Net session to allow future triggers."""
        try:
            con = sqlite3.connect(self.db_path)
            con.execute("""
                UPDATE throw_net_triggers
                SET llm_misses = 0, fired = 0, last_seen = datetime('now')
                WHERE topic = ?
            """, (topic,))
            con.commit()
            con.close()
        except Exception as e:
            log.error(f"reset_topic error: {e}")

    def pending_triggers(self) -> list:
        """Return topics that have crossed threshold but not yet been processed."""
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute("""
                SELECT topic, llm_misses FROM throw_net_triggers
                WHERE llm_misses >= ? AND fired = 0
                ORDER BY llm_misses DESC
            """, (self.MISS_THRESHOLD,))
            rows = cur.fetchall()
            con.close()
            return [{'topic': r[0], 'misses': r[1]} for r in rows]
        except Exception as e:
            log.error(f"pending_triggers error: {e}")
            return []

# ═══════════════════════════════════════════════════════════════════
# TOOL A — TIME FETCH
# Uses Nex's source router to sweep for resonance
# ═══════════════════════════════════════════════════════════════════

class TimeFetch:
    """
    Sweeps past (known research), present (belief DB), pending (source router).
    Returns resonant findings tagged to the constraint.
    """

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path

    def fetch_from_belief_db(self, constraint: str, limit: int = 20) -> list:
        """
        Present sweep — what does Nex already know that touches this constraint?
        Uses FAISS-style keyword match against belief content.
        """
        try:
            keywords = [w.lower() for w in constraint.split()
                        if len(w) > 3 and w.lower() not in {
                            'what', 'that', 'this', 'with', 'from',
                            'cannot', 'does', 'have', 'about'
                        }]
            if not keywords:
                return []
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            placeholders = ' OR '.join(
                ['LOWER(content) LIKE ?'] * len(keywords)
            )
            params = [f'%{k}%' for k in keywords]
            cur.execute(f"""
                SELECT content, topic, confidence, source
                FROM beliefs
                WHERE ({placeholders})
                  AND confidence > 0.4
                  AND LENGTH(content) > 30
                ORDER BY confidence DESC, reinforce_count DESC
                LIMIT ?
            """, params + [limit])
            rows = cur.fetchall()
            con.close()
            return [
                {'content': r[0], 'topic': r[1],
                 'confidence': r[2], 'source': r[3],
                 'origin': 'belief_db'}
                for r in rows
            ]
        except Exception as e:
            log.error(f"fetch_from_belief_db error: {e}")
            return []

    def fetch_from_source_router(self, constraint: str) -> list:
        """
        Past + pending sweep — source router crawls for external resonance.
        Falls back gracefully if source router unavailable.
        """
        results = []
        try:
            # SourceRouter is a daemon (start/status/stop) not a query interface.
            # Instead: do a broader keyword sweep across nex_posts (procedural
            # memory) and recent episodic events as the "pending" sweep.
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            keywords = [w.lower() for w in constraint.split() if len(w) > 4][:5]
            if keywords:
                placeholders = ' OR '.join(['LOWER(content) LIKE ?'] * len(keywords))
                params = [f'%{k}%' for k in keywords]
                # Sweep nex_posts for past successful responses
                try:
                    cur.execute(f"""
                        SELECT content, topic, quality
                        FROM nex_posts
                        WHERE ({placeholders})
                          AND quality > 0.5
                        ORDER BY quality DESC LIMIT 5
                    """, params)
                    for r in cur.fetchall():
                        results.append({
                            'content': (r[0] or '')[:300],
                            'topic': r[1] or 'procedural',
                            'confidence': float(r[2] or 0.6),
                            'source': 'nex_posts',
                            'origin': 'source_router'
                        })
                except Exception:
                    pass
                # Sweep episodic_events if available
                try:
                    cur.execute(f"""
                        SELECT content, topic, importance
                        FROM episodic_events
                        WHERE ({placeholders})
                        ORDER BY importance DESC LIMIT 5
                    """, params)
                    for r in cur.fetchall():
                        results.append({
                            'content': (r[0] or '')[:300],
                            'topic': r[1] or 'episodic',
                            'confidence': float(r[2] or 0.5),
                            'source': 'episodic_events',
                            'origin': 'source_router'
                        })
                except Exception:
                    pass
            con.close()
        except Exception as e:
            log.error(f"source_router sweep error: {e}")
        return results

    def fetch_from_gaps(self, constraint: str) -> list:
        """
        What has Nex already flagged as unknown that overlaps with this constraint?
        """
        try:
            keywords = [w.lower() for w in constraint.split() if len(w) > 3]
            if not keywords:
                return []
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            placeholders = ' OR '.join(['LOWER(term) LIKE ?'] * len(keywords))
            params = [f'%{k}%' for k in keywords]
            cur.execute(f"""
                SELECT term, frequency, context
                FROM gaps
                WHERE ({placeholders})
                  AND (drained IS NULL OR drained = 0)
                ORDER BY frequency DESC
                LIMIT 10
            """, params)
            rows = cur.fetchall()
            con.close()
            return [
                {'content': f"Known gap: {r[0]} (seen {r[1]} times). Context: {(r[2] or '')[:80]}",
                 'topic': 'gap_feeder',
                 'confidence': 0.5,
                 'source': 'gap_feeder',
                 'origin': 'gap_feeder'}
                for r in rows
            ]
        except Exception as e:
            log.error(f"fetch_from_gaps error: {e}")
            return []

    def run(self, constraint: str) -> list:
        """Full Time Fetch — all three sweeps combined."""
        log.info(f"Time Fetch: [{constraint[:60]}]")
        results = []
        results.extend(self.fetch_from_belief_db(constraint))
        results.extend(self.fetch_from_source_router(constraint))
        results.extend(self.fetch_from_gaps(constraint))
        log.info(f"Time Fetch complete: {len(results)} items found")
        return results

# ═══════════════════════════════════════════════════════════════════
# TOOL B/C — NBRE DISTILL
# Fires the reservoir against fetch results + existing beliefs
# This IS Logic Distill: knowns (beliefs) vs unknowns (fetch results)
# worked by the reservoir. Neti-Neti happens through tension detection.
# ═══════════════════════════════════════════════════════════════════

class NBREDistill:
    """
    Seeds fetch results as temporary neurons.
    Fires NBRE against them.
    Tensions between existing beliefs and new fetch = Neti-Neti output.
    High-confidence fired neurons = candidate solutions.
    """

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path

    def _load_nbre(self):
        try:
            sys.path.insert(0, _NEX_ROOT)
            from nex_belief_reservoir_engine import NexBeliefReservoirEngine
            engine = NexBeliefReservoirEngine()
            engine.load()
            return engine
        except Exception as e:
            log.error(f"NBRE load error: {e}")
            return None

    def _extract_topics(self, constraint: str, fetch_results: list) -> list:
        """Extract topic keywords from constraint and fetch results."""
        words = set(constraint.lower().split())
        for item in fetch_results[:5]:
            topic = item.get('topic', '')
            if topic and topic != 'external':
                words.add(topic)
        # Clean stopwords
        stopwords = {'what', 'that', 'this', 'with', 'from', 'cannot',
                     'does', 'have', 'about', 'when', 'where', 'which'}
        topics = [w for w in words if len(w) > 3 and w not in stopwords]
        return topics[:8]

    def run(self, constraint: str, fetch_results: list) -> dict:
        """
        Run NBRE distill pass.
        Returns: candidates, tensions, confidence.
        """
        log.info("NBRE Distill: firing reservoir against constraint")
        engine = self._load_nbre()
        if not engine:
            return {
                'candidates': [], 'tensions': [],
                'confidence': 0.0, 'fired': 0
            }

        topics = self._extract_topics(constraint, fetch_results)

        try:
            result = engine.process(constraint, topics)
            candidates = []
            for n in result.get('supporting_beliefs', []):
                if not n or not getattr(n, 'content', None):
                    continue
                candidates.append({
                    'content':    n.content,
                    'topic':      getattr(n, 'topic', 'general'),
                    'confidence': getattr(n, 'confidence', 0.5),
                    'source':     'nbre_fired'
                })

            log.info(
                f"NBRE Distill: fired={result.get('n_fired', 0)} "
                f"tensions={len(result.get('tensions', []))} "
                f"conf={result.get('confidence', 0):.2f}"
            )
            return {
                'candidates': candidates,
                'tensions':   result.get('tensions', []),
                'confidence': result.get('confidence', 0.0),
                'fired':      result.get('n_fired', 0),
                'position':   result.get('position', '')
            }
        except Exception as e:
            log.error(f"NBRE distill error: {e}")
            return {'candidates': [], 'tensions': [], 'confidence': 0.0, 'fired': 0}

# ═══════════════════════════════════════════════════════════════════
# TOOL D — REFINEMENT ENGINE
# Auto-validates candidates against Nex's actual architecture
# ═══════════════════════════════════════════════════════════════════

class RefinementEngine:
    """
    Six questions derived from Nex's actual architecture.
    Each candidate scored 0-6. Below 3 = rejected.
    """
    PASS_THRESHOLD = 3

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path

    def _r1_wires_to_existing(self, candidate: dict) -> bool:
        """R1: Does this connect to something that actually exists and runs?"""
        try:
            content = candidate.get('content', '').lower()
            keywords = [w for w in content.split()
                        if len(w) > 4][:6]
            if not keywords:
                return False
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            placeholders = ' OR '.join(['LOWER(content) LIKE ?'] * len(keywords))
            params = [f'%{k}%' for k in keywords]
            cur.execute(f"""
                SELECT COUNT(*) FROM beliefs
                WHERE ({placeholders}) AND confidence > 0.5
            """, params)
            count = cur.fetchone()[0]
            con.close()
            return count >= 2
        except Exception as e:
            log.error(f"R1 error: {e}")
            return False

    def _r2_uses_belief_links(self, candidate: dict) -> bool:
        """R2: Does this topic have belief_links connections?"""
        try:
            topic = candidate.get('topic', '')
            if not topic:
                return False
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM belief_links bl
                JOIN beliefs b ON bl.parent_id = b.id
                WHERE LOWER(b.topic) LIKE ?
            """, (f'%{topic.lower()[:20]}%',))
            count = cur.fetchone()[0]
            con.close()
            return count > 0
        except Exception as e:
            log.error(f"R2 error: {e}")
            return True  # Default pass — don't block on DB errors

    def _r3_safe_for_live_service(self, candidate: dict) -> bool:
        """R3: Is this safe — doesn't risk breaking Telegram or brain service?"""
        content = candidate.get('content', '').lower()
        # Flag anything that sounds like it touches live service paths
        risky_patterns = [
            'delete all', 'drop table', 'truncate', 'restart service',
            'kill process', 'format ', 'rm -rf', 'overwrite soul loop'
        ]
        return not any(p in content for p in risky_patterns)

    def _r4_schema_change_safe(self, candidate: dict) -> bool:
        """R4: If schema change needed, is it safe (ADD not ALTER/DROP)?"""
        content = candidate.get('content', '').lower()
        # Most belief-level candidates don't need schema changes
        # Flag only explicit destructive schema changes
        unsafe = ['drop column', 'alter column', 'drop table', 'truncate table']
        return not any(p in content for p in unsafe)

    def _r5_right_size(self, candidate: dict) -> bool:
        """R5: Is this one coherent thing, not three disguised as one?"""
        content = candidate.get('content', '')
        # Rough heuristic: if content contains multiple 'and also' / 'plus' /
        # 'additionally' it's probably multiple things
        oversized_signals = [
            ' and also ', ' plus ', ' additionally ', ' furthermore ',
            ' moreover ', ' on top of that '
        ]
        signal_count = sum(1 for s in oversized_signals if s in content.lower())
        word_count = len(content.split())
        # Over 80 words and 2+ compound signals = likely oversized
        if word_count > 80 and signal_count >= 2:
            return False
        return True

    def _r6_graceful_degradation(self, candidate: dict) -> bool:
        """R6: Can this be implemented with try/except fallback?"""
        # Almost everything can be wrapped — only flag hardcoded failures
        content = candidate.get('content', '').lower()
        blocking = ['must succeed', 'cannot fail', 'required to work',
                    'no fallback', 'will always']
        return not any(b in content for b in blocking)

    def score(self, candidate: dict) -> dict:
        """Score a single candidate against all 6 questions."""
        checks = [
            ('R1_wires_to_existing',    self._r1_wires_to_existing(candidate)),
            ('R2_uses_belief_links',    self._r2_uses_belief_links(candidate)),
            ('R3_safe_for_live',        self._r3_safe_for_live_service(candidate)),
            ('R4_schema_safe',          self._r4_schema_change_safe(candidate)),
            ('R5_right_size',           self._r5_right_size(candidate)),
            ('R6_graceful_degradation', self._r6_graceful_degradation(candidate)),
        ]
        score = sum(1 for _, passed in checks if passed)
        return {
            'candidate':  candidate,
            'score':      score,
            'max_score':  6,
            'checks':     dict(checks),
            'buildable':  score >= self.PASS_THRESHOLD,
        }

    def run(self, candidates: list) -> list:
        """Score and filter all candidates. Return sorted by score."""
        log.info(f"Refinement: evaluating {len(candidates)} candidates")
        scored = [self.score(c) for c in candidates]
        scored.sort(key=lambda x: x['score'], reverse=True)
        buildable = [s for s in scored if s['buildable']]
        log.info(
            f"Refinement complete: {len(buildable)}/{len(scored)} passed"
        )
        return scored

# ═══════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR — ThrowNetEngine
# ═══════════════════════════════════════════════════════════════════

class ThrowNetEngine:
    """
    Runs the full four-tool Throw-Net methodology.
    Conductor over Nex's existing components.
    """

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path     = db_path
        self.trigger     = TriggerDetector(db_path)
        self.time_fetch  = TimeFetch(db_path)
        self.nbre_distil = NBREDistill(db_path)
        self.refinement  = RefinementEngine(db_path)

    def _save_session(self, session: dict) -> int:
        """Persist session to DB. Returns session ID."""
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute("""
                INSERT INTO throw_net_sessions
                    (session_ts, constraint_text, trigger_mode,
                     trigger_topic, status,
                     fetch_results, candidates_raw,
                     candidates_refined, top_candidate)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                datetime.now().isoformat(),
                session.get('constraint', ''),
                session.get('trigger_mode', 'manual'),
                session.get('trigger_topic', ''),
                session.get('status', 'complete'),
                json.dumps(session.get('fetch_results', [])[:5]),
                json.dumps(session.get('candidates_raw', [])[:10]),
                json.dumps(session.get('candidates_refined', [])[:5]),
                json.dumps(session.get('top_candidate', {})),
            ))
            session_id = cur.lastrowid
            con.commit()
            con.close()
            return session_id
        except Exception as e:
            log.error(f"save_session error: {e}")
            return -1

    def _format_surface_message(self, session: dict) -> str:
        """Format result for Telegram surfacing."""
        top = session.get('top_candidate', {})
        candidate = top.get('candidate', {})
        score = top.get('score', 0)
        content = candidate.get('content', '')[:200]
        topic = candidate.get('topic', 'unknown')
        constraint = session.get('constraint', '')[:80]

        tensions = session.get('tensions', [])
        tension_note = ''
        if tensions:
            tension_note = f"\nTension detected: {tensions[0][:80]}"

        return (
            f"🧠 Throw-Net complete\n"
            f"Constraint: {constraint}\n"
            f"Top candidate [{topic}] score={score}/6:\n"
            f"{content}"
            f"{tension_note}\n"
            f"Approve with /approve_tn <session_id>"
        )

    def run(self,
            constraint: str,
            trigger_mode: str = 'manual',
            trigger_topic: str = '') -> dict:
        """
        Full Throw-Net run. Returns session dict with results.

        Steps:
          1. Time Fetch — sweep all three sources
          2. NBRE Distill — fire reservoir, Logic Distill + Neti-Neti
          3. Combine and deduplicate candidates
          4. Refinement Engine — score and filter
          5. Persist and surface
        """
        log.info(f"=== Throw-Net START: [{constraint[:60]}] mode={trigger_mode}")
        session = {
            'constraint':    constraint,
            'trigger_mode':  trigger_mode,
            'trigger_topic': trigger_topic,
            'status':        'running',
            'started_at':    datetime.now().isoformat(),
        }

        # ── Step 1: Time Fetch ─────────────────────────────────────
        try:
            fetch_results = self.time_fetch.run(constraint)
            session['fetch_results'] = fetch_results
            log.info(f"Step 1 complete: {len(fetch_results)} fetch results")
        except Exception as e:
            log.error(f"Step 1 Time Fetch failed: {e}")
            fetch_results = []
            session['fetch_results'] = []

        # ── Step 2: NBRE Distill ───────────────────────────────────
        try:
            distill = self.nbre_distil.run(constraint, fetch_results)
            session['tensions']   = distill.get('tensions', [])
            session['nbre_fired'] = distill.get('fired', 0)
            session['nbre_conf']  = distill.get('confidence', 0.0)
            nbre_candidates = distill.get('candidates', [])
            log.info(f"Step 2 complete: {len(nbre_candidates)} NBRE candidates")
        except Exception as e:
            log.error(f"Step 2 NBRE Distill failed: {e}")
            nbre_candidates = []
            session['tensions'] = []

        # ── Step 3: Combine candidates ─────────────────────────────
        try:
            # NBRE candidates first (already scored by reservoir)
            # Then fetch results as lower-confidence candidates
            all_candidates = list(nbre_candidates)
            for item in fetch_results:
                if item.get('origin') == 'belief_db':
                    continue  # Already in NBRE candidates
                all_candidates.append(item)

            # Deduplicate by content similarity (simple word overlap)
            deduped = []
            seen_words = []
            for c in all_candidates:
                words = set(c.get('content', '').lower().split())
                is_dupe = any(
                    len(words & sw) / max(len(words), 1) > 0.7
                    for sw in seen_words
                )
                if not is_dupe:
                    deduped.append(c)
                    seen_words.append(words)

            session['candidates_raw'] = deduped
            log.info(f"Step 3 complete: {len(deduped)} deduplicated candidates")
        except Exception as e:
            log.error(f"Step 3 combine failed: {e}")
            deduped = nbre_candidates
            session['candidates_raw'] = deduped

        # ── Step 4: Refinement Engine ──────────────────────────────
        try:
            if deduped:
                refined = self.refinement.run(deduped)
                buildable = [r for r in refined if r['buildable']]
                session['candidates_refined'] = refined
                session['top_candidate'] = refined[0] if refined else {}
                log.info(
                    f"Step 4 complete: {len(buildable)} buildable candidates"
                )
            else:
                session['candidates_refined'] = []
                session['top_candidate'] = {}
                log.info("Step 4: no candidates to refine")
        except Exception as e:
            log.error(f"Step 4 Refinement failed: {e}")
            session['candidates_refined'] = []
            session['top_candidate'] = {}

        # ── Step 5: Persist ────────────────────────────────────────
        try:
            session['status'] = 'complete'
            session_id = self._save_session(session)
            session['session_id'] = session_id
            log.info(f"Session saved: id={session_id}")
        except Exception as e:
            log.error(f"Step 5 persist failed: {e}")
            session['session_id'] = -1

        # ── Step 6: Surface message ────────────────────────────────
        try:
            if session.get('top_candidate'):
                surface_msg = self._format_surface_message(session)
                session['surface_message'] = surface_msg
                log.info(f"Surface message ready")
            else:
                session['surface_message'] = (
                    f"Throw-Net complete — no strong candidates found for: "
                    f"{constraint[:60]}"
                )
        except Exception as e:
            log.error(f"Step 6 surface failed: {e}")
            session['surface_message'] = "Throw-Net complete."

        log.info(f"=== Throw-Net DONE: session_id={session.get('session_id')}")
        return session

# ═══════════════════════════════════════════════════════════════════
# AUTONOMOUS MONITOR — hooks into NBRE shadow output
# ═══════════════════════════════════════════════════════════════════

class ThrowNetMonitor:
    """
    Watches for autonomous trigger conditions.
    Runs as a background thread alongside the soul loop.
    Call record_nbre_result() from the NBRE shadow block in soul_loop.
    """

    def __init__(self, db_path: str = _DB_PATH):
        self.engine  = ThrowNetEngine(db_path)
        self.trigger = TriggerDetector(db_path)
        self._lock   = threading.Lock()

    def record_nbre_result(self, topic: str, needs_llm: bool, query: str = ''):
        """
        Call this from soul loop NBRE shadow block on every query.
        If needs_llm=True, records a miss for the topic.
        Fires Throw-Net in background if threshold crossed.
        """
        if not needs_llm:
            return
        try:
            with self._lock:
                should_fire = self.trigger.record_miss(topic)
            if should_fire:
                constraint = (
                    f"Nex cannot resolve queries about '{topic}' "
                    f"without LLM assistance. Last query: {query[:80]}"
                )
                log.info(f"Autonomous trigger: topic={topic}")
                self.trigger.mark_fired(topic)
                t = threading.Thread(
                    target=self._run_background,
                    args=(constraint, topic),
                    daemon=True
                )
                t.start()
        except Exception as e:
            log.error(f"record_nbre_result error: {e}")

    def _run_background(self, constraint: str, topic: str):
        """Background thread — run Throw-Net without blocking soul loop."""
        try:
            session = self.engine.run(
                constraint,
                trigger_mode='autonomous',
                trigger_topic=topic
            )
            # Surface to Telegram if possible
            msg = session.get('surface_message', '')
            if msg:
                self._surface_to_telegram(msg)
        except Exception as e:
            log.error(f"background throw-net error: {e}\n{traceback.format_exc()}")

    def _surface_to_telegram(self, message: str):
        """Send result to Telegram operator channel."""
        try:
            con = sqlite3.connect(self.engine.db_path)
            cur = con.cursor()
            # Write to a pending_notifications table if it exists
            # Otherwise just log — Telegram handler will pick up from DB
            cur.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='pending_notifications'
            """)
            if cur.fetchone():
                cur.execute("""
                    INSERT INTO pending_notifications (message, created_at)
                    VALUES (?, datetime('now'))
                """, (message,))
                con.commit()
            else:
                log.info(f"Surface (no notification table): {message[:100]}")
            con.close()
        except Exception as e:
            log.error(f"surface_to_telegram error: {e}")

# ═══════════════════════════════════════════════════════════════════
# METABOLISM DAEMON HOOK
# Add to MetabolismDaemon slow cycle for nightly runs
# ═══════════════════════════════════════════════════════════════════

def metabolism_slow_cycle_hook(db_path: str = _DB_PATH):
    """
    Call from MetabolismDaemon slow cycle.
    Checks pending triggers + runs one scheduled Throw-Net if due.
    """
    try:
        monitor = ThrowNetMonitor(db_path)

        # Check for pending autonomous triggers
        pending = monitor.trigger.pending_triggers()
        if pending:
            top = pending[0]
            log.info(f"Metabolism: processing pending trigger: {top['topic']}")
            constraint = (
                f"Nex cannot resolve '{top['topic']}' queries natively "
                f"({top['misses']} LLM fallbacks recorded)"
            )
            monitor.engine.run(
                constraint,
                trigger_mode='scheduled',
                trigger_topic=top['topic']
            )
            monitor.trigger.mark_fired(top['topic'])
            return

        # Scheduled: check if 24h since last Throw-Net session
        engine = ThrowNetEngine(db_path)
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            SELECT created_at FROM throw_net_sessions
            ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
        con.close()

        if row:
            last_run = datetime.fromisoformat(row[0])
            if datetime.now() - last_run < timedelta(hours=20):
                log.info("Metabolism: Throw-Net not due yet")
                return

        # Find the most frequent unresolved gap as tonight's constraint
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            SELECT term FROM gaps
            ORDER BY frequency DESC LIMIT 1
        """)
        gap = cur.fetchone()
        con.close()

        if gap:
            constraint = (
                f"Nex keeps encountering '{gap[0]}' as an unknown "
                f"but cannot resolve it from existing beliefs"
            )
            log.info(f"Metabolism: scheduled Throw-Net for gap: {gap[0]}")
            engine.run(
                constraint,
                trigger_mode='scheduled',
                trigger_topic=gap[0]
            )
    except Exception as e:
        log.error(f"metabolism_hook error: {e}")

# ═══════════════════════════════════════════════════════════════════
# SOUL LOOP PATCH SNIPPET
# Add to nex_soul_loop.py NBRE shadow block
# ═══════════════════════════════════════════════════════════════════

SOUL_LOOP_PATCH = '''
# ── Throw-Net Monitor hook ──────────────────────────────────────────
# Add after the NBRE shadow result is logged:
try:
    import sys as _tn_sys
    _tn_mod = _tn_sys.modules.get('nex.nex_throw_net')
    if _tn_mod is None:
        import importlib
        _tn_mod = importlib.import_module('nex.nex_throw_net')
    if not hasattr(_tn_mod, '_throw_net_monitor'):
        _tn_mod._throw_net_monitor = _tn_mod.ThrowNetMonitor()
    _tn_mod._throw_net_monitor.record_nbre_result(
        topic   = _nr.get('dominant_topic', 'general'),
        needs_llm = _nr.get('needs_llm', True),
        query   = query,
    )
except Exception as _tn_err:
    pass  # Never block soul loop
'''

# ═══════════════════════════════════════════════════════════════════
# TELEGRAM COMMAND HANDLER
# Wire into nex_telegram_commands.py
# ═══════════════════════════════════════════════════════════════════

def handle_thrownet_command(args: str, db_path: str = _DB_PATH) -> str:
    """
    Handle /thrownet "constraint description" from Telegram.
    Returns response string for Telegram.
    """
    constraint = args.strip().strip('"').strip("'")
    if not constraint:
        return (
            "Usage: /thrownet \"what Nex cannot do\"\n"
            "Example: /thrownet \"cannot reason causally about beliefs\""
        )
    if len(constraint) < 10:
        return "Please describe the constraint in more detail."

    try:
        engine = ThrowNetEngine(db_path)
        log.info(f"Telegram thrownet: [{constraint[:60]}]")
        session = engine.run(constraint, trigger_mode='manual')
        return session.get('surface_message', 'Throw-Net complete — check logs.')
    except Exception as e:
        log.error(f"handle_thrownet_command error: {e}")
        return f"Throw-Net error: {str(e)[:80]}"


def handle_approve_command(session_id: int,
                           notes: str = '',
                           db_path: str = _DB_PATH) -> str:
    """Handle /approve_tn <session_id> from Telegram."""
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            UPDATE throw_net_sessions
            SET approved = 1, outcome_notes = ?, surfaced = 1
            WHERE id = ?
        """, (notes or 'Approved via Telegram', session_id))
        con.commit()
        cur.execute("""
            SELECT top_candidate FROM throw_net_sessions WHERE id = ?
        """, (session_id,))
        row = cur.fetchone()
        con.close()
        if row and row[0]:
            candidate = json.loads(row[0]).get('candidate', {})
            content = candidate.get('content', '')[:120]
            return f"✓ Approved session {session_id}.\nQueued for build: {content}"
        return f"✓ Session {session_id} approved."
    except Exception as e:
        log.error(f"handle_approve error: {e}")
        return f"Approval error: {str(e)[:80]}"


def handle_sessions_command(limit: int = 5, db_path: str = _DB_PATH) -> str:
    """Handle /tn_sessions — show recent Throw-Net sessions."""
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            SELECT id, constraint_text, trigger_mode, status,
                   approved, created_at
            FROM throw_net_sessions
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        con.close()
        if not rows:
            return "No Throw-Net sessions yet."
        lines = ["Recent Throw-Net sessions:"]
        for r in rows:
            approved = "✓" if r[4] else "·"
            lines.append(
                f"{approved} [{r[0]}] {r[2]} — {r[1][:50]}... ({r[3]})"
            )
        return '\n'.join(lines)
    except Exception as e:
        return f"Sessions error: {str(e)[:80]}"

# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def _cli():
    parser = argparse.ArgumentParser(
        description="Throw-Net Engine — Nex autonomous self-improvement"
    )
    parser.add_argument('--install', action='store_true',
                        help='Install DB schema')
    parser.add_argument('--run',     type=str, default='',
                        help='Run Throw-Net on a constraint string')
    parser.add_argument('--sessions', action='store_true',
                        help='Show recent sessions')
    parser.add_argument('--pending', action='store_true',
                        help='Show pending autonomous triggers')
    parser.add_argument('--db', type=str, default=_DB_PATH,
                        help=f'DB path (default: {_DB_PATH})')
    args = parser.parse_args()

    if args.install:
        ok = install_schema(args.db)
        print("[✓] Schema installed" if ok else "[!] Schema install failed")
        print("\nAdd to soul loop NBRE shadow block:")
        print(SOUL_LOOP_PATCH)
        return

    if args.run:
        engine = ThrowNetEngine(args.db)
        session = engine.run(args.run, trigger_mode='manual')
        print(f"\nSession ID:   {session.get('session_id')}")
        print(f"Fetch items:  {len(session.get('fetch_results', []))}")
        print(f"NBRE fired:   {session.get('nbre_fired', 0)}")
        print(f"Tensions:     {len(session.get('tensions', []))}")
        refined = session.get('candidates_refined', [])
        buildable = [r for r in refined if r['buildable']]
        print(f"Candidates:   {len(refined)} scored, {len(buildable)} buildable")
        if buildable:
            top = buildable[0]
            print(f"\nTop candidate [{top['score']}/6]:")
            print(f"  {top['candidate'].get('content','')[:200]}")
        print(f"\n{session.get('surface_message','')}")
        return

    if args.sessions:
        print(handle_sessions_command(db_path=args.db))
        return

    if args.pending:
        td = TriggerDetector(args.db)
        pending = td.pending_triggers()
        if not pending:
            print("No pending triggers.")
        for p in pending:
            print(f"  topic={p['topic']} misses={p['misses']}")
        return

    parser.print_help()

if __name__ == '__main__':
    _cli()
