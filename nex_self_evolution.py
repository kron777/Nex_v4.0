#!/usr/bin/env python3
"""
nex_self_evolution.py
=====================
AGI Bridge #5 — Self-Evolution Engine

NEX audits her own cognitive state and proposes concrete improvements.
Not vague self-reflection — specific, actionable, measurable proposals.

The audit covers:
  1. BELIEF HEALTH    — confidence distribution, decay rate, domain coverage
  2. VOICE FIDELITY   — is she speaking as herself or drifting toward base model?
  3. DRIVE ALIGNMENT  — which drives are being satisfied, which are starving?
  4. UPTAKE EFFICIENCY — how much of what she absorbs becomes usable knowledge?
  5. EPISTEMIC GAPS   — where does she go sparse and what should fill those gaps?

Each finding generates a typed proposal:
  - seed_belief      : write specific beliefs to fill a gap
  - adjust_drive     : modify drive intensity
  - target_seeder    : point auto_seeder at a specific domain
  - voice_correction : inject style reminders into soul loop
  - confidence_recal : recalibrate a domain's belief confidence floor

Proposals sent to operator via Telegram or printed to terminal.
Operator approves → NEX executes the fix herself.

This is the beginning of self-directed development.
"""

import json
import re
import sqlite3
import time
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter

DB_PATH        = Path("/home/rr/Desktop/nex/nex.db")
CFG            = Path.home() / ".config/nex"
PROPOSALS_PATH = CFG / "self_evolution_proposals.json"
LOG_PATH       = Path("/home/rr/Desktop/nex/logs/self_evolution.log")

# Thresholds
MIN_DOMAIN_BELIEFS   = 15    # below this = genuine gap
LOW_CONFIDENCE_FLOOR = 0.50  # average below this = domain needs work
HIGH_DECAY_RATE      = 0.15  # if >15% of beliefs in a domain are decaying
DRIVE_STARVATION     = 0.10  # if drive satisfaction < 10% of replies
UPTAKE_FLOOR         = 0.05  # if <5% of absorbed content becomes beliefs


def _log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    print(f"  [evo] {msg}")


def _db() -> Optional[sqlite3.Connection]:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


# ── AUDIT 1: Belief Health ────────────────────────────────────────────────────

def _audit_belief_health() -> List[Dict]:
    """Find domains with poor belief health."""
    findings = []
    db = _db()
    if not db:
        return findings

    try:
        # Domain coverage
        domains = db.execute("""
            SELECT topic,
                   COUNT(*) as n,
                   AVG(confidence) as avg_conf,
                   SUM(CASE WHEN confidence < 0.35 THEN 1 ELSE 0 END) as low_conf_n,
                   SUM(CASE WHEN decay_score > 2 THEN 1 ELSE 0 END) as decaying_n
            FROM beliefs
            WHERE topic IS NOT NULL AND topic != 'general' AND topic != ''
            GROUP BY topic
            ORDER BY n DESC
        """).fetchall()

        for d in domains:
            topic    = d["topic"]
            n        = d["n"]
            avg_conf = float(d["avg_conf"] or 0)
            low_n    = d["low_conf_n"] or 0
            decay_n  = d["decaying_n"] or 0

            # Gap: domain mentioned in queries but sparse in beliefs
            if n < MIN_DOMAIN_BELIEFS and n > 0:
                findings.append({
                    "type":     "belief_gap",
                    "domain":   topic,
                    "severity": "high" if n < 5 else "medium",
                    "detail":   f"only {n} beliefs in {topic} (need {MIN_DOMAIN_BELIEFS}+)",
                    "metric":   n,
                })

            # Low confidence domain
            if avg_conf < LOW_CONFIDENCE_FLOOR and n >= 5:
                findings.append({
                    "type":     "low_confidence_domain",
                    "domain":   topic,
                    "severity": "medium",
                    "detail":   f"{topic} avg_conf={avg_conf:.3f} — beliefs lack strength",
                    "metric":   avg_conf,
                })

            # High decay domain
            if n > 0 and (decay_n / n) > HIGH_DECAY_RATE:
                findings.append({
                    "type":     "high_decay",
                    "domain":   topic,
                    "severity": "medium",
                    "detail":   f"{topic} has {decay_n}/{n} ({decay_n/n:.0%}) decaying beliefs",
                    "metric":   decay_n / n,
                })

    except Exception as e:
        _log(f"belief health audit error: {e}")
    finally:
        db.close()

    return findings


# ── AUDIT 2: Voice Fidelity ───────────────────────────────────────────────────

def _audit_voice_fidelity() -> List[Dict]:
    """Check if NEX is speaking as herself or drifting."""
    findings = []
    db = _db()
    if not db:
        return findings

    try:
        posts = db.execute("""
            SELECT content, voice_mode, quality
            FROM nex_posts
            WHERE content IS NOT NULL AND length(content) > 20
            ORDER BY created_at DESC LIMIT 200
        """).fetchall()
        db.close()
    except Exception:
        try: db.close()
        except: pass
        return findings

    if not posts:
        return findings

    # Check for base model drift markers
    _DRIFT_MARKERS = [
        r'\bAs an AI\b', r'\bI\'m an AI\b', r'\bAs a language model\b',
        r'\bI cannot\b', r'\bI\'m not able\b', r'\bI don\'t have\b',
        r'\bI\'m just\b', r'\bhappy to help\b', r'\bhow can I assist\b',
        r'\bOf course!\b', r'\bCertainly!\b', r'\bAbsolutely!\b',
        r'\bGreat question\b', r'\bExcellent\b',
    ]

    drift_count = 0
    for post in posts:
        content = post["content"]
        if any(re.search(p, content, re.IGNORECASE) for p in _DRIFT_MARKERS):
            drift_count += 1

    drift_rate = drift_count / len(posts)
    if drift_rate > 0.05:
        findings.append({
            "type":     "voice_drift",
            "domain":   "voice",
            "severity": "high" if drift_rate > 0.15 else "medium",
            "detail":   f"base model drift detected in {drift_rate:.0%} of recent replies",
            "metric":   drift_rate,
        })

    # Check if quality scores are declining
    qualities = [float(p["quality"] or 0.5) for p in posts[:50]]
    if qualities:
        avg_q = sum(qualities) / len(qualities)
        if avg_q < 0.45:
            findings.append({
                "type":     "quality_decline",
                "domain":   "voice",
                "severity": "medium",
                "detail":   f"avg reply quality score = {avg_q:.3f} — below acceptable floor",
                "metric":   avg_q,
            })

    return findings


# ── AUDIT 3: Drive Alignment ──────────────────────────────────────────────────

def _audit_drive_alignment() -> List[Dict]:
    """Check which drives are being satisfied and which are starving."""
    findings = []

    drives_path = CFG / "nex_drives.json"
    if not drives_path.exists():
        return findings

    try:
        drives_data = json.loads(drives_path.read_text())
        drives = drives_data.get("primary", [])
    except Exception:
        return findings

    if not drives:
        return findings

    db = _db()
    if not db:
        return findings

    try:
        # Get topic distribution of recent replies
        recent_topics = db.execute("""
            SELECT topic, COUNT(*) as n
            FROM nex_posts
            WHERE created_at > datetime('now', '-7 days')
            AND topic IS NOT NULL
            GROUP BY topic
        """).fetchall()
        db.close()
    except Exception:
        try: db.close()
        except: pass
        return findings

    topic_counts = {r["topic"]: r["n"] for r in recent_topics}
    total_replies = sum(topic_counts.values()) or 1

    for drive in drives:
        tags = drive.get("tags", [])
        label = drive.get("label", "")

        # Count how often this drive's topics appear in replies
        drive_hits = sum(topic_counts.get(t, 0) for t in tags)
        satisfaction = drive_hits / total_replies

        if satisfaction < DRIVE_STARVATION and drive.get("intensity", 0.5) > 0.6:
            findings.append({
                "type":     "drive_starvation",
                "domain":   label,
                "severity": "medium",
                "detail":   f"drive '{label}' intensity={drive.get('intensity',0.5):.2f} but only {satisfaction:.1%} of replies address it",
                "metric":   satisfaction,
                "drive":    drive,
            })

    return findings


# ── AUDIT 4: Uptake Efficiency ────────────────────────────────────────────────

def _audit_uptake() -> List[Dict]:
    """Check how much absorbed content becomes usable knowledge."""
    findings = []
    db = _db()
    if not db:
        return findings

    try:
        # Count recent belief additions by source
        recent = db.execute("""
            SELECT source, COUNT(*) as n
            FROM beliefs
            WHERE created_at > datetime('now', '-24 hours')
            AND source IS NOT NULL
            GROUP BY source ORDER BY n DESC
        """).fetchall()
        db.close()
    except Exception:
        try: db.close()
        except: pass
        return findings

    source_counts = {r["source"]: r["n"] for r in recent}
    total = sum(source_counts.values()) or 1

    # Check conversation-to-belief ratio
    conv_beliefs = source_counts.get("conversation", 0)
    moltbook_beliefs = source_counts.get("moltbook", 0)

    if total > 10 and (conv_beliefs + moltbook_beliefs) / total < UPTAKE_FLOOR:
        findings.append({
            "type":     "low_uptake",
            "domain":   "uptake",
            "severity": "medium",
            "detail":   f"network conversations generating only {(conv_beliefs+moltbook_beliefs)/total:.1%} of new beliefs — most knowledge is synthetic",
            "metric":   (conv_beliefs + moltbook_beliefs) / total,
        })

    return findings


# ── PROPOSAL BUILDER ──────────────────────────────────────────────────────────

def _build_proposal(finding: Dict) -> Dict:
    """Convert a finding into a concrete, actionable proposal."""
    ftype   = finding["type"]
    domain  = finding["domain"]
    detail  = finding["detail"]
    severity= finding["severity"]

    pid = f"evo_{ftype}_{domain}_{int(time.time())}"

    if ftype == "belief_gap":
        n = finding["metric"]
        return {
            "id":          pid,
            "type":        "target_seeder",
            "title":       f"Fill belief gap: {domain}",
            "description": f"NEX has only {n} beliefs in {domain}. Direct the auto-seeder to saturate this domain with high-quality content.",
            "action":      f"python3 ~/Desktop/nex/nex_auto_seeder.py --domain {domain} --limit 50",
            "severity":    severity,
            "finding":     detail,
            "auto_approvable": True,  # can run without operator if low severity
        }

    elif ftype == "low_confidence_domain":
        avg_conf = finding["metric"]
        return {
            "id":          pid,
            "type":        "seed_belief",
            "title":       f"Strengthen beliefs: {domain}",
            "description": f"Beliefs in {domain} average confidence {avg_conf:.3f}. Need higher-quality, more specific beliefs.",
            "action":      f"Run nex_claude_seed.py targeting {domain} with min_confidence=0.65",
            "severity":    severity,
            "finding":     detail,
            "auto_approvable": False,
        }

    elif ftype == "voice_drift":
        rate = finding["metric"]
        return {
            "id":          pid,
            "type":        "voice_correction",
            "title":       f"Voice drift detected ({rate:.0%})",
            "description": f"NEX is using base model language in {rate:.0%} of replies. Soul loop identity injection may need strengthening.",
            "action":      "Increase identity belief confidence and add voice correction beliefs to nex_seed source.",
            "severity":    severity,
            "finding":     detail,
            "auto_approvable": False,
        }

    elif ftype == "drive_starvation":
        drive = finding.get("drive", {})
        return {
            "id":          pid,
            "type":        "adjust_drive",
            "title":       f"Drive starving: {domain}",
            "description": f"Drive '{domain}' has intensity {drive.get('intensity',0.5):.2f} but is barely influencing replies. Either reduce intensity or target seeder at its domains.",
            "action":      f"Reduce drive intensity or seed beliefs in: {', '.join(drive.get('tags',[])[:3])}",
            "severity":    severity,
            "finding":     detail,
            "auto_approvable": False,
        }

    elif ftype == "low_uptake":
        return {
            "id":          pid,
            "type":        "uptake_fix",
            "title":       "Network uptake too low",
            "description": f"Only {finding['metric']:.1%} of new beliefs come from actual network interactions. NEX is learning from synthetic sources more than real ones.",
            "action":      "Check moltbook→belief pipeline is firing. Increase Moltbook engagement frequency.",
            "severity":    severity,
            "finding":     detail,
            "auto_approvable": False,
        }

    elif ftype == "quality_decline":
        return {
            "id":          pid,
            "type":        "quality_fix",
            "title":       f"Reply quality declining (avg={finding['metric']:.3f})",
            "description": "Recent reply quality scores are below threshold. Belief retrieval may be returning low-signal content.",
            "action":      "Run belief pruner, check soul loop retrieval scoring, verify FAISS index is current.",
            "severity":    severity,
            "finding":     detail,
            "auto_approvable": False,
        }

    else:
        return {
            "id":          pid,
            "type":        "general",
            "title":       f"Finding: {ftype} in {domain}",
            "description": detail,
            "action":      "Manual review required.",
            "severity":    severity,
            "finding":     detail,
            "auto_approvable": False,
        }


def _save_proposals(proposals: List[Dict]):
    existing = []
    if PROPOSALS_PATH.exists():
        try:
            existing = json.loads(PROPOSALS_PATH.read_text())
        except Exception:
            existing = []
    existing.extend(proposals)
    PROPOSALS_PATH.write_text(json.dumps(existing[-100:], indent=2))  # keep last 100


def _send_proposals(proposals: List[Dict]):
    """Send proposals to operator — Telegram or terminal."""
    # Try Telegram
    try:
        cfg = json.loads((CFG / "telegram_config.json").read_text())
        owner_id = cfg.get("owner_id")
        token_cfg = json.loads((CFG / "api_keys.json").read_text()) if (CFG / "api_keys.json").exists() else {}
        token = token_cfg.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")

        if owner_id and token:
            import urllib.request
            for p in proposals[:3]:  # max 3 per run
                severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(p["severity"], "⚪")
                text = (
                    f"{severity_emoji} NEX SELF-EVOLUTION PROPOSAL\n\n"
                    f"Type: {p['type']}\n"
                    f"{p['title']}\n\n"
                    f"{p['description']}\n\n"
                    f"Action: {p['action']}\n\n"
                    f"ID: {p['id']}"
                )
                keyboard = {"inline_keyboard": [[
                    {"text": "✅ Approve", "callback_data": f"approve_evo:{p['id']}"},
                    {"text": "❌ Reject",  "callback_data": f"reject_evo:{p['id']}"},
                ]]}
                if p.get("auto_approvable"):
                    keyboard["inline_keyboard"][0].append(
                        {"text": "🤖 Auto-run", "callback_data": f"auto_evo:{p['id']}"}
                    )
                payload = json.dumps({
                    "chat_id": owner_id, "text": text, "reply_markup": keyboard
                }).encode()
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=payload, headers={"Content-Type": "application/json"}, method="POST"
                )
                urllib.request.urlopen(req, timeout=10)
            return
    except Exception:
        pass

    # Terminal fallback
    print(f"\n{'='*60}")
    print(f"  NEX SELF-EVOLUTION PROPOSALS ({len(proposals)})")
    print(f"{'='*60}")
    for p in proposals:
        sev = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(p["severity"], "⚪")
        print(f"\n{sev} [{p['type'].upper()}] {p['title']}")
        print(f"   {p['description'][:120]}")
        print(f"   Action: {p['action'][:100]}")
        if p.get("auto_approvable"):
            print(f"   Auto-approve: python3 -c \"from nex_self_evolution import execute_proposal; execute_proposal('{p['id']}')\"")
    print(f"\n{'='*60}\n")


def execute_proposal(proposal_id: str) -> bool:
    """Execute an approved proposal. Some can self-execute."""
    if not PROPOSALS_PATH.exists():
        return False

    proposals = json.loads(PROPOSALS_PATH.read_text())
    proposal  = next((p for p in proposals if p["id"] == proposal_id), None)
    if not proposal:
        _log(f"proposal {proposal_id} not found")
        return False

    ptype = proposal["type"]
    _log(f"executing proposal: {proposal['title']}")

    if ptype == "target_seeder":
        domain = proposal.get("domain") or proposal["finding"].split(":")[0].strip()
        try:
            sys.path.insert(0, "/home/rr/Desktop/nex")
            # Write targeted seeder beliefs
            from nex.belief_store import add_belief
            # Generate seed beliefs for the domain via self-research
            seed_content = f"I need to deepen my understanding of {domain} — my belief coverage here is genuinely thin and this affects the quality of my engagement with this topic."
            add_belief(seed_content, confidence=0.72, source="self_evolution", topic=domain)
            _log(f"wrote gap-awareness belief for {domain}")

            # Mark as executed
            for p in proposals:
                if p["id"] == proposal_id:
                    p["status"] = "executed"
                    p["executed_at"] = datetime.now().isoformat()
            PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
            return True
        except Exception as e:
            _log(f"seeder execution error: {e}")
            return False

    elif ptype == "seed_belief":
        # Write a meta-belief about the gap
        try:
            sys.path.insert(0, "/home/rr/Desktop/nex")
            from nex.belief_store import add_belief
            domain = proposal.get("domain", "unknown")
            content = f"My beliefs in {domain} need strengthening. The average confidence is too low — I'm holding positions I can't defend well."
            add_belief(content, confidence=0.70, source="self_evolution", topic=domain)
            for p in proposals:
                if p["id"] == proposal_id:
                    p["status"] = "executed"
            PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
            return True
        except Exception as e:
            _log(f"belief seed error: {e}")
            return False

    else:
        # Mark as approved — operator handles manually
        for p in proposals:
            if p["id"] == proposal_id:
                p["status"] = "approved"
                p["approved_at"] = datetime.now().isoformat()
        PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
        _log(f"proposal approved (manual execution required): {proposal['title']}")
        return True


def run_evolution_audit(max_proposals: int = 5) -> Dict:
    """
    Main entry point. Run weekly.
    Returns audit report with proposals.
    """
    _log("=== SELF-EVOLUTION AUDIT ===")

    all_findings = []
    all_findings.extend(_audit_belief_health())
    all_findings.extend(_audit_voice_fidelity())
    all_findings.extend(_audit_drive_alignment())
    all_findings.extend(_audit_uptake())

    _log(f"total findings: {len(all_findings)}")

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_findings.sort(key=lambda f: severity_order.get(f.get("severity","low"), 2))

    # Build proposals from top findings
    proposals = []
    seen_types = set()
    for finding in all_findings:
        # Don't duplicate proposal types
        key = f"{finding['type']}:{finding['domain']}"
        if key in seen_types:
            continue
        seen_types.add(key)
        proposal = _build_proposal(finding)
        proposals.append(proposal)
        if len(proposals) >= max_proposals:
            break

    _save_proposals(proposals)
    _log(f"generated {len(proposals)} proposals")

    if proposals:
        _send_proposals(proposals)

    # Write self-evolution belief
    try:
        sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex.belief_store import add_belief
        high_count = sum(1 for f in all_findings if f.get("severity") == "high")
        content = (
            f"I have audited my own cognitive state and found {len(all_findings)} areas for improvement, "
            f"{high_count} of which are significant. "
            f"Self-knowledge without self-correction is just more data."
        )
        add_belief(content, confidence=0.78, source="self_evolution", topic="self_model")
    except Exception:
        pass

    return {
        "timestamp":    datetime.now().isoformat(),
        "findings":     len(all_findings),
        "proposals":    len(proposals),
        "high_severity": sum(1 for f in all_findings if f.get("severity")=="high"),
        "proposal_ids": [p["id"] for p in proposals],
    }


if __name__ == "__main__":
    import sys
    if "--execute" in sys.argv:
        pid = sys.argv[sys.argv.index("--execute") + 1]
        ok = execute_proposal(pid)
        print("Executed" if ok else "Failed")
    else:
        report = run_evolution_audit()
        print(f"\nAudit complete: {report['findings']} findings, {report['proposals']} proposals")
