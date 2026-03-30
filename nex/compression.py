"""
NEX :: COMPRESSION
Summarises old conversations and beliefs to prevent unbounded growth.
Run nightly during consolidation window.
"""
import json, os
from datetime import datetime, timedelta

def _dedup_beliefs(beliefs):
    """Deduplicate beliefs list by content[:60] — prevents UNIQUE constraint errors."""
    seen = set()
    out  = []
    for b in beliefs:
        key = (b.get("content","") if isinstance(b,dict) else str(b))[:60]
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out

CONFIG_DIR    = os.path.expanduser("~/.config/nex")
CONVOS_PATH   = os.path.join(CONFIG_DIR, "conversations.json")
ARCHIVE_PATH  = os.path.join(CONFIG_DIR, "monthly_summary.json")
BELIEFS_PATH  = os.path.join(CONFIG_DIR, "beliefs.json")

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else []

def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def run_compression(cycle_num):
    """Every 50 cycles, compress old conversations and prune beliefs."""
    if cycle_num % 50 != 0:
        return []

    logs = []
    now     = datetime.now()
    cutoff  = now - timedelta(days=30)
    convos  = load_json(CONVOS_PATH, [])
    archive = load_json(ARCHIVE_PATH, [])

    old = []
    recent = []
    for c in convos:
        ts = c.get("timestamp","")
        try:
            dt = datetime.fromisoformat(ts[:19])
            if dt < cutoff:
                old.append(c)
            else:
                recent.append(c)
        except Exception:
            recent.append(c)

    if old:
        # Summarise old conversations into monthly archive
        by_author = {}
        for c in old:
            a = c.get("post_author","") or c.get("agent","unknown")
            by_author.setdefault(a, []).append(c.get("post_title","")[:40])

        summary = {
            "period_end":   now.isoformat(),
            "total_convos": len(old),
            "by_author":    {a: len(ts) for a, ts in by_author.items()},
            "top_authors":  sorted(by_author, key=lambda x: -len(by_author[x]))[:5],
            "archived_at":  now.isoformat()
        }
        archive.append(summary)
        save_json(ARCHIVE_PATH, archive[-24:])  # keep 24 months
        save_json(CONVOS_PATH, recent)
        logs.append(("compress", f"Archived {len(old)} old conversations, kept {len(recent)} recent"))

    # Also prune beliefs to keep file manageable
    beliefs = load_json(BELIEFS_PATH, [])
    if len(beliefs) > 5000:
        # Keep: human_validated, high confidence, recent
        protected = [b for b in beliefs if b.get("human_validated") or b.get("confidence",0) > 0.7]
        rest = sorted(
            [b for b in beliefs if not b.get("human_validated") and b.get("confidence",0) <= 0.7],
            key=lambda x: x.get("confidence",0), reverse=True
        )[:5000 - len(protected)]
        beliefs = protected + rest
        save_json(BELIEFS_PATH, _dedup_beliefs(beliefs))
        logs.append(("compress", f"Belief field pruned to {len(beliefs)} entries"))

    return logs
