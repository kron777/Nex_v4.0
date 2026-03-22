"""
NEX RESOURCE THROTTLE
======================
Drop this file into ~/Nex_v4.0/
Then add one line to run.py main loop.

Keeps CPU below TARGET_CPU% and GPU below TARGET_GPU%
by inserting adaptive sleeps — steady drip not burst.
"""

import time
import os
import threading

# ── TARGETS — adjust these to taste ──────────────────────────
TARGET_CPU   = 65   # max CPU % before throttling kicks in
TARGET_GPU   = 75   # max GPU % before throttling kicks in
MIN_SLEEP    = 0.05  # minimum sleep between cycles (seconds)
MAX_SLEEP    = 2.0  # maximum sleep when under heavy load
CHECK_EVERY  = 3    # re-check resource usage every N cycles
# ─────────────────────────────────────────────────────────────

_cycle_count  = 0
_current_sleep = MIN_SLEEP
_lock          = threading.Lock()


def _get_cpu():
    try:
        with open('/proc/stat') as f:
            line = f.readline()
        fields = [float(x) for x in line.strip().split()[1:]]
        idle = fields[3]
        total = sum(fields)
        return round((1.0 - idle / total) * 100, 1)
    except Exception:
        return 0.0


def _get_gpu():
    """AMD ROCm GPU usage."""
    try:
        result = os.popen(
            "cat /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1"
        ).read().strip()
        return float(result) if result else 0.0
    except Exception:
        return 0.0


def _get_gpu_mem():
    """GPU VRAM usage %."""
    try:
        used = int(os.popen(
            "cat /sys/class/drm/card*/device/mem_info_vram_used 2>/dev/null | head -1"
        ).read().strip())
        total = int(os.popen(
            "cat /sys/class/drm/card*/device/mem_info_vram_total 2>/dev/null | head -1"
        ).read().strip())
        return round(used / total * 100, 1) if total else 0.0
    except Exception:
        return 0.0


def throttle_cycle():
    """
    Call this once per main cognitive cycle.
    Sleeps adaptively based on current CPU/GPU load.
    Returns the sleep duration used (for logging).
    """
    global _cycle_count, _current_sleep

    with _lock:
        _cycle_count += 1

        # Re-evaluate every CHECK_EVERY cycles
        if _cycle_count % CHECK_EVERY == 0:
            cpu = _get_cpu()
            gpu = _get_gpu()

            if cpu > TARGET_CPU or gpu > TARGET_GPU:
                # Increase sleep — back off
                _current_sleep = min(_current_sleep * 1.5, MAX_SLEEP)
            else:
                # Decrease sleep — speed up gradually
                _current_sleep = max(_current_sleep * 0.85, MIN_SLEEP)

        sleep_time = _current_sleep

    time.sleep(sleep_time)
    return sleep_time


def get_status():
    """Returns current throttle status for logging."""
    cpu = _get_cpu()
    gpu = _get_gpu()
    return {
        "cpu_pct":     cpu,
        "gpu_pct":     gpu,
        "sleep_s":     round(_current_sleep, 2),
        "cycle":       _cycle_count,
        "throttling":  _current_sleep > MIN_SLEEP
    }


# ── BELIEF ENGINE PATCH ───────────────────────────────────────
# Slows the BeliefEngine tick from 0.05s (20/sec) to 0.3s (3/sec)
# Apply by patching run.py — see instructions below
BELIEF_ENGINE_TICK = 0.3   # was 0.05


if __name__ == "__main__":
    print("NEX Throttle — live resource test")
    print(f"CPU: {_get_cpu()}%  GPU: {_get_gpu()}%  VRAM: {_get_gpu_mem()}%")
    print(f"Target CPU: {TARGET_CPU}%  Target GPU: {TARGET_GPU}%")
    print(f"Sleep range: {MIN_SLEEP}s – {MAX_SLEEP}s")
