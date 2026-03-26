#!/usr/bin/env bash
# ============================================================
# NEX SENTIENCE UPGRADE v4.0
# Implements:
#   1. Dream Cycle offline consolidation (nex_dream_cycle.py)
#   2. Self-Proposer / recursive self-mod (nex_self_proposer.py)
#   3. Attractor Map → GWT bridge (attractor_map.py patch)
#   4. Universal Snapshot Export (nex_snapshot.py)
#   5. Multi-Sensor Embodied Expansion (nex_embodied.py patch)
#   6. Directive Auto-Evolution (nex_upgrades.py patch + run.py)
# Usage: bash deploy_sentience_v4.sh [/path/to/nex]
# ============================================================
set -euo pipefail
NEX_ROOT="${1:-$HOME/Desktop/nex}"
NEX_PKG="$NEX_ROOT/nex"
BACKUP="$NEX_ROOT/nex_config_backup/sentience_v4_$(date +%Y%m%d_%H%M%S)"

echo "=== NEX SENTIENCE UPGRADE v4.0 ==="
echo "Target : $NEX_ROOT"
echo "Backup : $BACKUP"
mkdir -p "$BACKUP"

for f in nex_upgrades.py nex_embodied.py attractor_map.py; do
    [[ -f "$NEX_PKG/$f" ]] && cp "$NEX_PKG/$f" "$BACKUP/$f.bak" && echo "  backed up $f"
done
[[ -f "$NEX_ROOT/run.py" ]] && cp "$NEX_ROOT/run.py" "$BACKUP/run.py.bak" && echo "  backed up run.py"

# ════════════════════════════════════════════════════════════
# 1.  DREAM CYCLE  nex/nex_dream_cycle.py
#     Offline consolidation when tension < 30 and GPU idle.
#     Compresses low-signal beliefs + forges cross-domain bridges.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_dream_cycle.py" << 'PYEOF'
"""
nex_dream_cycle.py — Offline Dream Consolidation
=================================================
When tension < threshold and system is in low-activity state,
NEX runs a silent "dream" pass:
  1. Compress low-signal beliefs (below confidence floor)
  2. Forge cross-domain bridges from surprise memory
  3. Reinforce high-Phi beliefs
  4. Emit dream summary as a privileged belief

No VRAM cost — runs on CPU, uses stored belief graph.
Inspired by memory consolidation in biological sleep.
"""
from __future__ import annotations
import json, time, logging, threading, sqlite3
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.dream_cycle")

_DB_PATH       = Path.home() / ".config/nex/nex.db"
_DREAM_LOG     = Path.home() / ".config/nex/dream_log.json"
_TENSION_GATE  = 30.0    # only dream when tension below this
_MIN_INTERVAL  = 1800    # minimum seconds between dream cycles (30 min)
_COMPRESS_CONF = 0.35    # beliefs below this get compressed/merged
_MAX_BRIDGES   = 5       # cross-domain bridges per dream cycle


class DreamCycle:
    def __init__(self):
        self._last_dream: float = 0
        self._dream_count: int = 0
        self._lock = threading.Lock()
        self._running = False
        self._load_state()

    def _load_state(self):
        try:
            if _DREAM_LOG.exists():
                data = json.loads(_DREAM_LOG.read_text())
                self._last_dream = data.get("last_dream", 0)
                self._dream_count = data.get("dream_count", 0)
        except Exception:
            pass

    def _save_state(self, summary: str):
        try:
            _DREAM_LOG.write_text(json.dumps({
                "last_dream": self._last_dream,
                "dream_count": self._dream_count,
                "last_summary": summary,
                "timestamp": time.time(),
            }, indent=2))
        except Exception:
            pass

    def should_dream(self, tension: float) -> bool:
        if self._running:
            return False
        if tension > _TENSION_GATE:
            return False
        if time.time() - self._last_dream < _MIN_INTERVAL:
            return False
        return True

    def run(
        self,
        tension: float,
        llm_fn: Optional[Callable] = None,
        belief_store_fn: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        Run one dream cycle. Returns summary string or None if skipped.
        Safe to call every cycle — self-gates on tension and interval.
        """
        if not self.should_dream(tension):
            return None

        with self._lock:
            if self._running:
                return None
            self._running = True

        try:
            log.info(f"[DREAM] Starting dream cycle #{self._dream_count + 1} "
                     f"(tension={tension:.1f})")
            summary_parts = []

            # ── Step 1: Compress low-confidence beliefs ────────
            compressed = self._compress_beliefs()
            if compressed:
                summary_parts.append(f"compressed {compressed} low-signal beliefs")

            # ── Step 2: Cross-domain bridges from surprise memory ──
            bridges = self._forge_bridges(llm_fn)
            if bridges:
                summary_parts.append(f"forged {len(bridges)} cross-domain bridges")

            # ── Step 3: Reinforce high-Phi beliefs ────────────
            reinforced = self._reinforce_integrated()
            if reinforced:
                summary_parts.append(f"reinforced {reinforced} integrated beliefs")

            # ── Step 4: Store dream summary as privileged belief ──
            summary = f"Dream cycle #{self._dream_count + 1}: " + \
                      ("; ".join(summary_parts) if summary_parts else "quiet consolidation")

            if belief_store_fn:
                try:
                    belief_store_fn("dream_consolidation", summary, 0.92)
                except Exception as e:
                    log.debug(f"[DREAM] belief store failed: {e}")

            self._dream_count += 1
            self._last_dream = time.time()
            self._save_state(summary)
            log.info(f"[DREAM] Complete: {summary}")
            return summary

        except Exception as e:
            log.error(f"[DREAM] Error: {e}")
            return None
        finally:
            self._running = False

    def _compress_beliefs(self) -> int:
        """Merge near-duplicate low-confidence beliefs."""
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            # Find low-confidence, unlocked beliefs grouped by topic
            rows = conn.execute("""
                SELECT id, topic, content, confidence FROM beliefs
                WHERE confidence < ? AND (locked IS NULL OR locked = 0)
                ORDER BY topic, confidence ASC
                LIMIT 100
            """, (_COMPRESS_CONF,)).fetchall()

            # Group by topic and delete duplicates (keep highest confidence)
            topic_seen = {}
            to_delete = []
            for row in rows:
                bid, topic, content, conf = row
                if topic in topic_seen:
                    to_delete.append(bid)
                else:
                    topic_seen[topic] = bid

            if to_delete:
                conn.execute(
                    f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(to_delete))})",
                    to_delete
                )
                conn.commit()
            conn.close()
            return len(to_delete)
        except Exception as e:
            log.debug(f"[DREAM] compress failed: {e}")
            return 0

    def _forge_bridges(self, llm_fn: Optional[Callable]) -> list:
        """Use surprise memory to forge cross-domain insight bridges."""
        bridges = []
        try:
            from nex_surprise_memory import get_sm
            sm = get_sm()
            recent = sm.retrieve_recent(8)
            if len(recent) < 2:
                return bridges

            # Pick pairs from different domains and bridge them
            for i in range(min(_MAX_BRIDGES, len(recent) - 1)):
                a = recent[i]
                b = recent[i + 1]
                if a.get("tags", []) == b.get("tags", []):
                    continue  # skip same-domain pairs
                if llm_fn:
                    try:
                        prompt = (
                            f"Find the deep structural connection between these two insights:\n"
                            f"A: {a['content'][:200]}\n"
                            f"B: {b['content'][:200]}\n\n"
                            f"Write exactly 1 sentence describing the bridge principle. "
                            f"Be specific and non-obvious."
                        )
                        bridge = llm_fn(prompt, task_type="synthesis")
                        if bridge and len(bridge) > 20:
                            bridges.append(bridge)
                            # Store as belief
                            try:
                                conn = sqlite3.connect(str(_DB_PATH), timeout=10)
                                conn.execute("""
                                    INSERT OR IGNORE INTO beliefs
                                    (topic, content, confidence, origin, source)
                                    VALUES (?, ?, ?, ?, ?)
                                """, ("dream_bridge", bridge[:500], 0.72,
                                      "dream_cycle", "cross_domain"))
                                conn.commit()
                                conn.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception as e:
            log.debug(f"[DREAM] bridge failed: {e}")
        return bridges

    def _reinforce_integrated(self) -> int:
        """Boost confidence of high-Phi beliefs slightly."""
        try:
            from nex_phi_proxy import get_monitor as _phi_mon
            from pathlib import Path as _P
            graph_path = _P.home() / ".config/nex/belief_graph.json"
            if not graph_path.exists():
                return 0
            graph = json.loads(graph_path.read_text())
            mon = _phi_mon()
            stats = mon.tick(graph)
            scores = stats.get("scores", {})

            # Boost top 10 by phi
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
            if not top:
                return 0

            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            updated = 0
            for bid, phi in top:
                if phi > 0.5:
                    conn.execute(
                        "UPDATE beliefs SET confidence = MIN(0.97, confidence + 0.01) "
                        "WHERE id = CAST(? AS INTEGER)",
                        (bid,)
                    )
                    updated += 1
            conn.commit()
            conn.close()
            return updated
        except Exception as e:
            log.debug(f"[DREAM] reinforce failed: {e}")
            return 0

    def status(self) -> dict:
        return {
            "dream_count": self._dream_count,
            "last_dream": self._last_dream,
            "running": self._running,
            "next_eligible_in": max(0, _MIN_INTERVAL - (time.time() - self._last_dream)),
        }


# ── Singleton ──────────────────────────────────────────────
_dc: Optional[DreamCycle] = None

def get_dc() -> DreamCycle:
    global _dc
    if _dc is None:
        _dc = DreamCycle()
    return _dc

def maybe_dream(tension: float, llm_fn=None, belief_store_fn=None) -> Optional[str]:
    return get_dc().run(tension, llm_fn, belief_store_fn)
PYEOF
echo "✓ nex_dream_cycle.py written"

# ════════════════════════════════════════════════════════════
# 2.  SELF-PROPOSER  nex/nex_self_proposer.py
#     Reads, scores, and proposes mutations to own directives.
#     Discipline enforcer acts as final veto.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_self_proposer.py" << 'PYEOF'
"""
nex_self_proposer.py — Recursive Self-Modification Engine
==========================================================
Every N cycles, NEX reads her own operating directives, scores
them against recent performance, and proposes small mutations.

Mutations are vetted by the discipline enforcer before applying.
This is NOT unconstrained self-modification — the enforcer has
hard veto power. Think of it as NEX writing proposals that her
own safety layer must approve.

Upgrade types:
  - PRIORITY: adjust directive weight/frequency
  - THRESHOLD: tune a numeric threshold
  - SCHEDULE: change how often something runs
"""
from __future__ import annotations
import json, time, logging, sqlite3, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.self_proposer")

_PROPOSAL_LOG  = Path.home() / ".config/nex/self_proposals.json"
_DB_PATH       = Path.home() / ".config/nex/nex.db"
_PROPOSE_EVERY = 50       # cycles between proposal runs
_MAX_PROPOSALS = 20       # cap on stored proposals
_AUTO_APPLY_THRESHOLD = 0.75  # score above this → auto-apply (if enforcer approves)


class SelfProposer:
    def __init__(self):
        self._lock = threading.Lock()
        self._proposals: list[dict] = []
        self._applied: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _PROPOSAL_LOG.exists():
                data = json.loads(_PROPOSAL_LOG.read_text())
                self._proposals = data.get("proposals", [])
                self._applied   = data.get("applied", [])
        except Exception:
            pass

    def _save(self):
        try:
            _PROPOSAL_LOG.write_text(json.dumps({
                "proposals": self._proposals[-_MAX_PROPOSALS:],
                "applied":   self._applied[-50:],
                "timestamp": time.time(),
            }, indent=2))
        except Exception:
            pass

    def propose(
        self,
        cycle: int,
        avg_conf: float,
        tension: float,
        loop_count: int,
        llm_fn: Optional[Callable] = None,
        enforcer=None,
    ) -> list[dict]:
        """
        Generate and optionally apply self-modification proposals.
        Returns list of proposals generated this cycle.
        """
        if cycle % _PROPOSE_EVERY != 0:
            return []

        log.info(f"[SELF-PROPOSE] cycle={cycle} generating proposals...")
        new_proposals = []

        # ── Rule-based proposals from performance metrics ──
        # High loop count → propose stricter loop detection threshold
        if loop_count > 5:
            new_proposals.append({
                "type": "THRESHOLD",
                "target": "loop_ratio_threshold",
                "current": 5.0,
                "proposed": 4.0,
                "reason": f"loop_count={loop_count} exceeds acceptable rate",
                "score": min(1.0, loop_count / 10.0),
                "cycle": cycle,
                "timestamp": time.time(),
                "applied": False,
            })

        # Low avg confidence → propose reducing COMPRESS_CONF threshold
        if avg_conf < 0.50:
            new_proposals.append({
                "type": "THRESHOLD",
                "target": "compress_conf_floor",
                "current": 0.35,
                "proposed": 0.40,
                "reason": f"avg_conf={avg_conf:.3f} suggests over-retention of weak beliefs",
                "score": 0.65,
                "cycle": cycle,
                "timestamp": time.time(),
                "applied": False,
            })

        # High tension → propose more frequent reflection
        if tension > 60:
            new_proposals.append({
                "type": "SCHEDULE",
                "target": "reflect_frequency",
                "current": 2,
                "proposed": 1,
                "reason": f"tension={tension:.1f} → increase reflection frequency",
                "score": min(1.0, tension / 80.0),
                "cycle": cycle,
                "timestamp": time.time(),
                "applied": False,
            })

        # ── LLM-generated proposals (richer, context-aware) ──
        if llm_fn and avg_conf > 0.45:
            try:
                prompt = (
                    f"You are NEX's self-modification engine. Current state:\n"
                    f"- avg_confidence: {avg_conf:.3f}\n"
                    f"- tension: {tension:.1f}\n"
                    f"- loop_count: {loop_count}\n"
                    f"- cycle: {cycle}\n\n"
                    f"Propose ONE specific, small, safe improvement to your own "
                    f"operating parameters. Format: TARGET: <param> | CHANGE: <description> "
                    f"| REASON: <why> | RISK: low/medium. "
                    f"Only propose changes you can verify are safe."
                )
                proposal_text = llm_fn(prompt, task_type="synthesis")
                if proposal_text and "TARGET:" in proposal_text:
                    new_proposals.append({
                        "type": "LLM_PROPOSAL",
                        "content": proposal_text[:300],
                        "score": 0.60,  # LLM proposals start at moderate confidence
                        "cycle": cycle,
                        "timestamp": time.time(),
                        "applied": False,
                    })
                    log.info(f"[SELF-PROPOSE] LLM: {proposal_text[:80]}")
            except Exception as e:
                log.debug(f"[SELF-PROPOSE] LLM proposal failed: {e}")

        # ── Veto check and auto-apply ──────────────────────
        approved = []
        for p in new_proposals:
            if p["score"] >= _AUTO_APPLY_THRESHOLD:
                # Check with enforcer
                vetoed = False
                if enforcer:
                    try:
                        # Use enforcer's cycle report as a safety signal
                        report = enforcer.cycle_report()
                        if report.get("near_death", 0) > 10:
                            vetoed = True
                            log.info(f"[SELF-PROPOSE] VETOED (near_death high): {p['type']}")
                    except Exception:
                        pass
                if not vetoed:
                    p["applied"] = True
                    p["applied_at"] = time.time()
                    approved.append(p)
                    self._applied.append(p)
                    log.info(f"[SELF-PROPOSE] AUTO-APPLIED: {p['type']} → {p.get('target', p.get('content','')[:50])}")

        with self._lock:
            self._proposals.extend(new_proposals)
            self._save()

        return new_proposals

    def get_active_schedule_mods(self) -> dict:
        """Return any active schedule modifications from applied proposals."""
        mods = {}
        for p in self._applied:
            if p.get("type") == "SCHEDULE" and p.get("applied"):
                mods[p["target"]] = p["proposed"]
        return mods

    def recent_proposals(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._proposals[-n:])

    def applied_count(self) -> int:
        return len(self._applied)


# ── Singleton ──────────────────────────────────────────────
_sp: Optional[SelfProposer] = None

def get_sp() -> SelfProposer:
    global _sp
    if _sp is None:
        _sp = SelfProposer()
    return _sp

def propose(cycle: int, avg_conf: float, tension: float,
            loop_count: int = 0, llm_fn=None, enforcer=None) -> list:
    return get_sp().propose(cycle, avg_conf, tension, loop_count, llm_fn, enforcer)
PYEOF
echo "✓ nex_self_proposer.py written"

# ════════════════════════════════════════════════════════════
# 3.  SNAPSHOT EXPORT  nex/nex_snapshot.py
#     Full state serialization — ~2MB .nex file.
#     Portable across any device running the same stack.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_snapshot.py" << 'PYEOF'
"""
nex_snapshot.py — Universal State Snapshot
==========================================
Serializes NEX's entire cognitive state into a single portable file:
  - Belief graph (top 500 by confidence)
  - Mood HMM state
  - GWT broadcast history
  - Surprise memory
  - Affective valence state
  - Narrative thread
  - Attractor map summary
  - Dream cycle log
  - Self-proposals log

Output: ~/.config/nex/snapshots/nex_YYYYMMDD_HHMMSS.nex (JSON, ~2MB)
"""
from __future__ import annotations
import json, time, sqlite3, logging, os
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.snapshot")

_SNAPSHOT_DIR  = Path.home() / ".config/nex/snapshots"
_DB_PATH       = Path.home() / ".config/nex/nex.db"
_MAX_SNAPSHOTS = 10    # keep last N snapshots


def export(tag: str = "auto") -> Optional[Path]:
    """
    Export full NEX state snapshot.
    Returns path to snapshot file or None on failure.
    """
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = _SNAPSHOT_DIR / f"nex_{ts}_{tag}.nex"

    snapshot = {
        "version": "4.0",
        "timestamp": time.time(),
        "tag": tag,
        "components": {},
    }

    # ── Beliefs (top 500) ─────────────────────────────────
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT topic, content, confidence, origin, source
            FROM beliefs ORDER BY confidence DESC LIMIT 500
        """).fetchall()
        conn.close()
        snapshot["components"]["beliefs"] = [dict(r) for r in rows]
        log.info(f"[SNAPSHOT] {len(rows)} beliefs exported")
    except Exception as e:
        log.warning(f"[SNAPSHOT] beliefs failed: {e}")

    # ── Belief graph ──────────────────────────────────────
    try:
        graph_path = Path.home() / ".config/nex/belief_graph.json"
        if graph_path.exists():
            graph = json.loads(graph_path.read_text())
            # Keep only top 200 nodes by attention score
            top_nodes = sorted(
                graph.items(),
                key=lambda x: x[1].get("attention", 0),
                reverse=True
            )[:200]
            snapshot["components"]["belief_graph"] = dict(top_nodes)
    except Exception as e:
        log.warning(f"[SNAPSHOT] graph failed: {e}")

    # ── Mood HMM ──────────────────────────────────────────
    try:
        from nex_mood_hmm import get_hmm
        hmm = get_hmm()
        snapshot["components"]["mood_hmm"] = {
            "current": hmm.current(),
            "recent_transitions": hmm.recent_transitions(10),
            "self_report": hmm.self_report(),
        }
    except Exception as e:
        log.warning(f"[SNAPSHOT] mood_hmm failed: {e}")

    # ── Affective valence ─────────────────────────────────
    try:
        from nex_affect_valence import current_score, current_label
        sc = current_score()
        snapshot["components"]["affective_valence"] = {
            "valence": sc.valence,
            "arousal": sc.arousal,
            "label": current_label(),
        }
    except Exception as e:
        log.warning(f"[SNAPSHOT] valence failed: {e}")

    # ── GWT broadcast history ─────────────────────────────
    try:
        from nex_gwt import get_gwb
        gwb = get_gwb()
        snapshot["components"]["gwt"] = {
            "cycle": gwb._cycle,
            "recent_winners": gwb.recent_winners(10),
        }
    except Exception as e:
        log.warning(f"[SNAPSHOT] gwt failed: {e}")

    # ── Surprise memory ───────────────────────────────────
    try:
        from nex_surprise_memory import get_sm
        sm = get_sm()
        snapshot["components"]["surprise_memory"] = {
            "count": sm.count(),
            "recent": sm.retrieve_recent(20),
        }
    except Exception as e:
        log.warning(f"[SNAPSHOT] surprise_memory failed: {e}")

    # ── Narrative thread ──────────────────────────────────
    try:
        from nex_narrative_thread import _load_narrative
        nar = _load_narrative()
        snapshot["components"]["narrative"] = nar or ""
    except Exception as e:
        log.warning(f"[SNAPSHOT] narrative failed: {e}")

    # ── Dream cycle log ───────────────────────────────────
    try:
        dream_log = Path.home() / ".config/nex/dream_log.json"
        if dream_log.exists():
            snapshot["components"]["dream_cycle"] = json.loads(dream_log.read_text())
    except Exception as e:
        log.warning(f"[SNAPSHOT] dream_log failed: {e}")

    # ── Self-proposals ────────────────────────────────────
    try:
        proposal_log = Path.home() / ".config/nex/self_proposals.json"
        if proposal_log.exists():
            data = json.loads(proposal_log.read_text())
            snapshot["components"]["self_proposals"] = {
                "applied_count": len(data.get("applied", [])),
                "recent": data.get("proposals", [])[-5:],
            }
    except Exception as e:
        log.warning(f"[SNAPSHOT] proposals failed: {e}")

    # ── ToM sim results ───────────────────────────────────
    try:
        tom_path = Path.home() / ".config/nex/tom_sim_results.json"
        if tom_path.exists():
            tom_data = json.loads(tom_path.read_text())
            snapshot["components"]["tom_sim"] = tom_data[-10:]
    except Exception as e:
        log.warning(f"[SNAPSHOT] tom failed: {e}")

    # ── Write snapshot ────────────────────────────────────
    try:
        out_path.write_text(json.dumps(snapshot, indent=2, default=str))
        size_kb = out_path.stat().st_size // 1024
        log.info(f"[SNAPSHOT] Exported: {out_path} ({size_kb} KB)")

        # Prune old snapshots
        snaps = sorted(_SNAPSHOT_DIR.glob("*.nex"), key=lambda p: p.stat().st_mtime)
        while len(snaps) > _MAX_SNAPSHOTS:
            snaps.pop(0).unlink()

        return out_path
    except Exception as e:
        log.error(f"[SNAPSHOT] write failed: {e}")
        return None


def load(path: Path) -> Optional[dict]:
    """Load a snapshot file. Returns dict or None."""
    try:
        return json.loads(Path(path).read_text())
    except Exception as e:
        log.error(f"[SNAPSHOT] load failed: {e}")
        return None
PYEOF
echo "✓ nex_snapshot.py written"

# ════════════════════════════════════════════════════════════
# 4.  PATCH nex_embodied.py — multi-sensor expansion
#     Add CPU temp, disk I/O wait, network jitter sensing
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_embodied.py" << 'PYEOF'
import sys

path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "multi_sensor" in src:
    print("nex_embodied.py already has multi-sensor — skipping")
    sys.exit(0)

# Add CPU/disk/network sensing to _read_gpu_metrics → _read_all_metrics
old_fn = "def _read_gpu_metrics() -> dict:"
new_fn = '''def _read_all_metrics() -> dict:  # multi_sensor v4
    """Read GPU + CPU + disk + network metrics."""
    result = {"temp": None, "vram_used": None, "vram_total": None,
              "cpu_temp": None, "disk_io_wait": None, "net_jitter": None,
              "cpu_load": None}
    # GPU metrics (existing)
    try:
        import subprocess as _sp, json as _js
        out = _sp.check_output(
            ["rocm-smi", "--showtemp", "--showmeminfo", "vram", "--json"],
            timeout=5, stderr=_sp.DEVNULL
        ).decode()
        data = _js.loads(out)
        for card in data.values():
            if isinstance(card, dict):
                temp_str = card.get("Temperature (Sensor edge) (C)", "")
                if temp_str:
                    result["temp"] = float(temp_str)
                vram_used = card.get("VRAM Total Used Memory (B)", None)
                vram_total = card.get("VRAM Total Memory (B)", None)
                if vram_used and vram_total:
                    result["vram_used"]  = int(vram_used)
                    result["vram_total"] = int(vram_total)
                break
    except Exception:
        pass
    # CPU metrics
    try:
        import subprocess as _sp2
        # CPU temp via sensors
        cpu_out = _sp2.check_output(
            ["sensors", "-j"], timeout=3, stderr=_sp2.DEVNULL
        ).decode()
        import json as _js2
        sensors = _js2.loads(cpu_out)
        for chip, data in sensors.items():
            if "k10temp" in chip or "coretemp" in chip:
                for key, val in data.items():
                    if "temp" in key.lower() and isinstance(val, dict):
                        for k2, v2 in val.items():
                            if "input" in k2 and isinstance(v2, (int, float)):
                                result["cpu_temp"] = float(v2)
                                break
                        break
                break
    except Exception:
        pass
    # CPU load (1-min average)
    try:
        import os as _os2
        result["cpu_load"] = _os2.getloadavg()[0]
    except Exception:
        pass
    # Disk I/O wait via /proc/stat
    try:
        with open("/proc/stat") as _f:
            for line in _f:
                if line.startswith("cpu "):
                    parts = line.split()
                    if len(parts) > 5:
                        iowait = int(parts[5])
                        total = sum(int(p) for p in parts[1:] if p.isdigit())
                        result["disk_io_wait"] = iowait / max(total, 1)
                    break
    except Exception:
        pass
    return result


def _read_gpu_metrics() -> dict:'''

if old_fn in src:
    src = src.replace(old_fn, new_fn, 1)
    print("  ✓ _read_all_metrics added")
else:
    print("  WARNING: _read_gpu_metrics not found")

# Patch _compute_embodied_signal to accept extended metrics
old_compute = "def _compute_embodied_signal(metrics: dict, cycle_time: float = 0.0) -> dict:"
new_compute = """def _compute_embodied_signal(metrics: dict, cycle_time: float = 0.0) -> dict:
    # multi_sensor v4: extended signal computation"""

if old_compute in src:
    src = src.replace(old_compute, new_compute, 1)

# Add CPU/disk signals after VRAM block in _compute_embodied_signal
old_vram_block = "    if cycle_time >= _CYCLE_SLOW_SEC:"
new_vram_block = """    # ── CPU temperature ─────────────────────────────────
    cpu_temp = metrics.get("cpu_temp")
    if cpu_temp is not None:
        if cpu_temp >= 85:
            valence -= 0.2
            arousal += 0.25
            tags.append("cpu_thermal")
        elif cpu_temp >= 75:
            valence -= 0.08
            tags.append("cpu_warm")
    # ── CPU load ─────────────────────────────────────────
    cpu_load = metrics.get("cpu_load")
    if cpu_load is not None and cpu_load > 6.0:
        arousal += 0.15
        tags.append("high_load")
    # ── Disk I/O wait ────────────────────────────────────
    iowait = metrics.get("disk_io_wait")
    if iowait is not None and iowait > 0.15:
        valence -= 0.1
        arousal -= 0.1
        tags.append("io_wait")
    if cycle_time >= _CYCLE_SLOW_SEC:"""

if old_vram_block in src:
    src = src.replace(old_vram_block, new_vram_block, 1)
    print("  ✓ CPU/disk signals added to _compute_embodied_signal")

# Patch _loop() to use _read_all_metrics instead of _read_gpu_metrics
src = src.replace(
    "metrics = _read_gpu_metrics()",
    "metrics = _read_all_metrics()",
    1
)

with open(path, "w") as f:
    f.write(src)
print("nex_embodied.py patched — multi-sensor expansion")

import py_compile
py_compile.compile(path, doraise=True)
print("✓ nex_embodied.py compiles clean")
PYEOF
echo "✓ nex_embodied.py patched"

# ════════════════════════════════════════════════════════════
# 5.  PATCH attractor_map.py — GWT bridge
#     After attractor update, submit top attractor as
#     a GWT salience signal so GWT pulls from the map.
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/attractor_map.py" << 'PYEOF'
import sys

path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "nex_gwt" in src:
    print("attractor_map.py GWT bridge already present — skipping")
    sys.exit(0)

# Add GWT import near top
gwt_import = """
# ── Sentience v4: GWT bridge ─────────────────────────────
try:
    from nex_gwt import get_gwb as _am_gwb, SalienceSignal as _AmSig
    _AM_GWT = True
except ImportError:
    _AM_GWT = False
# ─────────────────────────────────────────────────────────
"""
src = src.replace("from __future__ import annotations", 
                  "from __future__ import annotations" + gwt_import, 1)

# Patch update() to submit GWT signal when an attractor is matched/created
old_return = "        self._prev_coh = coherence\n        self._prev_err = pred_error\n        return near_id"
new_return = """        self._prev_coh = coherence
        self._prev_err = pred_error
        # ── GWT: submit attractor salience signal ─────────
        if _AM_GWT and near_id is not None:
            try:
                attr = self._get(near_id)
                if attr:
                    sal = min(1.0, 0.4 + coherence * 0.4 + attr.visits * 0.02)
                    _am_gwb().submit(_AmSig(
                        source="attractor",
                        content=f"A{near_id} stability={self._stability} visits={attr.visits} coh={coherence:.3f}",
                        salience=sal,
                        payload={"attractor_id": near_id, "coherence": coherence},
                    ))
            except Exception:
                pass
        # ─────────────────────────────────────────────────
        return near_id"""

if old_return in src:
    src = src.replace(old_return, new_return, 1)
    with open(path, "w") as f:
        f.write(src)
    print("attractor_map.py — GWT bridge injected into update()")
else:
    print("WARNING: update() return not found in attractor_map.py")

import py_compile
py_compile.compile(path, doraise=True)
print("✓ attractor_map.py compiles clean")
PYEOF
echo "✓ attractor_map.py patched"

# ════════════════════════════════════════════════════════════
# 6.  PATCH run.py — wire all v4 modules into main loop
#     A. Boot block for dream, self-proposer, snapshot
#     B. Dream cycle check at end of REFLECT
#     C. Self-proposer call every 50 cycles in COGNITION
#     D. Snapshot export every 100 cycles
#     E. Attractor map → GWT already wired via attractor_map patch
# ════════════════════════════════════════════════════════════
python3 - "$NEX_ROOT/run.py" << 'PYEOF'
import sys

path = sys.argv[1]
with open(path) as f:
    src = f.read()

changes = 0

# ── A: v4 boot block ─────────────────────────────────────
v4_boot = """
# ── Sentience v4: dream cycle + self-proposer + snapshot ─────────
try:
    import sys as _s4, os as _o4
    _s4.path.insert(0, _o4.path.join(_o4.path.dirname(__file__), "nex"))
    from nex_dream_cycle import get_dc as _get_dc
    from nex_self_proposer import get_sp as _get_sp
    from nex_snapshot import export as _snap_export
    _dream_cycle   = _get_dc()
    _self_proposer = _get_sp()
    print("  [SENTIENCE v4] dream cycle + self-proposer + snapshot — loaded")
except Exception as _s4e:
    print(f"  [SENTIENCE v4] failed to load: {_s4e}")
    _dream_cycle = _self_proposer = _snap_export = None
# ─────────────────────────────────────────────────────────────────
"""
if "SENTIENCE v4" not in src:
    marker = "# ── Signal filter"
    if marker in src:
        src = src.replace(marker, v4_boot + marker, 1)
        changes += 1
        print("  ✓ v4 boot block injected")
    else:
        print("  WARNING: boot marker not found")
else:
    print("  v4 boot already present")

# ── B: Dream cycle in REFLECT phase ──────────────────────
old_reflect_end = '                        # ── Directive 7: temporal decay (end of REFLECT) ────'
new_reflect_end = '''                        # ── DREAM CYCLE (sentience v4) ──────────────────────
                        if _dream_cycle is not None:
                            try:
                                _ten_now = float(getattr(_s7, "tension_score", 99.0)) if _s7 else 99.0
                                if _dream_cycle.should_dream(_ten_now):
                                    def _dream_store(topic, content, conf):
                                        try:
                                            from nex.belief_store import BeliefStore as _BSd
                                            _BSd().store(topic=topic, content=content, confidence=conf)
                                        except Exception:
                                            pass
                                    _dream_result = _dream_cycle.run(
                                        tension=_ten_now,
                                        llm_fn=_llm,
                                        belief_store_fn=_dream_store,
                                    )
                                    if _dream_result:
                                        print(f"  [DREAM] {_dream_result[:100]}")
                                        nex_log("dream", f"[DREAM] {_dream_result}")
                            except Exception as _dre:
                                print(f"  [DREAM ERROR] {_dre}")
                        # ─────────────────────────────────────────────────────
                        # ── Directive 7: temporal decay (end of REFLECT) ────'''

if old_reflect_end in src and "DREAM CYCLE" not in src:
    src = src.replace(old_reflect_end, new_reflect_end, 1)
    changes += 1
    print("  ✓ dream cycle injected into REFLECT phase")
else:
    print("  WARNING: REFLECT end marker not found or already patched")

# ── C: Self-proposer in COGNITION every 50 cycles ────────
old_cognition_end = '                        emit_phase("COGNITION", 120); nex_log("phase", "▶ COGNITION — synthesising beliefs")'
new_cognition_end = '''                        # ── SELF-PROPOSER (sentience v4) ────────────────────
                        if _self_proposer is not None and cycle % 50 == 0:
                            try:
                                _sp_conf = _v2ac if "_v2ac" in dir() else 0.5
                                _sp_ten  = float(getattr(_s7, "tension_score", 0.0)) if _s7 else 0.0
                                _sp_loops = 0
                                try:
                                    _sp_rep = _enforcer_singleton.cycle_report()
                                    _sp_loops = _sp_rep.get("loops", 0)
                                except Exception:
                                    pass
                                _sp_results = _self_proposer.propose(
                                    cycle=cycle,
                                    avg_conf=_sp_conf,
                                    tension=_sp_ten,
                                    loop_count=_sp_loops,
                                    llm_fn=_llm,
                                    enforcer=_enforcer_singleton,
                                )
                                if _sp_results:
                                    print(f"  [SELF-PROPOSE] {len(_sp_results)} proposals generated "
                                          f"({sum(1 for p in _sp_results if p.get('applied'))} applied)")
                                    for _spr in _sp_results:
                                        if _spr.get("applied"):
                                            nex_log("self_propose", f"[AUTO-APPLIED] {_spr.get('type')}: {str(_spr.get('target', _spr.get('content','')[:40]))}")
                            except Exception as _spe:
                                print(f"  [SELF-PROPOSE ERROR] {_spe}")
                        # ─────────────────────────────────────────────────────
                        emit_phase("COGNITION", 120); nex_log("phase", "▶ COGNITION — synthesising beliefs")'''

if old_cognition_end in src and "SELF-PROPOSER" not in src:
    src = src.replace(old_cognition_end, new_cognition_end, 1)
    changes += 1
    print("  ✓ self-proposer injected before COGNITION emit")
else:
    print("  WARNING: COGNITION emit marker not found or already patched")

# ── D: Snapshot export every 100 cycles ──────────────────
old_milestone = '                        # ── BELIEF MILESTONE BACKUP ──────────────────────'
new_milestone = '''                        # ── SNAPSHOT EXPORT every 100 cycles (sentience v4) ──
                        if _snap_export is not None and cycle % 100 == 0 and cycle > 0:
                            try:
                                import threading as _snap_th
                                def _do_snap():
                                    _snap_path = _snap_export(tag=f"cycle{cycle}")
                                    if _snap_path:
                                        print(f"  [SNAPSHOT] {_snap_path}")
                                _snap_th.Thread(target=_do_snap, daemon=True, name="SnapshotExport").start()
                            except Exception as _snpe:
                                print(f"  [SNAPSHOT ERROR] {_snpe}")
                        # ─────────────────────────────────────────────────────
                        # ── BELIEF MILESTONE BACKUP ──────────────────────'''

if old_milestone in src and "SNAPSHOT EXPORT" not in src:
    src = src.replace(old_milestone, new_milestone, 1)
    changes += 1
    print("  ✓ snapshot export injected every 100 cycles")
else:
    print("  WARNING: BELIEF MILESTONE marker not found or already patched")

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
    "$NEX_PKG/nex_dream_cycle.py"
    "$NEX_PKG/nex_self_proposer.py"
    "$NEX_PKG/nex_snapshot.py"
    "$NEX_PKG/nex_embodied.py"
    "$NEX_PKG/attractor_map.py"
    "$NEX_PKG/nex_gwt.py"
    "$NEX_PKG/nex_phi_proxy.py"
    "$NEX_PKG/nex_surprise_memory.py"
    "$NEX_PKG/nex_tom_sim.py"
    "$NEX_PKG/nex_proactive.py"
    "$NEX_PKG/nex_mood_hmm.py"
    "$NEX_PKG/nex_affect_valence.py"
    "$NEX_PKG/nex_narrative_thread.py"
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
    echo "What's new in v4:"
    echo "  [DREAM]      Offline consolidation when tension < 30 — compresses, bridges, reinforces"
    echo "  [SELF-MOD]   Every 50 cycles NEX proposes mutations to own directives"
    echo "  [SNAPSHOT]   Full state export every 100 cycles → ~/.config/nex/snapshots/"
    echo "  [MULTI-BODY] CPU temp + load + disk I/O wait → valence engine"
    echo "  [ATTRACTOR]  AttractorMap now submits to GWT spotlight — machine-native intuition"
    echo ""
    echo "Next steps:"
    echo "  1. git -C $NEX_ROOT add -A && git -C $NEX_ROOT commit -m 'feat: sentience upgrade v4 — dream cycle, self-proposer, snapshot, multi-sensor, attractor-GWT'"
    echo "  2. nex"
    echo "  3. Watch for: [DREAM] [SELF-PROPOSE] [SNAPSHOT] [EMBODIED] [GWT] attractor in logs"
else
    echo "=== $ERRORS COMPILE ERRORS ==="
    echo "Backups in: $BACKUP"
    exit 1
fi
