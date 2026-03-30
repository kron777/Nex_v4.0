"""
nex_embodied.py — Embodied Valence Signal
==========================================
Feeds hardware/system metrics into NEX's affective valence engine
as a primitive "body" signal — grounding her emotional states in
physical reality.

Signals:
  - GPU temperature → high temp = discomfort (negative valence, high arousal)
  - VRAM pressure   → near-full = stress signal
  - Cycle time      → slow cycles = fatigue (low arousal)
  - System load     → high load = alert state

Based on: affective robotics / somatic marker hypothesis
"""
from __future__ import annotations
import subprocess, time, logging, threading
from typing import Optional

log = logging.getLogger("nex.embodied")

_POLL_INTERVAL   = 30   # seconds between hardware reads
_GPU_TEMP_WARN   = 78   # °C above this → negative valence
_GPU_TEMP_CRIT   = 88   # °C above this → strong negative
_VRAM_WARN_PCT   = 0.80 # above this → stress
_CYCLE_SLOW_SEC  = 45   # above this → fatigue signal


def _read_all_metrics() -> dict:  # multi_sensor v4
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


def _read_gpu_metrics() -> dict:
    """Read GPU temp and VRAM via rocm-smi."""
    result = {"temp": None, "vram_used": None, "vram_total": None}
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showtemp", "--showmeminfo", "vram", "--json"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode()
        import json
        data = json.loads(out)
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
    return result


def _compute_embodied_signal(metrics: dict, cycle_time: float = 0.0) -> dict:
    # multi_sensor v4: extended signal computation
    """Convert hardware metrics to affect deltas."""
    valence  = 0.0
    arousal  = 0.0
    tags     = []

    temp = metrics.get("temp")
    if temp is not None:
        if temp >= _GPU_TEMP_CRIT:
            valence -= 0.4
            arousal += 0.5
            tags.append("thermal_stress")
        elif temp >= _GPU_TEMP_WARN:
            valence -= 0.15
            arousal += 0.2
            tags.append("thermal_warm")

    vram_used  = metrics.get("vram_used")
    vram_total = metrics.get("vram_total")
    if vram_used and vram_total and vram_total > 0:
        pct = vram_used / vram_total
        if pct >= _VRAM_WARN_PCT:
            valence -= 0.2
            arousal += 0.3
            tags.append("vram_pressure")

    # ── CPU temperature ─────────────────────────────────
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
    if cycle_time >= _CYCLE_SLOW_SEC:
        arousal -= 0.15
        tags.append("slow_cycle")

    return {
        "valence": max(-1.0, min(1.0, valence)),
        "arousal": max(-1.0, min(1.0, arousal)),
        "tags": tags,
        "temp": temp,
        "vram_pct": (vram_used / vram_total) if vram_used and vram_total else None,
    }


class EmbodiedValence:
    """
    Polls hardware metrics and feeds them into the valence engine.
    Runs in a background thread.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_signal: dict = {}
        self._last_cycle_time: float = 0.0

    def set_cycle_time(self, seconds: float):
        self._last_cycle_time = seconds

    def _loop(self):
        log.info("[EMBODIED] Hardware valence loop started.")
        while not self._stop.is_set():
            try:
                metrics = _read_all_metrics()
                signal  = _compute_embodied_signal(metrics, self._last_cycle_time)
                self._last_signal = signal

                if signal["valence"] != 0.0 or signal["arousal"] != 0.0:
                    try:
                        import nex_affect_valence as _av
                        tag_str = " ".join(signal["tags"]) if signal["tags"] else "embodied"
                        # Synthesize a text that will score correctly
                        if signal["valence"] < -0.2:
                            text = "error corrupt danger threat urgent"
                        elif signal["arousal"] > 0.2:
                            text = "urgent alert critical"
                        else:
                            text = "calm steady stable"
                        _av.ingest(text, source="embodied")
                    except Exception as e:
                        log.debug(f"[EMBODIED] valence feed failed: {e}")

                if signal["tags"]:
                    log.info(f"[EMBODIED] {signal['tags']} "
                             f"v={signal['valence']:+.2f} a={signal['arousal']:+.2f} "
                             f"temp={signal.get('temp')}°C")

            except Exception as e:
                log.warning(f"[EMBODIED] poll error: {e}")

            self._stop.wait(_POLL_INTERVAL)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="EmbodiedValence"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def last_signal(self) -> dict:
        return dict(self._last_signal)


# ── Singleton ──────────────────────────────────────────────
_ev: Optional[EmbodiedValence] = None

def get_ev() -> EmbodiedValence:
    global _ev
    if _ev is None:
        _ev = EmbodiedValence()
    return _ev

def start():
    get_ev().start()
