"""
nex_resource_orch.py — Hardware-Aware Resource Orchestrator
============================================================
Monitors hardware state and returns recommended cognitive modes
to keep NEX within safe resource bounds on the RX 6600 (8GB VRAM).

Outputs a ResourceState that run.py uses to throttle:
  - belief_field size
  - LLM call frequency
  - synthesis batch size
  - dream cycle eligibility

All monitoring is read-only — no subprocess killing.
"""
from __future__ import annotations
import subprocess, time, logging, threading
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("nex.resource_orch")

_POLL_INTERVAL  = 20    # seconds
_VRAM_WARN      = 0.78  # 78% VRAM usage → throttle
_VRAM_CRIT      = 0.90  # 90% → aggressive throttle
_TEMP_WARN      = 78    # °C GPU temp → reduce synthesis batch
_TEMP_CRIT      = 88    # °C → pause heavy compute
_CPU_WARN       = 7.0   # load avg → throttle LLM calls


@dataclass
class ResourceState:
    vram_pct:       float = 0.0
    gpu_temp:       float = 0.0
    cpu_load:       float = 0.0
    timestamp:      float = 0.0
    zone:           str = "nominal"   # nominal | warn | critical
    belief_field_cap: int = 5000
    synthesis_batch:  int = 10
    allow_dream:      bool = True
    allow_heavy_llm:  bool = True
    throttle_reason:  str = ""


def _read_hardware() -> dict:
    result = {"vram_pct": 0.0, "gpu_temp": 0.0, "cpu_load": 0.0}
    try:
        import json as _j
        out = subprocess.check_output(
            ["rocm-smi", "--showtemp", "--showmeminfo", "vram", "--json"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode()
        data = _j.loads(out)
        for card in data.values():
            if isinstance(card, dict):
                t = card.get("Temperature (Sensor edge) (C)", "")
                if t:
                    result["gpu_temp"] = float(t)
                vu = card.get("VRAM Total Used Memory (B)")
                vt = card.get("VRAM Total Memory (B)")
                if vu and vt:
                    result["vram_pct"] = int(vu) / int(vt)
                break
    except Exception:
        pass
    try:
        import os
        result["cpu_load"] = os.getloadavg()[0]
    except Exception:
        pass
    return result


def _compute_state(hw: dict) -> ResourceState:
    s = ResourceState(
        vram_pct=hw["vram_pct"],
        gpu_temp=hw["gpu_temp"],
        cpu_load=hw["cpu_load"],
        timestamp=time.time(),
    )

    if hw["vram_pct"] >= _VRAM_CRIT or hw["gpu_temp"] >= _TEMP_CRIT:
        s.zone = "critical"
        s.belief_field_cap = 2000
        s.synthesis_batch  = 3
        s.allow_dream      = False
        s.allow_heavy_llm  = False
        s.throttle_reason  = (
            f"VRAM={hw['vram_pct']:.0%} GPU={hw['gpu_temp']:.0f}°C"
        )
    elif hw["vram_pct"] >= _VRAM_WARN or hw["gpu_temp"] >= _TEMP_WARN or hw["cpu_load"] >= _CPU_WARN:
        s.zone = "warn"
        s.belief_field_cap = 3500
        s.synthesis_batch  = 6
        s.allow_dream      = False
        s.allow_heavy_llm  = True
        s.throttle_reason  = (
            f"VRAM={hw['vram_pct']:.0%} GPU={hw['gpu_temp']:.0f}°C "
            f"CPU={hw['cpu_load']:.1f}"
        )
    else:
        s.zone = "nominal"
        s.belief_field_cap = 5000
        s.synthesis_batch  = 10
        s.allow_dream      = True
        s.allow_heavy_llm  = True

    return s


class ResourceOrchestrator:
    def __init__(self):
        self._state = ResourceState()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _loop(self):
        while not self._stop.is_set():
            try:
                hw = _read_hardware()
                new_state = _compute_state(hw)
                if new_state.zone != self._state.zone:
                    log.info(
                        f"[RESOURCE] zone: {self._state.zone} → {new_state.zone} "
                        f"({new_state.throttle_reason})"
                    )
                self._state = new_state
            except Exception as e:
                log.debug(f"[RESOURCE] poll error: {e}")
            self._stop.wait(_POLL_INTERVAL)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="ResourceOrch"
        )
        self._thread.start()
        log.info("[RESOURCE] Orchestrator started")

    def stop(self):
        self._stop.set()

    def state(self) -> ResourceState:
        return self._state

    def belief_field_cap(self) -> int:
        return self._state.belief_field_cap

    def allow_dream(self) -> bool:
        return self._state.allow_dream

    def allow_heavy_llm(self) -> bool:
        return self._state.allow_heavy_llm


# ── Singleton ──────────────────────────────────────────────
_ro: Optional[ResourceOrchestrator] = None

def get_ro() -> ResourceOrchestrator:
    global _ro
    if _ro is None:
        _ro = ResourceOrchestrator()
    return _ro

def start():
    get_ro().start()

def state() -> ResourceState:
    return get_ro().state()
