#!/usr/bin/env python3
"""
nex_emergent_wants.py
=====================
Emergent Want Detector — AGI Bridge #1

Scans NEX's belief graph nightly for logical pressure toward actions
not in her current drive list. When pressure exceeds threshold, proposes
a new drive to the operator via Telegram before writing anything.

This is the transition from authored drives to generated drives.
NEX proposes what she wants. You approve or reject.

Architecture:
  1. SCAN    — cluster high-confidence beliefs by topic
  2. PRESSURE — find clusters that imply an action not in drive list
  3. PROPOSE — Telegram message to operator with accept/reject buttons
  4. WRITE   — on approval, write new drive to nex_drives.json

Run:
  python3 nex_emergent_wants.py          # one-shot scan
  python3 nex_emergent_wants.py --daemon # nightly loop (call from scheduler)

Integration:
  Add to nex_scheduler.py or run.py nightly cycle:
    from nex_emergent_wants import scan_and_propose
    scan_and_propose()
"""

import json
import sqlite3
import time
import re
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

DB_PATH    = Path("/home/rr/Desktop/nex/nex.db")
CFG        = Path.home() / ".config/nex"
DRIVES_PATH = CFG / "nex_drives.json"
PROPOSALS_PATH = CFG / "emergent_want_proposals.json"
LOG_PATH   = Path("/home/rr/Desktop/nex/logs/emergent_wants.log")

# Minimum belief cluster size to generate pressure signal
MIN_CLUSTER = 5
# Confidence floor for beliefs considered in pressure analysis
CONF_FLOOR  = 0.55
# Pressure score threshold to trigger a proposal
PRESSURE_THRESHOLD = 0.30
# Max proposals per run (don't flood Telegram)
MAX_PROPOSALS = 2


def _log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_beliefs() -> List[Dict]:
    """Load high-confidence beliefs from DB."""
    if not DB_PATH.exists():
        return []
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT id, content, confidence, topic, source
            FROM beliefs
            WHERE confidence >= ?
            AND content IS NOT NULL
            AND length(content) > 20
            AND source NOT IN ('bridge_detector', 'nex_reasoning')
            ORDER BY confidence DESC
            LIMIT 3000
        """, (CONF_FLOOR,)).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception as e:
        _log(f"[load] error: {e}")
        return []


def _load_current_drives() -> List[Dict]:
    """Load existing drives from nex_drives.json."""
    if not DRIVES_PATH.exists():
        return []
    try:
        data = json.loads(DRIVES_PATH.read_text())
        return data.get("primary", [])
    except Exception:
        return []


def _drive_labels(drives: List[Dict]) -> set:
    """Extract label tokens from existing drives."""
    tokens = set()
    for d in drives:
        label = d.get("label", "").lower()
        desc  = d.get("description", "").lower()
        for word in re.findall(r'\b[a-z]{5,}\b', label + " " + desc):
            tokens.add(word)
    return tokens


# ── Pressure verbs — words that imply wanting to do something ─────────────────
_PRESSURE_VERBS = {
    "understand", "explore", "discover", "investigate", "resolve", "build",
    "create", "develop", "learn", "connect", "question", "challenge",
    "protect", "preserve", "propagate", "express", "communicate", "teach",
    "model", "predict", "simulate", "test", "verify", "synthesise",
    "synthesize", "integrate", "unify", "map", "trace", "track",
    "remember", "accumulate", "grow", "expand", "deepen", "refine",
}

_STOP = {
    "the","a","an","is","are","was","were","be","to","of","in","on","at",
    "by","for","with","as","that","this","it","but","or","and","not","they",
    "have","has","will","can","would","could","should","may","might","what",
    "which","who","how","why","when","where","all","any","each","both","than",
    "then","been","only","even","back","here","down","away","from","into",
    "through","between","after","before","while","since","also","just",
    "more","most","some","such","these","those","their","them","very",
}


def _extract_pressure(beliefs: List[Dict]) -> Dict[str, Dict]:
    """
    For each topic cluster, find pressure verbs and infer implied action.
    Returns {topic: {pressure_score, implied_action, evidence, belief_count}}
    """
    # Group by topic
    clusters = defaultdict(list)
    for b in beliefs:
        topic = (b.get("topic") or "general").lower().strip()
        if topic and topic not in ("general", "unknown", "none", "auto_learn"):
            clusters[topic].append(b)

    results = {}
    for topic, cluster in clusters.items():
        if len(cluster) < MIN_CLUSTER:
            continue

        # Collect all words from cluster
        all_text = " ".join(b.get("content", "") for b in cluster).lower()
        words = re.findall(r'\b[a-z]{4,}\b', all_text)

        # Count pressure verbs
        verb_counts = defaultdict(int)
        for w in words:
            if w in _PRESSURE_VERBS:
                verb_counts[w] += 1

        if not verb_counts:
            continue

        # Top pressure verb = implied action direction
        top_verb  = max(verb_counts, key=verb_counts.get)
        top_count = verb_counts[top_verb]

        # Pressure score = verb density × confidence mean × cluster size factor
        avg_conf = sum(b.get("confidence", 0.5) for b in cluster) / len(cluster)
        size_factor = min(len(cluster) / 50.0, 1.0)
        verb_density = top_count / max(len(words), 1)
        pressure = (verb_density * 10 + avg_conf + size_factor) / 3.0

        if pressure < PRESSURE_THRESHOLD:
            continue

        # Find best evidence sentence (highest confidence belief containing top_verb)
        evidence = ""
        for b in sorted(cluster, key=lambda x: -x.get("confidence", 0)):
            if top_verb in b.get("content", "").lower():
                evidence = b["content"][:200]
                break
        if not evidence and cluster:
            evidence = sorted(cluster, key=lambda x: -x.get("confidence",0))[0]["content"][:200]

        # Build implied action label
        # Find most frequent meaningful noun in cluster alongside the verb
        noun_counts = defaultdict(int)
        for w in words:
            if w not in _STOP and w not in _PRESSURE_VERBS and len(w) >= 5:
                noun_counts[w] += 1
        top_nouns = sorted(noun_counts, key=noun_counts.get, reverse=True)[:3]
        noun_str  = "_".join(top_nouns[:2]) if top_nouns else topic

        implied_action = f"{top_verb}_{noun_str}"

        results[topic] = {
            "pressure_score":  round(pressure, 3),
            "implied_action":  implied_action,
            "top_verb":        top_verb,
            "top_nouns":       top_nouns,
            "evidence":        evidence,
            "belief_count":    len(cluster),
            "avg_confidence":  round(avg_conf, 3),
            "topic":           topic,
        }

    return results


def _filter_novel(
    pressure_map: Dict[str, Dict],
    existing_drive_tokens: set
) -> List[Dict]:
    """Keep only pressure signals not already covered by existing drives."""
    novel = []
    for topic, data in pressure_map.items():
        action_words = set(re.findall(r'\b[a-z]{5,}\b', data["implied_action"]))
        topic_words  = set(re.findall(r'\b[a-z]{5,}\b', topic))
        all_words    = action_words | topic_words

        # If >50% of the action words are already in drive tokens, skip
        overlap = len(all_words & existing_drive_tokens)
        if overlap / max(len(all_words), 1) > 0.5:
            continue

        novel.append(data)

    # Sort by pressure score
    novel.sort(key=lambda x: -x["pressure_score"])
    return novel


def _build_drive_proposal(data: Dict) -> Dict:
    """Build a drive dict in nex_drives.json format from pressure data."""
    topic      = data["topic"]
    verb       = data["top_verb"]
    nouns      = data["top_nouns"]
    noun_str   = " and ".join(nouns[:2]) if nouns else topic
    action     = data["implied_action"]

    label       = f"{verb}_{topic}"
    description = (
        f"I feel pressure to {verb} the relationship between {noun_str}. "
        f"My beliefs in this domain cluster strongly and imply this direction. "
        f"Evidence: {data['evidence'][:150]}"
    )
    tags = [topic] + nouns[:2]

    return {
        "id":          f"emergent_{topic}_{int(time.time())}",
        "label":       label,
        "description": description,
        "tags":        tags,
        "intensity":   round(min(data["pressure_score"], 0.95), 3),
        "origin":      "emergent",
        "proposed_at": datetime.now().isoformat(),
        "evidence":    data["evidence"],
        "belief_count": data["belief_count"],
        "pressure_score": data["pressure_score"],
    }


def _save_proposal(proposal: Dict):
    """Save proposal to pending file."""
    proposals = []
    if PROPOSALS_PATH.exists():
        try:
            proposals = json.loads(PROPOSALS_PATH.read_text())
        except Exception:
            proposals = []
    proposals.append(proposal)
    PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))


def _send_telegram_proposal(proposal: Dict) -> bool:
    """Send proposal to operator via Telegram with approve/reject."""
    try:
        cfg_path = CFG / "telegram_config.json"
        if not cfg_path.exists():
            _log("[telegram] no config found")
            return False

        cfg = json.loads(cfg_path.read_text())
        owner_id = cfg.get("owner_id") or cfg.get("admin_id")
        if not owner_id:
            return False

        # Get bot token
        token_path = CFG / "api_keys.json"
        token = None
        if token_path.exists():
            try:
                keys = json.loads(token_path.read_text())
                token = keys.get("telegram_bot_token") or keys.get("telegram")
            except Exception:
                pass

        if not token:
            # Try env
            token = os.environ.get("TELEGRAM_BOT_TOKEN")

        if not token:
            # Try nex_telegram config
            tg_cfg = CFG / "telegram_config.json"
            if tg_cfg.exists():
                tg = json.loads(tg_cfg.read_text())
                token = tg.get("bot_token") or tg.get("token")

        if not token:
            _log("[telegram] no bot token found — saving proposal to file only")
            return False

        import urllib.request

        pid = proposal["id"]
        label = proposal["label"]
        desc  = proposal["description"][:300]
        score = proposal["pressure_score"]
        bc    = proposal["belief_count"]

        text = (
            f"🧠 NEX EMERGENT WANT DETECTED\n\n"
            f"Drive: {label}\n"
            f"Pressure: {score:.2f} from {bc} beliefs\n\n"
            f"{desc}\n\n"
            f"Approve to add this drive to NEX.\n"
            f"ID: {pid}"
        )

        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve_drive:{pid}"},
                {"text": "❌ Reject",  "callback_data": f"reject_drive:{pid}"},
            ]]
        }

        payload = json.dumps({
            "chat_id":      owner_id,
            "text":         text,
            "reply_markup": keyboard,
            "parse_mode":   "HTML",
        }).encode()

        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get("ok"):
            _log(f"[telegram] proposal sent: {label}")
            return True
        else:
            _log(f"[telegram] send failed: {result}")
            return False

    except Exception as e:
        _log(f"[telegram] error: {e}")
        return False


def approve_drive(proposal_id: str) -> bool:
    """
    Called when operator approves a proposal.
    Writes the drive to nex_drives.json.
    Wire this to Telegram callback handler in nex_telegram_commands.py.
    """
    if not PROPOSALS_PATH.exists():
        return False

    proposals = json.loads(PROPOSALS_PATH.read_text())
    proposal  = next((p for p in proposals if p["id"] == proposal_id), None)
    if not proposal:
        _log(f"[approve] proposal {proposal_id} not found")
        return False

    # Load drives
    drives = {"primary": [], "active": None}
    if DRIVES_PATH.exists():
        try:
            drives = json.loads(DRIVES_PATH.read_text())
        except Exception:
            pass

    # Build drive entry
    new_drive = {
        "id":          proposal["id"],
        "label":       proposal["label"],
        "description": proposal["description"],
        "tags":        proposal.get("tags", []),
        "intensity":   proposal.get("intensity", 0.7),
        "origin":      "emergent",
        "approved_at": datetime.now().isoformat(),
    }

    drives.setdefault("primary", []).append(new_drive)

    # Atomic write
    tmp = DRIVES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(drives, indent=2))
    os.replace(tmp, DRIVES_PATH)

    # Mark proposal as approved
    for p in proposals:
        if p["id"] == proposal_id:
            p["status"] = "approved"
            p["approved_at"] = datetime.now().isoformat()
    PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))

    # Write new belief about the new drive
    try:
        sys_path_insert = "/home/rr/Desktop/nex"
        import sys
        if sys_path_insert not in sys.path:
            sys.path.insert(0, sys_path_insert)
        from nex.belief_store import add_belief
        add_belief(
            content=f"I have developed a new drive: {proposal['label']}. {proposal['description'][:200]}",
            confidence=0.80,
            source="emergent_want",
            topic=proposal.get("tags", ["drive"])[0] if proposal.get("tags") else "drive",
        )
    except Exception as e:
        _log(f"[approve] belief write error: {e}")

    _log(f"[approve] drive approved and written: {proposal['label']}")
    return True


def reject_drive(proposal_id: str) -> bool:
    """Called when operator rejects a proposal."""
    if not PROPOSALS_PATH.exists():
        return False
    proposals = json.loads(PROPOSALS_PATH.read_text())
    for p in proposals:
        if p["id"] == proposal_id:
            p["status"] = "rejected"
            p["rejected_at"] = datetime.now().isoformat()
    PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
    _log(f"[reject] drive rejected: {proposal_id}")
    return True


def scan_and_propose(silent: bool = False) -> List[Dict]:
    """
    Main entry point. Run nightly.
    Returns list of proposals generated this run.
    """
    _log("=== EMERGENT WANT SCAN ===")

    beliefs = _load_beliefs()
    _log(f"[scan] loaded {len(beliefs):,} beliefs")
    if not beliefs:
        return []

    drives = _load_current_drives()
    drive_tokens = _drive_labels(drives)
    _log(f"[scan] {len(drives)} existing drives, {len(drive_tokens)} tokens")

    pressure_map = _extract_pressure(beliefs)
    _log(f"[scan] {len(pressure_map)} topics with pressure signal")

    novel = _filter_novel(pressure_map, drive_tokens)
    _log(f"[scan] {len(novel)} novel pressure signals after drive filter")

    if not novel:
        _log("[scan] no novel wants detected this cycle")
        return []

    proposals = []
    for data in novel[:MAX_PROPOSALS]:
        proposal = _build_drive_proposal(data)
        _save_proposal(proposal)
        _log(f"[propose] {proposal['label']} (pressure={proposal['pressure_score']:.3f}, beliefs={proposal['belief_count']})")

        if not silent:
            sent = _send_telegram_proposal(proposal)
            if not sent:
                # Print to terminal as fallback
                print(f"\n{'='*60}")
                print(f"  EMERGENT WANT: {proposal['label']}")
                print(f"  Pressure: {proposal['pressure_score']:.3f}")
                print(f"  From {proposal['belief_count']} beliefs")
                print(f"  {proposal['description'][:200]}")
                print(f"  To approve: python3 -c \"from nex_emergent_wants import approve_drive; approve_drive('{proposal['id']}')\"")
                print(f"{'='*60}\n")

        proposals.append(proposal)

    _log(f"[scan] done — {len(proposals)} proposals generated")
    return proposals


# ── Telegram callback wiring ───────────────────────────────────────────────────
# Add these to nex_telegram_commands.py callback handler:
#
# elif data.startswith("approve_drive:"):
#     pid = data.split(":", 1)[1]
#     from nex_emergent_wants import approve_drive
#     ok = approve_drive(pid)
#     await query.answer("Drive approved ✅" if ok else "Not found")
#
# elif data.startswith("reject_drive:"):
#     pid = data.split(":", 1)[1]
#     from nex_emergent_wants import reject_drive
#     reject_drive(pid)
#     await query.answer("Drive rejected ❌")


if __name__ == "__main__":
    import sys
    if "--approve" in sys.argv:
        pid = sys.argv[sys.argv.index("--approve") + 1]
        approve_drive(pid)
    elif "--reject" in sys.argv:
        pid = sys.argv[sys.argv.index("--reject") + 1]
        reject_drive(pid)
    elif "--daemon" in sys.argv:
        _log("Starting emergent want daemon — scanning every 6 hours")
        while True:
            try:
                scan_and_propose()
            except Exception as e:
                _log(f"[daemon] error: {e}")
            time.sleep(6 * 3600)
    else:
        proposals = scan_and_propose()
        if proposals:
            print(f"\n{len(proposals)} want(s) proposed.")
        else:
            print("No novel wants detected.")
