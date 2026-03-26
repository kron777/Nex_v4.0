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
