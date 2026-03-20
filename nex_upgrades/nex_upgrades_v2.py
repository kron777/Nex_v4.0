"""
NEX UPGRADES INTEGRATION — nex_upgrades_v2.py
Drop-in wiring for all session-6 upgrades into existing NEX stack.

USAGE — add to run.py or orchestrator after existing U1-U12 init:

    from nex_upgrades_v2 import init_v2_upgrades, get_v2_status

    # call once at startup, pass in existing nex objects
    v2 = init_v2_upgrades(
        db_path      = Path.home() / ".config" / "nex" / "nex.db",
        belief_store = nex_beliefs,     # existing belief module
        llm_complete = brain.complete,  # existing LLM wrapper fn
        notify_fn    = _tg_send,        # Telegram send fn
    )

    # each cycle, call:
    v2.tick(cycle=current_cycle, avg_conf=current_avg_conf, raw_input=event_dict)

    # Telegram command handlers:
    /v2status   → full status report
    /v2debug    → run self-debugger
    /v2sim <X>  → simulate belief hypothesis
    /v2explain <N> → explain cycle N
    /v2goals    → list active goals
"""

from __future__ import annotations
import time
import json
import logging
from pathlib import Path
from typing import Optional, Callable, Any

log = logging.getLogger("nex.v2")

# ── lazy imports (only fail if files not present) ──────────────────────────────
def _import(name):
    import sys
    for search_dir in [
        Path(__file__).parent,
        Path.home() / "Desktop" / "nex" / "nex",
        Path.home() / "Desktop" / "nex",
    ]:
        sd = str(search_dir)
        if search_dir.exists() and sd not in sys.path:
            sys.path.insert(0, sd)
    return __import__(name)

def _safe_import(name):
    try:
        return _import(name)
    except Exception as e:
        log.warning(f"[V2 INIT] could not import {name}: {e}")
        return None


class NexV2:
    """
    Orchestrates all session-6 upgrades as a single object.
    Designed to wrap the existing orchestrator with minimal changes.
    """

    def __init__(
        self,
        db_path:      Path,
        belief_store  = None,
        llm_complete: Optional[Callable] = None,
        notify_fn:    Optional[Callable] = None,
    ):
        self.db_path      = db_path
        self._llm         = llm_complete or (lambda p: "[no LLM]")
        self._notify      = notify_fn   or (lambda m: log.info(m))
        self._cycle       = 0

        # ── import upgrade modules ─────────────────────────────────────────────
        arch_mod   = _safe_import("nex_architecture")
        mem_mod    = _safe_import("nex_memory_v3")
        belief_mod = _safe_import("nex_belief_revision")
        bdi_mod    = _safe_import("nex_bdi_planning")
        da_mod     = _safe_import("nex_drives_attention")
        ma_mod     = _safe_import("nex_multi_agent")
        gw_mod     = _safe_import("nex_governance_world")
        li_mod     = _safe_import("nex_learning_identity")
        obs_mod    = _safe_import("nex_observability")
        be_mod     = _safe_import("nex_bleeding_edge")
        cloop_mod  = _safe_import("nex_cognitive_loop")

        # ── UPGRADE 3: Memory V3 ──────────────────────────────────────────────
        self.memory = mem_mod.MemorySystem(db_path) if mem_mod else None

        # ── UPGRADE 4: Belief Revision Engine ────────────────────────────────
        self.belief_graph = belief_mod.BeliefGraph(db_path) if belief_mod else None

        # ── UPGRADE 7: Drive System ───────────────────────────────────────────
        self.drives = da_mod.DriveSystem() if da_mod else None

        # ── UPGRADE 8: Attention ──────────────────────────────────────────────
        self.attention = (
            da_mod.AttentionSystem(top_n=5, drive_system=self.drives)
            if da_mod else None
        )

        # ── UPGRADE 5+6: BDI + Planning ──────────────────────────────────────
        self.planning = (
            bdi_mod.PlanningEngine(db_path, llm_client=None)
            if bdi_mod else None
        )

        # ── UPGRADE 9: Multi-agent debate ────────────────────────────────────
        self.debate = (
            ma_mod.InternalDebateManager(llm_complete=self._llm)
            if ma_mod else None
        )

        # ── UPGRADE 10+11: Governance + World Model ───────────────────────────
        self.governance  = gw_mod.GovernanceLayer(db_path) if gw_mod else None
        self.world_model = gw_mod.WorldModel()             if gw_mod else None

        # ── UPGRADE 12+13: Learning + Identity ───────────────────────────────
        self.learning = (
            li_mod.LearningSystem(db_path, self.belief_graph, self.drives)
            if li_mod else None
        )
        self.identity = (
            li_mod.IdentityStabilizer(self.belief_graph)
            if li_mod else None
        )

        # ── UPGRADE 15+16: Observability + Failure Detection ─────────────────
        self.obs = (
            obs_mod.ObservabilityEngine(
                db_path, self.drives, self.belief_graph, self.learning
            )
            if obs_mod else None
        )

        # ── UPGRADE 17A: Future Reasoning ────────────────────────────────────
        self.future = (
            be_mod.FutureReasoningEngine(self._llm)
            if be_mod else None
        )

        # ── UPGRADE 17B: Belief Economy ───────────────────────────────────────
        self.economy = be_mod.BeliefEconomy(budget=100) if be_mod else None

        # ── UPGRADE 17C: Emergent Goals ───────────────────────────────────────
        self.emergent = (
            be_mod.EmergentGoalGenerator(self.planning, self.drives, self.belief_graph)
            if be_mod else None
        )

        # ── UPGRADE 17D: Session Continuity ──────────────────────────────────
        self.continuity = (
            be_mod.SessionContinuity(self.belief_graph, self._notify)
            if be_mod else None
        )

        # ── UPGRADE 17E: Self-Debugger ────────────────────────────────────────
        self.debugger = (
            be_mod.SelfDebugger(self.obs, self._notify, self._llm)
            if be_mod else None
        )

        # ── UPGRADE 1+2: Control Layer + Cognitive Loop (wraps everything) ───
        self.control = arch_mod.get_control() if arch_mod else None
        if self.control:
            self.control.register("memory",     self.memory)
            self.control.register("attention",  self.attention)
            self.control.register("planning",   self.planning)
            self.control.register("governance", self.governance)

        self.cloop = (
            cloop_mod.CognitiveLoop(
                belief_store=self.belief_graph,
                memory_store=self.memory,
                llm_client=None,   # inject via llm wrapper below
                attention=self.attention,
                drive_system=self.drives,
            )
            if cloop_mod else None
        )

        # ── STARTUP CHECKS ────────────────────────────────────────────────────
        if self.identity:
            locked = self.identity.lock_identity_beliefs()
            if locked:
                log.info(f"[V2 INIT] locked {len(locked)} identity beliefs")

        if self.continuity:
            report = self.continuity.check_continuity()
            log.info(f"[V2 INIT] continuity check: {report.get('status')}")

        log.info("[V2 INIT] all upgrades initialized")
        self._log_init_summary()

    def _log_init_summary(self) -> None:
        components = {
            "memory":       self.memory       is not None,
            "belief_graph": self.belief_graph is not None,
            "drives":       self.drives       is not None,
            "attention":    self.attention    is not None,
            "planning":     self.planning     is not None,
            "debate":       self.debate       is not None,
            "governance":   self.governance   is not None,
            "world_model":  self.world_model  is not None,
            "learning":     self.learning     is not None,
            "identity":     self.identity     is not None,
            "obs":          self.obs          is not None,
            "future":       self.future       is not None,
            "economy":      self.economy      is not None,
            "emergent":     self.emergent     is not None,
            "continuity":   self.continuity   is not None,
            "debugger":     self.debugger     is not None,
            "control":      self.control      is not None,
            "cloop":        self.cloop        is not None,
        }
        active = [k for k, v in components.items() if v]
        failed = [k for k, v in components.items() if not v]
        log.info(f"[V2 INIT] active={len(active)} failed={len(failed)}")
        if failed:
            log.warning(f"[V2 INIT] missing modules: {failed}")

    # ─────────────────────────────────────────
    # MAIN TICK — call once per NEX cycle
    # ─────────────────────────────────────────
    def tick(
        self,
        cycle:     int,
        avg_conf:  float,
        raw_input: Optional[dict] = None,
    ) -> dict:
        """
        Per-cycle hook. Wire into existing orchestrator's cycle loop.
        Returns summary dict.
        """
        self._cycle = cycle

        # drives decay
        if self.drives:
            self.drives.tick()

        # emergent goal check
        emergent = []
        if self.emergent:
            emergent = self.emergent.check_and_generate(cycle, avg_conf)

        # identity snapshot every 50 cycles
        if self.identity and cycle % 50 == 0:
            self.identity.take_snapshot()
            drift = self.identity.check_drift()
            if drift.get("alert"):
                self._notify(
                    f"⚠️ *NEX IDENTITY DRIFT*\n"
                    f"drift={drift['drift']:.3f} conf_delta={drift['conf_delta']:+.3f}"
                )

        # self-debug check every 100 cycles
        if self.debugger and cycle % 100 == 0:
            self.debugger.run()

        # world model salience decay every 25 cycles
        if self.world_model and cycle % 25 == 0:
            self.world_model.decay_salience()

        # memory decay every 25 cycles
        if self.memory and cycle % 25 == 0:
            self.memory.run_decay(cycle)

        # belief merge every 100 cycles
        if self.belief_graph and cycle % 100 == 0:
            merged = self.belief_graph.merge_similar()
            if merged:
                log.info(f"[V2] belief merge: {merged} merged")
                if self.drives:
                    self.drives.signal("conflict_resolved")

        return {
            "cycle":    cycle,
            "emergent": len(emergent),
        }

    # ─────────────────────────────────────────
    # TELEGRAM COMMAND HANDLERS
    # ─────────────────────────────────────────

    def handle_command(self, cmd: str, args: str = "") -> str:
        """Route /v2* Telegram commands."""
        cmd = cmd.lower().strip()

        if cmd == "/v2status":
            return self._cmd_status()
        elif cmd == "/v2debug":
            reports = self.debugger.run() if self.debugger else []
            if not reports:
                return "✅ No active failures detected."
            return f"🔧 {len(reports)} failure(s) diagnosed — check Telegram for fix proposals."
        elif cmd == "/v2sim":
            return self._cmd_sim(args)
        elif cmd.startswith("/v2explain"):
            try:
                n = int(args.strip())
                return self.obs.explain(n) if self.obs else "obs not available"
            except:
                return "Usage: /v2explain <cycle_id>"
        elif cmd == "/v2goals":
            return self._cmd_goals()
        elif cmd == "/v2drives":
            return self._cmd_drives()
        elif cmd == "/v2economy":
            return self._cmd_economy()
        else:
            return "Unknown v2 command. Try /v2status /v2debug /v2sim /v2goals /v2drives"

    def _cmd_status(self) -> str:
        sections = ["*NEX V2 STATUS*\n"]

        if self.belief_graph:
            bs = self.belief_graph.stats()
            sections.append(
                f"📊 *Belief Graph*\n"
                f"  total={bs['total']} locked={bs['locked']} "
                f"conflicts={bs['conflicts']} avg_conf={bs['avg_conf']}"
            )

        if self.memory:
            ms = self.memory.stats()
            sections.append("🧠 *Memory*\n" + "  ".join(
                f"{layer}: {v['count']} ({v['avg_conf']:.3f})" for layer, v in ms.items()
            ))

        if self.drives:
            ds = self.drives.state()
            drive_lines = "  ".join(
                f"{n}={v['level']:.2f}" for n, v in ds["drives"].items()
            )
            sections.append(
                f"⚡ *Drives*\n  {drive_lines}\n"
                f"  dominant={ds['dominant']} pressure={ds['decision_pressure']:.2f}"
            )

        if self.planning:
            ps = self.planning.stats()
            sections.append(f"🎯 *Planning*\n  goals={ps['goals']}  intentions={ps['intentions']}")

        if self.learning:
            ls = self.learning.stats()
            sections.append(
                f"📈 *Learning*\n  outcome_count={ls['outcome_count']} "
                f"beliefs_tracked={ls['beliefs_tracked']}"
            )

        if self.obs:
            os_ = self.obs.stats()
            failures = os_["active_failures"]
            sections.append(
                f"🔍 *Observability*\n"
                f"  cycles={os_['cycles_logged']} "
                f"active_failures={failures or 'none'}"
            )

        if self.future:
            fs = self.future.stats()
            sections.append(
                f"🔮 *Future Reasoning*\n"
                f"  sims={fs.get('simulations',0)} pass_rate={fs.get('pass_rate',0):.2f}"
            )

        if self.debate:
            ds2 = self.debate.stats()
            sections.append(
                f"🗣️ *Internal Debate*\n"
                f"  debates={ds2.get('debates',0)} consensus={ds2.get('consensus_pct',0):.0%}"
            )

        return "\n\n".join(sections)

    def _cmd_sim(self, hypothesis: str) -> str:
        if not hypothesis:
            return "Usage: /v2sim <hypothesis>"
        if not self.future:
            return "FutureReasoningEngine not available"
        sim = self.future.simulate(hypothesis)
        status = "✅ ACCEPTED" if not sim.rejected else "❌ REJECTED"
        return (
            f"*Simulation*\n"
            f"Hypothesis: {hypothesis[:80]}\n"
            f"Predicted: {sim.predicted[:120]}\n"
            f"Confidence: {sim.confidence:.2f} | Risk: {sim.risk:.2f}\n"
            f"Result: {status}"
            + (f"\nReason: {sim.reject_reason}" if sim.rejected else "")
        )

    def _cmd_goals(self) -> str:
        if not self.planning:
            return "Planning not available"
        goals = self.planning.get_active_goals()
        if not goals:
            return "No active goals"
        lines = [f"*Active Goals* ({len(goals)})\n"]
        for g in goals[:10]:
            lines.append(f"  [{g.priority:.2f}] {g.name} ({g.status.value})")
        return "\n".join(lines)

    def _cmd_drives(self) -> str:
        if not self.drives:
            return "DriveSystem not available"
        s = self.drives.state()
        lines = ["*Drive State*\n"]
        for n, d in s["drives"].items():
            bar = "█" * int(d["level"] * 10) + "░" * (10 - int(d["level"] * 10))
            lines.append(f"  {n:12} [{bar}] {d['level']:.3f}")
        lines.append(f"\n  dominant: {s['dominant']}")
        lines.append(f"  pressure: {s['decision_pressure']:.3f}")
        return "\n".join(lines)

    def _cmd_economy(self) -> str:
        if not self.economy or not self.belief_graph:
            return "BeliefEconomy not available"
        active = self.economy.get_active_set(self.belief_graph)
        total  = len(self.belief_graph._nodes)
        return (
            f"*Belief Economy*\n"
            f"  total beliefs: {total}\n"
            f"  active set:    {len(active)} (budget={self.economy.budget})\n"
            f"  reserved:      {self.economy.reserve} (identity)\n"
            f"  evicted:       {max(0, total - len(active))}"
        )

    # ─────────────────────────────────────────
    # SHUTDOWN
    # ─────────────────────────────────────────
    def shutdown(self) -> None:
        """Call from nex_exit.sh SIGTERM handler."""
        if self.continuity:
            self.continuity.save_session()
            log.info("[V2] session fingerprint saved")
        if self.obs:
            summary = self.obs.stats()
            log.info(f"[V2] shutdown obs summary: {summary}")
        log.info("[V2] graceful shutdown complete")


# ─────────────────────────────────────────────
# FACTORY
# ─────────────────────────────────────────────

_instance: Optional[NexV2] = None

def init_v2_upgrades(
    db_path:      Path,
    belief_store  = None,
    llm_complete: Optional[Callable] = None,
    notify_fn:    Optional[Callable] = None,
) -> NexV2:
    global _instance
    _instance = NexV2(db_path, belief_store, llm_complete, notify_fn)
    return _instance

def get_v2() -> Optional[NexV2]:
    return _instance

def get_v2_status() -> str:
    if _instance:
        return _instance.handle_command("/v2status")
    return "V2 not initialized"
