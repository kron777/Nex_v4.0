#!/usr/bin/env python3
"""
nex_belief_colony.py  —  NEX Multi-Agent Belief Colony
═══════════════════════════════════════════════════════
Four lightweight specialist agents argue over the shared belief graph.
Each has a distinct role and a distinct lens. The coordinator runs debate
rounds, collects proposals, and applies the winners.

Agents:
  CuratorAgent      — quality gate: promote strong beliefs, flag weak ones
  ContradictorAgent — devil's advocate: challenges top beliefs, surfaces tensions
  SynthesizerAgent  — integrator: merges clusters into meta-beliefs
  GoalAgent         — planner: derives research goals from gaps + world-model

Colony does NOT replace:
  nex_contradiction_resolver.py  — still runs on its own schedule (graph-level)
  nex_nightly.py                 — still runs the full consolidation pipeline
  nex_active_inference.py        — still runs the FE minimization loop

Colony ADDS:
  Internal debate that produces richer belief updates than any single pass
  Cross-agent proposals that no single module would generate alone
  colony_debate table: transparent reasoning trace

Wire-in (run.py):
    from nex_belief_colony import ColonyDaemon as _CD
    _colony = _CD()
    _colony.start()
    print("  [COLONY] 4-agent belief colony started")

Manual:
    python3 ~/Desktop/nex/nex_belief_colony.py --debate
    python3 ~/Desktop/nex/nex_belief_colony.py --status
"""

from __future__ import annotations
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── paths ─────────────────────────────────────────────────────────────────────
NEX_DIR  = Path.home() / "Desktop" / "nex"
DB_PATH  = NEX_DIR / "nex.db"
CFG_DIR  = Path.home() / ".config" / "nex"
LLAMA_URL = "http://127.0.0.1:8080"

DEBATE_INTERVAL_S   = 7200    # run a debate round every 2h
DEBATE_INTERVAL_HI  = 3600    # every 1h if free energy > 0.5
STARTUP_DELAY_S     = 420     # 7 min — let other daemons settle first
MAX_BELIEFS_PER_TOPIC = 8     # beliefs fed to each agent per round

# ── helpers ───────────────────────────────────────────────────────────────────
def _llm(prompt: str, max_tokens: int = 300, temperature: float = 0.35) -> str:
    payload = json.dumps({
        "prompt":      prompt,
        "n_predict":   max_tokens,
        "temperature": temperature,
        "stop":        ["<|user|>", "<|system|>", "---END---", "||"],
    }).encode()
    req = urllib.request.Request(
        f"{LLAMA_URL}/completion",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read()).get("content", "").strip()
    except Exception:
        return ""

def _llm_json(prompt: str, max_tokens: int = 300) -> dict:
    raw = _llm(prompt, max_tokens)
    if not raw:
        return {}
    for attempt in [raw, "{" + raw if not raw.strip().startswith("{") else raw]:
        try:
            s = attempt.strip()
            if not s.endswith("}"): s += "}"
            return json.loads(s)
        except Exception:
            pass
    # fallback: extract quoted strings
    return {"raw": raw[:200]}

def _open_db() -> Optional[sqlite3.Connection]:
    for p in [DB_PATH, CFG_DIR / "nex.db"]:
        if p.exists():
            conn = sqlite3.connect(str(p), timeout=15)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            return conn
    return None

def _text_col(conn: sqlite3.Connection) -> str:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
    return "content" if "content" in cols else ("belief" if "belief" in cols else "text")

def _load_topic_beliefs(conn: sqlite3.Connection, topic: str, n: int = MAX_BELIEFS_PER_TOPIC) -> list[dict]:
    tc   = _text_col(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
    has_tags   = "tags" in cols
    has_source = "source" in cols

    where_parts = []
    params = []
    if has_tags:
        where_parts.append(f"(tags LIKE ? OR tags LIKE ?)")
        params += [f"%{topic}%", f"{topic},%"]
    where_parts.append(f"{tc} LIKE ?")
    params.append(f"%{topic}%")

    where = " OR ".join(where_parts) if where_parts else "1=1"

    rows = conn.execute(f"""
        SELECT id, {tc}, confidence,
               {'source' if has_source else repr('')} as source,
               {'tags' if has_tags else repr('')} as tags
        FROM beliefs
        WHERE ({where}) AND confidence >= 0.45
        ORDER BY confidence DESC
        LIMIT ?
    """, params + [n]).fetchall()

    return [{"id": r["id"], "content": r[tc], "confidence": r["confidence"] or 0.5,
             "source": r["source"] or "", "tags": r["tags"] or ""} for r in rows]


def _select_debate_topic(conn: sqlite3.Connection) -> str:
    """Pick the topic with the most uncertain beliefs — highest AIF value."""
    try:
        # Try to use AIF state for topic selection
        aif_path = CFG_DIR / "nex_aif_state.json"
        if aif_path.exists():
            history = json.loads(aif_path.read_text())
            if history:
                last = history[-1]
                top_efe = last.get("top_efe", [])
                if top_efe:
                    return top_efe[0][0]   # topic with lowest EFE
    except Exception:
        pass

    # Fallback: tag with most low-confidence beliefs
    tc = _text_col(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
    if "tags" not in cols:
        return "general"

    rows = conn.execute(f"""
        SELECT tags, COUNT(*) as c, AVG(confidence) as avg_c
        FROM beliefs
        WHERE tags IS NOT NULL AND tags != '' AND confidence < 0.70
        GROUP BY tags
        HAVING c >= 3
        ORDER BY c DESC LIMIT 1
    """).fetchone()

    if rows:
        # tags is comma-separated — take first tag
        return rows["tags"].split(",")[0].strip() or "general"
    return "general"


# ══════════════════════════════════════════════════════════════════════════════
# BASE AGENT
# ══════════════════════════════════════════════════════════════════════════════

class ColonyAgent:
    """Base class for all colony agents."""
    name: str = "base"
    role: str = "base role"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def deliberate(self, topic: str, beliefs: list[dict]) -> dict:
        """Override in subclasses. Returns proposal dict."""
        raise NotImplementedError

    def _belief_block(self, beliefs: list[dict]) -> str:
        return "\n".join(f"- [{b['confidence']:.2f}] {b['content']}" for b in beliefs)


# ══════════════════════════════════════════════════════════════════════════════
# CURATOR AGENT — quality gate
# ══════════════════════════════════════════════════════════════════════════════

class CuratorAgent(ColonyAgent):
    """
    Reviews beliefs for quality. Promotes strong ones, flags weak ones.
    Lens: factual completeness, standalone clarity, specificity.
    """
    name = "Curator"
    role = "quality gate — promote strong beliefs, flag weak ones"

    PROMPT = """<|system|>
You are the Curator agent in a belief colony. Your job: evaluate belief quality.
Output ONLY valid JSON. No prose.
<|user|>
Topic: {topic}

Beliefs to evaluate:
{belief_block}

For each belief, decide: PROMOTE (genuinely strong, specific, standalone) or FLAG (vague, repetitive, or low-value).
Also identify the single strongest belief worth boosting.

Return ONLY:
{{"promote": ["belief text snippet 1", ...], "flag": ["belief text snippet 2", ...], "strongest": "the best belief here", "reason": "one sentence"}}
<|assistant|>
{{"""

    def deliberate(self, topic: str, beliefs: list[dict]) -> dict:
        if not beliefs:
            return {"agent": self.name, "action": "noop", "reason": "no beliefs"}

        raw = _llm_json(self.PROMPT.format(
            topic=topic,
            belief_block=self._belief_block(beliefs)
        ), max_tokens=400)

        promote_snippets = raw.get("promote", [])
        flag_snippets    = raw.get("flag", [])
        strongest        = raw.get("strongest", "")
        reason           = raw.get("reason", "")

        # Apply promotions and flags
        promoted = flagged = 0
        tc = _text_col(self.conn)
        for b in beliefs:
            content = b["content"]
            is_promote = any(s[:40] in content for s in promote_snippets if s)
            is_flag    = any(s[:40] in content for s in flag_snippets if s)

            if is_promote and b["confidence"] < 0.88:
                new_conf = min(0.90, b["confidence"] + 0.08)
                self.conn.execute(f"UPDATE beliefs SET confidence=? WHERE id=?",
                                  (round(new_conf, 3), b["id"]))
                promoted += 1
            elif is_flag and b["confidence"] > 0.35:
                new_conf = max(0.35, b["confidence"] - 0.07)
                self.conn.execute(f"UPDATE beliefs SET confidence=? WHERE id=?",
                                  (round(new_conf, 3), b["id"]))
                flagged += 1

        self.conn.commit()
        return {
            "agent":    self.name,
            "action":   "quality_gate",
            "promoted": promoted,
            "flagged":  flagged,
            "strongest": strongest[:120] if strongest else "",
            "reason":   reason[:200],
        }


# ══════════════════════════════════════════════════════════════════════════════
# CONTRADICTOR AGENT — devil's advocate
# ══════════════════════════════════════════════════════════════════════════════

class ContradictorAgent(ColonyAgent):
    """
    Challenges the top belief in a topic cluster.
    Generates a counter-belief and runs the existing graph-level resolver.
    Lens: epistemic tension, untested assumptions.
    """
    name = "Contradictor"
    role = "devil's advocate — surface tensions, generate counter-beliefs"

    PROMPT = """<|system|>
You are the Contradictor agent in a belief colony. Your job: find weaknesses.
Output ONLY valid JSON. No prose.
<|user|>
Topic: {topic}

The strongest belief in this cluster:
"{primary}"

Supporting beliefs:
{belief_block}

Generate ONE specific counter-belief that most directly challenges the primary belief.
Also name the core assumption it relies on.

Return ONLY:
{{"counter_belief": "a complete standalone sentence that challenges the primary", "assumption": "the assumption being challenged", "tension_type": "empirical|logical|values|scope"}}
<|assistant|>
{{"""

    def deliberate(self, topic: str, beliefs: list[dict]) -> dict:
        if not beliefs:
            return {"agent": self.name, "action": "noop", "reason": "no beliefs"}

        primary = max(beliefs, key=lambda b: b["confidence"])
        others  = [b for b in beliefs if b["id"] != primary["id"]]

        raw = _llm_json(self.PROMPT.format(
            topic=topic,
            primary=primary["content"],
            belief_block=self._belief_block(others[:4])
        ), max_tokens=250)

        counter  = raw.get("counter_belief", "")
        assumption = raw.get("assumption", "")
        tension_type = raw.get("tension_type", "logical")

        # Write counter-belief to DB as a low-confidence challenger
        written = False
        if counter and len(counter.split()) >= 8:
            try:
                tc   = _text_col(self.conn)
                cols = {r[1] for r in self.conn.execute("PRAGMA table_info(beliefs)").fetchall()}
                base_cols = [tc, "confidence", "source"]
                base_vals = [counter, 0.45, f"colony_contradictor:{topic}"]
                if "tags" in cols:
                    base_cols.append("tags"); base_vals.append(f"{topic},colony_tension")
                if "created_at" in cols:
                    base_cols.append("created_at")
                    base_vals.append(datetime.now(timezone.utc).isoformat())
                ph = ",".join(["?"] * len(base_cols))
                self.conn.execute(
                    f"INSERT OR IGNORE INTO beliefs ({','.join(base_cols)}) VALUES ({ph})",
                    base_vals
                )
                self.conn.commit()
                written = True
            except Exception as e:
                print(f"  [Contradictor] write error: {e}", flush=True)

        # Also trigger graph-level resolution on this topic
        resolved = 0
        try:
            sys.path.insert(0, str(NEX_DIR))
            from nex_contradiction_resolver import resolve_contradictions
            result   = resolve_contradictions(topic_filter=topic, dry_run=False,
                                              limit=20, verbose=False)
            resolved = result.get("resolved", 0) + result.get("archived", 0)
        except Exception:
            pass

        return {
            "agent":        self.name,
            "action":       "challenge",
            "counter_belief": counter[:150] if counter else "",
            "assumption":   assumption[:100] if assumption else "",
            "tension_type": tension_type,
            "counter_written": written,
            "graph_resolved": resolved,
        }


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHESIZER AGENT — integrator
# ══════════════════════════════════════════════════════════════════════════════

class SynthesizerAgent(ColonyAgent):
    """
    Merges the cluster into a single higher-order meta-belief.
    Lens: abstraction, pattern, underlying principle.
    """
    name = "Synthesizer"
    role = "integrator — generate meta-beliefs from clusters"

    PROMPT = """<|system|>
You are the Synthesizer agent in a belief colony. Your job: find the deeper principle.
Output ONLY valid JSON. No prose.
<|user|>
Topic: {topic}

Beliefs in this cluster:
{belief_block}

Synthesize ONE meta-belief (20-60 words) that captures the underlying principle
unifying these beliefs. It must be a generalization, not a summary.
Also rate your confidence in it (0.0-1.0).

Return ONLY:
{{"meta_belief": "your meta-belief here", "confidence": 0.82, "principle_type": "causal|structural|normative|empirical"}}
<|assistant|>
{{"""

    def deliberate(self, topic: str, beliefs: list[dict]) -> dict:
        if len(beliefs) < 3:
            return {"agent": self.name, "action": "noop", "reason": "too few beliefs"}

        # Try to enrich with causal chains from CausalEngine
        causal_block = ""
        try:
            sys.path.insert(0, str(NEX_DIR))
            from nex_causal_engine import CausalEngine
            ce = CausalEngine()
            seed_ids = [b["id"] for b in beliefs[:4] if b.get("id")]
            reasoning = ce.reason_from_query(seed_ids, max_hops=2)
            if reasoning.get("chains"):
                causal_block = "\nCausal chains in this cluster:\n"
                for chain in reasoning["chains"][:3]:
                    path_text = " → ".join(
                        b.get("content", "")[:50] for b in chain.get("beliefs", [])
                    )
                    causal_block += f"  {path_text}\n"
        except Exception:
            pass

        raw = _llm_json(self.PROMPT.format(
            topic=topic,
            belief_block=self._belief_block(beliefs) + causal_block
        ), max_tokens=250)

        meta     = raw.get("meta_belief", "")
        conf     = float(raw.get("confidence", 0.75))
        ptype    = raw.get("principle_type", "structural")
        written  = False

        if meta and len(meta.split()) >= 8:
            try:
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS meta_beliefs (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        topic        TEXT,
                        meta_belief  TEXT,
                        confidence   REAL,
                        belief_count INTEGER,
                        source       TEXT,
                        created_at   TEXT
                    )
                """)
                self.conn.execute(
                    "INSERT INTO meta_beliefs (topic, meta_belief, confidence, belief_count, source, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (topic, meta, round(conf, 3), len(beliefs),
                     f"colony_synthesizer", datetime.now(timezone.utc).isoformat())
                )
                self.conn.commit()
                written = True
            except Exception as e:
                print(f"  [Synthesizer] write error: {e}", flush=True)

        return {
            "agent":          self.name,
            "action":         "synthesize",
            "meta_belief":    meta[:150] if meta else "",
            "confidence":     round(conf, 3),
            "principle_type": ptype,
            "written":        written,
        }


# ══════════════════════════════════════════════════════════════════════════════
# GOAL AGENT — research planner
# ══════════════════════════════════════════════════════════════════════════════

class GoalAgent(ColonyAgent):
    """
    Derives specific research questions from belief gaps + world-model anchors.
    Lens: what NEX doesn't know yet that matters most.
    """
    name = "GoalAgent"
    role = "planner — derive research goals from belief gaps"

    PROMPT = """<|system|>
You are the Goal agent in a belief colony. Your job: identify what to learn next.
Output ONLY valid JSON. No prose.
<|user|>
Topic: {topic}

What NEX currently believes (strong beliefs):
{strong_block}

What NEX is uncertain about (weak beliefs):
{weak_block}

Generate 2 specific, searchable research questions that would most reduce NEX's uncertainty on this topic.
Each question should be a specific claim to investigate, not a generic topic.

Return ONLY:
{{"goals": ["specific research question 1", "specific research question 2"], "priority": "urgent|high|normal"}}
<|assistant|>
{{"""

    def deliberate(self, topic: str, beliefs: list[dict]) -> dict:
        if not beliefs:
            return {"agent": self.name, "action": "noop", "reason": "no beliefs"}

        strong = [b for b in beliefs if b["confidence"] >= 0.70]
        weak   = [b for b in beliefs if b["confidence"] < 0.60]

        raw = _llm_json(self.PROMPT.format(
            topic=topic,
            strong_block=self._belief_block(strong[:3]) or "(none yet)",
            weak_block=self._belief_block(weak[:3]) or "(none yet)"
        ), max_tokens=250)

        goals    = raw.get("goals", [])
        priority = raw.get("priority", "normal")
        queued   = []

        if goals:
            try:
                sys.path.insert(0, str(NEX_DIR / "nex"))
                sys.path.insert(0, str(NEX_DIR))
                from nex_curiosity import CuriosityQueue
                q = CuriosityQueue()
                for goal in goals[:2]:
                    if goal and len(goal) > 8:
                        added = q.enqueue(
                            topic=goal[:80],
                            reason=f"colony_goal_{priority}",
                            confidence=0.3,
                        )
                        if added:
                            queued.append(goal[:80])
            except Exception as e:
                print(f"  [GoalAgent] queue error: {e}", flush=True)

        # Also update GoalSystem if available
        try:
            from nex_belief_graph import GoalSystem
            gs = GoalSystem()
            for goal in queued:
                goal_id = re.sub(r"[^a-z0-9_]", "_", goal[:30].lower())
                gs.add_goal(goal_id, goal[:120], priority=0.70)
        except Exception:
            pass

        return {
            "agent":    self.name,
            "action":   "goal_generation",
            "goals":    goals[:2],
            "priority": priority,
            "queued":   queued,
        }


# ══════════════════════════════════════════════════════════════════════════════
# COLONY COORDINATOR
# ══════════════════════════════════════════════════════════════════════════════

class ColonyCoordinator:
    """
    Runs one debate round. Each agent deliberates on the selected topic.
    Logs the transcript to colony_debate table.
    """

    def __init__(self):
        self._round = 0

    def _init_table(self, conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS colony_debate (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                round      INTEGER,
                topic      TEXT,
                timestamp  TEXT,
                transcript TEXT,
                proposals  TEXT
            )
        """)
        conn.commit()

    def run_debate(self) -> dict:
        self._round += 1
        t0 = time.time()
        conn = _open_db()
        if not conn:
            return {"error": "no db", "round": self._round}

        self._init_table(conn)

        topic    = _select_debate_topic(conn)
        beliefs  = _load_topic_beliefs(conn, topic)

        print(f"  [Colony] round={self._round}  topic='{topic}'  "
              f"beliefs={len(beliefs)}", flush=True)

        if not beliefs:
            conn.close()
            return {"round": self._round, "topic": topic, "status": "no_beliefs"}

        # Instantiate agents
        agents = [
            CuratorAgent(conn),
            ContradictorAgent(conn),
            SynthesizerAgent(conn),
            GoalAgent(conn),
        ]

        proposals = []
        for agent in agents:
            try:
                proposal = agent.deliberate(topic, beliefs)
                proposals.append(proposal)
                print(f"  [Colony]   {agent.name}: {proposal.get('action','?')}  "
                      f"— {str(proposal)[:80]}", flush=True)
            except Exception as e:
                proposals.append({"agent": agent.name, "action": "error", "error": str(e)})
                print(f"  [Colony]   {agent.name}: ERROR — {e}", flush=True)

        elapsed = round(time.time() - t0, 1)

        # Log debate
        try:
            conn.execute(
                "INSERT INTO colony_debate (round, topic, timestamp, transcript, proposals) "
                "VALUES (?,?,?,?,?)",
                (self._round, topic,
                 datetime.now(timezone.utc).isoformat(),
                 f"4-agent debate on '{topic}', {len(beliefs)} beliefs",
                 json.dumps(proposals, default=str))
            )
            conn.commit()
        except Exception as e:
            print(f"  [Colony] log error: {e}", flush=True)

        conn.close()

        report = {
            "round":     self._round,
            "topic":     topic,
            "beliefs":   len(beliefs),
            "proposals": proposals,
            "elapsed_s": elapsed,
        }
        print(f"  [Colony] debate complete — {elapsed}s", flush=True)
        return report


# ══════════════════════════════════════════════════════════════════════════════
# COLONY DAEMON
# ══════════════════════════════════════════════════════════════════════════════

def _free_energy() -> float:
    """Read current free energy from AIF state."""
    try:
        aif_path = (Path.home() / ".config" / "nex" / "nex_aif_state.json")
        if not aif_path.exists():
            aif_path = NEX_DIR / "nex_aif_state.json"
        if aif_path.exists():
            history = json.loads(aif_path.read_text())
            if history:
                # Free energy not directly stored — use weakest topic uncertainty as proxy
                snap = history[-1].get("belief_state", {})
                weakest = snap.get("weakest", [])
                if weakest:
                    return float(weakest[0][1])  # highest uncertainty score
    except Exception:
        pass
    return 0.3   # default: moderate


class ColonyDaemon:
    """
    Background daemon that runs colony debate rounds on schedule.
    Runs more frequently when free energy is high (NEX is most uncertain).

    Wire-in (run.py):
        from nex_belief_colony import ColonyDaemon as _CD
        _colony = _CD()
        _colony.start()
    """

    def __init__(self):
        self.coordinator = ColonyCoordinator()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="nex-colony"
        )
        self._stop = threading.Event()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        # Wait for other daemons to initialise
        self._stop.wait(STARTUP_DELAY_S)

        while not self._stop.is_set():
            try:
                self.coordinator.run_debate()
            except Exception as e:
                print(f"  [Colony] loop error: {e}", flush=True)

            fe       = _free_energy()
            interval = DEBATE_INTERVAL_HI if fe > 0.5 else DEBATE_INTERVAL_S
            print(f"  [Colony] free_energy={fe:.3f}  next_debate_in={interval//60}min",
                  flush=True)
            self._stop.wait(interval)

    def status(self) -> dict:
        conn = _open_db()
        if not conn:
            return {"error": "no db"}
        try:
            row = conn.execute(
                "SELECT round, topic, timestamp FROM colony_debate "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                return {"last_round": row["round"], "last_topic": row["topic"],
                        "last_at": row["timestamp"]}
            return {"status": "no debates yet"}
        except Exception:
            return {"status": "colony_debate table not found"}


# ── standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEX Belief Colony")
    parser.add_argument("--debate", action="store_true", help="Run one debate round now")
    parser.add_argument("--status", action="store_true", help="Show last debate")
    args = parser.parse_args()

    if args.status:
        d = ColonyDaemon()
        print(json.dumps(d.status(), indent=2))
    else:
        c = ColonyCoordinator()
        report = c.run_debate()
        print(json.dumps(report, indent=2, default=str))
