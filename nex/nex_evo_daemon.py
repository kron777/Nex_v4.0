"""
nex_evo_daemon.py — Self-evolution daemon.
Mines audit log every N cycles; detects gaps, co-occurrences,
synthesis triggers, and pruning candidates.
"""
import os, re, json, time, threading, collections
from pathlib import Path

AUDIT_PATH = Path.home() / "Desktop" / "nex" / "nex_audit.log"
CYCLE_INTERVAL = 50   # belief cycles between evo runs
_cycle_count = 0
_lock = threading.Lock()

def _read_audit(tail=2000) -> list[str]:
    try:
        lines = AUDIT_PATH.read_text(errors="replace").splitlines()
        return lines[-tail:]
    except Exception:
        return []

def _query_gaps(lines: list[str]) -> list[str]:
    """Topics that got fallback/weak replies."""
    gaps = []
    for ln in lines:
        m = re.search(r"\[GAP\]\s+(\w+)", ln)
        if m:
            gaps.append(m.group(1))
    return list(dict.fromkeys(gaps))[:5]

def _co_occurrences(lines: list[str]) -> list[tuple[str, str]]:
    """Topic pairs that appear in same query."""
    pairs = []
    for ln in lines:
        topics = re.findall(r"topic=(\w+)", ln)
        if len(topics) >= 2:
            pairs.append((topics[0], topics[1]))
    return list(dict.fromkeys(pairs))[:10]

def _synthesis_candidates(beliefs_by_topic: dict) -> list[str]:
    """Topics with 3+ strong beliefs but no opinion."""
    cands = []
    for topic, bs in beliefs_by_topic.items():
        strong = [b for b in bs if b.get("confidence", 0) >= 0.7]
        has_opinion = any("opinion" in b.get("tags", []) for b in bs)
        if len(strong) >= 3 and not has_opinion:
            cands.append(topic)
    return cands[:3]

def _prune_candidates(beliefs_by_topic: dict) -> list[str]:
    """Topics with many beliefs but low average confidence."""
    cands = []
    for topic, bs in beliefs_by_topic.items():
        if len(bs) < 8:
            continue
        avg = sum(b.get("confidence", 0.5) for b in bs) / len(bs)
        if avg < 0.45:
            cands.append((topic, avg, len(bs)))
    return sorted(cands, key=lambda x: x[1])[:3]

def run_evo_cycle(kernel=None) -> dict:
    """Run one evolution cycle. Pass the kernel object for action hooks."""
    lines = _read_audit()
    report = {
        "gaps": _query_gaps(lines),
        "co_occurrences": _co_occurrences(lines),
        "synthesis": [],
        "prune": [],
    }

    # Build beliefs_by_topic from kernel if available
    beliefs_by_topic: dict = collections.defaultdict(list)
    if kernel and hasattr(kernel, "soul") and hasattr(kernel.soul, "_beliefs"):
        for b in kernel.soul._beliefs:
            beliefs_by_topic[b.get("topic", "unknown")].append(b)

    report["synthesis"] = _synthesis_candidates(beliefs_by_topic)
    report["prune"]     = [t for t, _, _ in _prune_candidates(beliefs_by_topic)]

    # Enqueue gaps into curiosity queue
    if kernel and hasattr(kernel, "curiosity_queue"):
        for gap in report["gaps"]:
            kernel.curiosity_queue.append(gap)

    print(f"  [EVO] gaps={report['gaps']} synth={report['synthesis']} prune={report['prune']}")
    return report

def start_evo_daemon(kernel=None):
    """Start background thread that runs evo every CYCLE_INTERVAL seconds."""
    def _loop():
        while True:
            time.sleep(CYCLE_INTERVAL * 60)
            try:
                run_evo_cycle(kernel)
            except Exception as e:
                print(f"  [EVO] daemon error: {e}")
    t = threading.Thread(target=_loop, daemon=True, name="nex-evo-daemon")
    t.start()
    print("  [EVO] daemon started")
