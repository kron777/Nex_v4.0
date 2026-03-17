"""
NEX :: GPU WATCH
Real-time RX 6600 LE health monitor.
Reads VRAM%, temp, power via rocm-smi.
Auto-throttles NEX if GPU is under stress.
"""
import subprocess
import os
import json
import logging
from datetime import datetime

log = logging.getLogger("nex.gpu_watch")

CONFIG_DIR   = os.path.expanduser("~/.config/nex")
GPU_LOG_PATH = os.path.join(CONFIG_DIR, "gpu_health.json")

VRAM_WARN    = 85   # % — warn above this
VRAM_CRIT    = 95   # % — throttle above this
TEMP_WARN    = 80   # °C
TEMP_CRIT    = 88   # °C
POWER_MAX    = 100  # W


def get_gpu_stats():
    """Read GPU stats via rocm-smi. Returns dict or None."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--showpower"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        stats = {
            "timestamp": datetime.now().isoformat(),
            "gpu_use_pct": 0,
            "vram_pct": 0,
            "temp_c": 0,
            "power_w": 0,
            "status": "ok"
        }
        for line in lines:
            if "GPU use (%)" in line:
                try: stats["gpu_use_pct"] = int(line.split(":")[-1].strip())
                except: pass
            elif "GPU Memory Allocated (VRAM%)" in line:
                try: stats["vram_pct"] = int(line.split(":")[-1].strip())
                except: pass
            elif "Temperature (Sensor edge)" in line or "Temperature (Sensor junction)" in line:
                try: stats["temp_c"] = float(line.split(":")[-1].strip().replace("c","").replace("C","").strip())
                except: pass
            elif "Average Graphics Package Power" in line or "Current Socket Graphics Package Power" in line:
                try: stats["power_w"] = float(line.split(":")[-1].strip().replace("W","").strip())
                except: pass

        # Set status
        if stats["vram_pct"] >= VRAM_CRIT or stats["temp_c"] >= TEMP_CRIT:
            stats["status"] = "critical"
        elif stats["vram_pct"] >= VRAM_WARN or stats["temp_c"] >= TEMP_WARN:
            stats["status"] = "warning"

        return stats
    except Exception as e:
        log.warning(f"[gpu_watch] rocm-smi failed: {e}")
        return None


def check_and_log():
    """
    Check GPU health, log to gpu_health.json, return status string.
    Called every N cycles from run.py.
    """
    stats = get_gpu_stats()
    if not stats:
        return "unavailable"

    # Append to rolling log (keep last 100 entries)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        history = []
        if os.path.exists(GPU_LOG_PATH):
            with open(GPU_LOG_PATH) as f:
                history = json.load(f)
        history.append(stats)
        history = history[-100:]
        with open(GPU_LOG_PATH, "w") as f:
            json.dump(history, f)
    except Exception:
        pass

    # Print alert if needed
    if stats["status"] == "critical":
        print(f"  [GPU CRITICAL] VRAM={stats['vram_pct']}% TEMP={stats['temp_c']}°C POWER={stats['power_w']}W")
    elif stats["status"] == "warning":
        print(f"  [GPU WARNING] VRAM={stats['vram_pct']}% TEMP={stats['temp_c']}°C POWER={stats['power_w']}W")

    return stats["status"]


def get_latest():
    """Return most recent GPU stats from log."""
    try:
        if os.path.exists(GPU_LOG_PATH):
            with open(GPU_LOG_PATH) as f:
                history = json.load(f)
            return history[-1] if history else None
    except Exception:
        pass
    return None


def format_dashboard():
    """One-line dashboard string for display."""
    stats = get_gpu_stats()
    if not stats:
        return "GPU: unavailable"
    icon = "🔥" if stats["status"] == "critical" else "⚠️" if stats["status"] == "warning" else "✅"
    return (f"{icon} GPU {stats['gpu_use_pct']}% | "
            f"VRAM {stats['vram_pct']}% | "
            f"{stats['temp_c']}°C | "
            f"{stats['power_w']}W")
