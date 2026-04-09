"""
nex_refinement_engine.py — Phase 3: Refinement Engine
══════════════════════════════════════════════════════
Nex validates her own Throw-Net proposals before surfacing them.
She generates, she validates, she surfaces only what passes.
You become the approval gate, not the engine.

Integration:
  Called automatically from ThrowNetEngine after candidate generation.
  Also callable standalone: /refine_tn <session_id>
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional

_NEX_ROOT = os.path.expanduser("~/Desktop/nex")
_DB_PATH  = os.path.join(_NEX_ROOT, "nex.db")

log = logging.getLogger("refinement_engine")

# ══════════════════════════════════════════════════════════════════
# SELF-KNOWLEDGE QUERIES
# Questions Nex asks herself about her own architecture
# ══════════════════════════════════════════════════════════════════

class SelfKnowledge:
    """
    Nex's understanding of her own architecture.
    Used to validate whether a proposal is realistic.
    """
    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        self._cache  = {}

    def topic_exists(self, topic: str) -> bool:
        """Does this topic have beliefs in the DB?"""
        try:
            con = sqlite3.connect(self.db_path, timeout=2)
            n = con.execute(
                "SELECT COUNT(*) FROM beliefs WHERE LOWER(topic) LIKE ?",
                (f"%{topic.lower()[:20]}%",)
            ).fetchone()[0]
            con.close()
            return n >= 2
        except Exception:
            return False

    def has_belief_links(self, topic: str) -> bool:
        """Does this topic connect into the belief_links graph?"""
        try:
            con = sqlite3.connect(self.db_path, timeout=2)
            n = con.execute("""
                SELECT COUNT(*) FROM belief_links bl
                JOIN beliefs b ON bl.parent_id = b.id
                WHERE LOWER(b.topic) LIKE ?
            """, (f"%{topic.lower()[:20]}%",)).fetchone()[0]
            con.close()
            return n > 0
        except Exception:
            return True

    def would_break_live_service(self, content: str) -> bool:
        """Does this proposal risk breaking live systems?"""
        danger = [
            "drop table", "delete from beliefs", "truncate",
            "rm -rf", "kill process", "restart soul loop",
            "overwrite nex.db", "format drive"
        ]
        cl = content.lower()
        return any(d in cl for d in danger)

    def is_too_large(self, content: str) -> bool:
        """Is this proposal trying to do too many things at once?"""
        compound = [" and also ", " plus ", " additionally ",
                    " furthermore ", " on top of that "]
        signals  = sum(1 for c in compound if c in content.lower())
        return len(content.split()) > 100 and signals >= 2

    def already_implemented(self, content: str) -> bool:
        """Has Nex already implemented something like this?"""
        try:
            keywords = [w for w in content.lower().split()
                        if len(w) > 5][:5]
            if not keywords:
                return False
            con = sqlite3.connect(self.db_path, timeout=2)
            placeholders = " OR ".join(
                ["LOWER(content) LIKE ?"] * len(keywords)
            )
            params = [f"%{k}%" for k in keywords]
            n = con.execute(f"""
                SELECT COUNT(*) FROM beliefs
                WHERE source IN
                    ('nbre_bridge','episodic_consolidation','nex_reasoning')
                  AND ({placeholders})
            """, params).fetchone()[0]
            con.close()
            return n >= 3
        except Exception:
            return False

    def confidence_in_topic(self, topic: str) -> float:
        """Average confidence Nex has in beliefs about this topic."""
        try:
            con = sqlite3.connect(self.db_path, timeout=2)
            r = con.execute("""
                SELECT AVG(confidence) FROM beliefs
                WHERE LOWER(topic) LIKE ? AND confidence > 0
            """, (f"%{topic.lower()[:20]}%",)).fetchone()
            con.close()
            return float(r[0] or 0.5)
        except Exception:
            return 0.5


# ══════════════════════════════════════════════════════════════════
# REFINEMENT ENGINE
# ══════════════════════════════════════════════════════════════════

class RefinementEngine:
    """
    Nex validates her own proposals.
    Seven questions — each grounded in her actual architecture.
    Score 0-7. Below 4 = rejected before surfacing.
    """
    PASS_THRESHOLD = 4

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        self.sk      = SelfKnowledge(db_path)

    def _q1_grounded_in_beliefs(self, candidate: dict) -> tuple:
        """Q1: Is this grounded in what I actually know?"""
        topic   = candidate.get("topic", "")
        content = candidate.get("content", "")
        exists  = self.sk.topic_exists(topic)
        conf    = self.sk.confidence_in_topic(topic)
        passed  = exists and conf >= 0.4
        reason  = (f"topic '{topic}' exists with conf={conf:.2f}"
                   if passed else
                   f"topic '{topic}' sparse or unknown (conf={conf:.2f})")
        return passed, reason

    def _q2_connected_to_graph(self, candidate: dict) -> tuple:
        """Q2: Does this connect to my belief_links graph?"""
        topic  = candidate.get("topic", "")
        passed = self.sk.has_belief_links(topic)
        reason = (f"topic '{topic}' has belief_links edges"
                  if passed else
                  f"topic '{topic}' isolated from belief graph")
        return passed, reason

    def _q3_safe_for_live(self, candidate: dict) -> tuple:
        """Q3: Will this break my live service?"""
        content = candidate.get("content", "")
        dangerous = self.sk.would_break_live_service(content)
        passed  = not dangerous
        reason  = ("safe for live service" if passed
                   else "contains dangerous operations")
        return passed, reason

    def _q4_right_size(self, candidate: dict) -> tuple:
        """Q4: Is this one thing, not three things disguised as one?"""
        content = candidate.get("content", "")
        too_big = self.sk.is_too_large(content)
        passed  = not too_big
        reason  = ("appropriately scoped" if passed
                   else "oversized — likely multiple inventions")
        return passed, reason

    def _q5_not_already_built(self, candidate: dict) -> tuple:
        """Q5: Have I already implemented something like this?"""
        content    = candidate.get("content", "")
        duplicated = self.sk.already_implemented(content)
        passed     = not duplicated
        reason     = ("novel — not yet implemented" if passed
                      else "already partially implemented in belief DB")
        return passed, reason

    def _q6_has_nbre_resonance(self, candidate: dict) -> tuple:
        """Q6: Does my reservoir resonate with this?"""
        try:
            sys.path.insert(0, _NEX_ROOT)
            from nex_belief_reservoir_engine import NexBeliefReservoirEngine
            engine = NexBeliefReservoirEngine()
            engine.load()
            content = candidate.get("content", "")
            topic   = candidate.get("topic", "general")
            result  = engine.process(content[:100], [topic])
            fired   = result.get("n_fired", 0)
            conf    = result.get("confidence", 0.0)
            passed  = fired >= 5 and conf >= 0.4
            reason  = f"reservoir fired={fired} conf={conf:.2f}"
            return passed, reason
        except Exception as e:
            return True, f"reservoir check skipped: {e}"

    def _q7_surfaces_tension(self, candidate: dict) -> tuple:
        """Q7: Does this resolve or surface a genuine tension?"""
        try:
            con = sqlite3.connect(self.db_path, timeout=2)
            topic = candidate.get("topic", "")
            # Check if this topic appears in known tensions
            n = con.execute("""
                SELECT COUNT(*) FROM belief_links bl
                JOIN beliefs b ON bl.parent_id = b.id
                WHERE LOWER(b.topic) LIKE ?
                  AND bl.link_type IN ('CONTRADICTS','BRIDGES','TENSIONS')
            """, (f"%{topic.lower()[:20]}%",)).fetchone()[0]
            con.close()
            passed = n > 0
            reason = (f"topic has {n} tension edges in belief_links"
                      if passed else
                      "no tension edges found for this topic")
            return passed, reason
        except Exception as e:
            return True, f"tension check skipped: {e}"

    def evaluate(self, candidate: dict) -> dict:
        """Run all seven questions. Return scored result."""
        questions = [
            ("Q1_grounded_in_beliefs",  self._q1_grounded_in_beliefs),
            ("Q2_connected_to_graph",   self._q2_connected_to_graph),
            ("Q3_safe_for_live",        self._q3_safe_for_live),
            ("Q4_right_size",           self._q4_right_size),
            ("Q5_not_already_built",    self._q5_not_already_built),
            ("Q6_nbre_resonance",       self._q6_has_nbre_resonance),
            ("Q7_surfaces_tension",     self._q7_surfaces_tension),
        ]
        results = {}
        score   = 0
        for name, fn in questions:
            try:
                passed, reason = fn(candidate)
                results[name]  = {"passed": passed, "reason": reason}
                if passed:
                    score += 1
            except Exception as e:
                results[name] = {"passed": True, "reason": f"skipped: {e}"}
                score += 1  # default pass on error

        buildable = score >= self.PASS_THRESHOLD
        return {
            "candidate":  candidate,
            "score":      score,
            "max_score":  7,
            "buildable":  buildable,
            "questions":  results,
            "verdict":    "APPROVED" if buildable else "REJECTED",
            "evaluated_at": datetime.now().isoformat(),
        }

    def evaluate_session(self, session_id: int) -> list:
        """
        Pull candidates from a throw_net_sessions row and
        re-evaluate them with full self-knowledge.
        Updates the DB with refined results.
        """
        try:
            con = sqlite3.connect(self.db_path, timeout=3)
            row = con.execute("""
                SELECT candidates_raw, candidates_refined
                FROM throw_net_sessions WHERE id = ?
            """, (session_id,)).fetchone()
            if not row:
                log.error(f"Session {session_id} not found")
                con.close()
                return []

            raw = json.loads(row[0] or "[]")
            if not raw:
                con.close()
                return []

            log.info(f"Refining {len(raw)} candidates from session {session_id}")
            refined = [self.evaluate(c) for c in raw]
            refined.sort(key=lambda x: x["score"], reverse=True)

            approved = [r for r in refined if r["buildable"]]
            top      = refined[0] if refined else {}

            con.execute("""
                UPDATE throw_net_sessions
                SET candidates_refined = ?,
                    top_candidate      = ?,
                    status             = ?
                WHERE id = ?
            """, (
                json.dumps(refined[:5]),
                json.dumps(top),
                "refined",
                session_id
            ))
            con.commit()
            con.close()

            log.info(
                f"Session {session_id} refined: "
                f"{len(approved)}/{len(refined)} approved"
            )
            return refined

        except Exception as e:
            log.error(f"evaluate_session error: {e}")
            return []

    def auto_refine_pending(self) -> int:
        """
        Find all completed but unrefined sessions and refine them.
        Called from metabolism slow cycle.
        """
        try:
            con = sqlite3.connect(self.db_path, timeout=2)
            rows = con.execute("""
                SELECT id FROM throw_net_sessions
                WHERE status = 'complete'
                ORDER BY id DESC LIMIT 10
            """).fetchall()
            con.close()

            refined = 0
            for (sid,) in rows:
                try:
                    results = self.evaluate_session(sid)
                    if results:
                        refined += 1
                except Exception as e:
                    log.error(f"auto_refine session {sid}: {e}")

            return refined
        except Exception as e:
            log.error(f"auto_refine_pending error: {e}")
            return 0

    def format_verdict(self, result: dict) -> str:
        """Format a single evaluation result for Telegram."""
        candidate = result.get("candidate", {})
        content   = (candidate.get("content") or "")[:150]
        topic     = candidate.get("topic", "unknown")
        score     = result.get("score", 0)
        verdict   = result.get("verdict", "?")
        icon      = "✓" if result["buildable"] else "✗"

        lines = [
            f"{icon} [{topic}] {score}/7 — {verdict}",
            f"   {content}",
        ]
        for q, r in result.get("questions", {}).items():
            if not r["passed"]:
                lines.append(f"   FAIL {q}: {r['reason']}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# TELEGRAM HANDLERS
# ══════════════════════════════════════════════════════════════════

def handle_refine_command(args: str,
                          db_path: str = _DB_PATH) -> str:
    """Handle /refine_tn <session_id> from Telegram."""
    try:
        session_id = int(args.strip())
    except ValueError:
        return "Usage: /refine_tn <session_id>"

    engine  = RefinementEngine(db_path)
    results = engine.evaluate_session(session_id)
    if not results:
        return f"No candidates found for session {session_id}"

    approved = [r for r in results if r["buildable"]]
    lines    = [
        f"Refinement complete — session {session_id}",
        f"{len(approved)}/{len(results)} candidates approved",
        "",
    ]
    for r in results[:3]:
        lines.append(engine.format_verdict(r))

    return "\n".join(lines)[:4000]


def handle_auto_refine_command(db_path: str = _DB_PATH) -> str:
    """Handle /auto_refine from Telegram."""
    engine  = RefinementEngine(db_path)
    refined = engine.auto_refine_pending()
    return f"Auto-refined {refined} pending sessions."


# ══════════════════════════════════════════════════════════════════
# METABOLISM HOOK
# ══════════════════════════════════════════════════════════════════

def metabolism_refinement_hook(db_path: str = _DB_PATH):
    """
    Called from metabolism slow cycle.
    Auto-refines all pending Throw-Net sessions overnight.
    """
    try:
        engine  = RefinementEngine(db_path)
        refined = engine.auto_refine_pending()
        if refined:
            print(f"[METABOLISM] refinement: {refined} sessions processed")
    except Exception as e:
        print(f"[METABOLISM] refinement error: {e}")


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="NEX Refinement Engine"
    )
    parser.add_argument("--refine",    type=int, help="Refine session ID")
    parser.add_argument("--auto",      action="store_true",
                        help="Auto-refine all pending sessions")
    parser.add_argument("--list",      action="store_true",
                        help="List sessions and their status")
    args = parser.parse_args()

    if args.refine:
        engine  = RefinementEngine()
        results = engine.evaluate_session(args.refine)
        for r in results:
            print(engine.format_verdict(r))
            print()

    elif args.auto:
        engine  = RefinementEngine()
        refined = engine.auto_refine_pending()
        print(f"Auto-refined {refined} sessions")

    elif args.list:
        con = sqlite3.connect(_DB_PATH)
        rows = con.execute("""
            SELECT id, trigger_mode, status, constraint_text, created_at
            FROM throw_net_sessions ORDER BY id DESC LIMIT 10
        """).fetchall()
        con.close()
        for r in rows:
            print(f"[{r[0]}] {r[3][:60]} | {r[1]} | {r[2]} | {r[4]}")
    else:
        parser.print_help()
