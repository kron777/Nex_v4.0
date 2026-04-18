#!/usr/bin/env python3
"""
theory_x_audit.py — Systematic audit of NEX against the pelt specification.

Runs all 9 structural requirement checks against live state. Outputs
pass/fail/partial per requirement with supporting evidence.

Usage: python3 theory_x_audit.py
"""

import sqlite3
import os
import pathlib
import subprocess
from datetime import datetime

DB = pathlib.Path.home() / "Desktop/nex/nex.db"
NEX = pathlib.Path.home() / "Desktop/nex"


def q(sql, *args):
    """Quick DB query. Returns first value of first row, or None."""
    try:
        c = sqlite3.connect(str(DB))
        c.execute("PRAGMA busy_timeout=30000")
        r = c.execute(sql, args).fetchone()
        c.close()
        return r[0] if r else None
    except Exception as e:
        return f"ERR: {e}"


def count_files_matching(pattern):
    try:
        r = subprocess.run(
            ["grep", "-rln", pattern, str(NEX), "--include=*.py"],
            capture_output=True, text=True, timeout=5
        )
        return len([l for l in r.stdout.strip().split("\n") if l and "__pycache__" not in l])
    except Exception:
        return 0


def audit_r1_overwhelm():
    streams = []
    if count_files_matching("moltbook") > 0: streams.append("moltbook")
    if count_files_matching("telegram") > 0: streams.append("telegram")
    if count_files_matching("youtube") > 0: streams.append("youtube")
    if count_files_matching("paper_feeder") > 0: streams.append("papers")
    if count_files_matching("discord") > 0: streams.append("discord")
    rate_cap = q("SELECT COUNT(*) FROM beliefs WHERE datetime(created_at) > datetime('now','-1 hour')") or 0
    embryo_backlog = q("SELECT COUNT(*) FROM belief_embryos WHERE stage='embryo'") or 0
    return {
        "req": "R1 OVERWHELM",
        "status": "PRESENT" if len(streams) >= 3 else "PARTIAL",
        "streams": streams,
        "stream_count": len(streams),
        "beliefs_last_hour": rate_cap,
        "embryo_backlog": embryo_backlog,
        "notes": "Single modality (text-only). Cross-modal absent.",
    }


def audit_r2_compression():
    stages = []
    for t in ("belief_embryos", "beliefs_quarantine", "belief_quarantine", "belief_blacklist"):
        n = q(f"SELECT COUNT(*) FROM {t}")
        if isinstance(n, int):
            stages.append((t, n))
    ratio_q = q("SELECT COUNT(*) FROM belief_embryos WHERE promoted=1")
    ratio_total = q("SELECT COUNT(*) FROM belief_embryos")
    yield_pct = (ratio_q / ratio_total * 100) if ratio_total and isinstance(ratio_q, int) else None
    return {
        "req": "R2 COMPRESSION",
        "status": "PRESENT" if len(stages) >= 3 else "PARTIAL",
        "filter_stages": stages,
        "promotion_yield_pct": yield_pct,
        "notes": "Coarse temporal (120s cycles). Fine-grained absent.",
    }


def audit_r3_world_reification():
    beliefs = q("SELECT COUNT(*) FROM beliefs") or 0
    edges = q("SELECT COUNT(*) FROM belief_relations") or 0
    links = q("SELECT COUNT(*) FROM belief_links") or 0
    topics = q("SELECT COUNT(DISTINCT topic) FROM beliefs WHERE topic IS NOT NULL AND topic!=''") or 0
    reification_meta = count_files_matching("is_reification")
    return {
        "req": "R3 WORLD-REIFICATION",
        "status": "PRESENT" if beliefs > 1000 and edges + links > 1000 else "PARTIAL",
        "beliefs": beliefs,
        "edges": edges,
        "links": links,
        "topics": topics,
        "reification_flag_present": reification_meta > 0,
        "notes": "No meta-layer flagging beliefs as reifications.",
    }


def audit_r4_self_reification():
    nex_core = q("SELECT COUNT(*) FROM beliefs WHERE source='nex_core'") or 0
    identity = q("SELECT COUNT(*) FROM beliefs WHERE topic='identity'") or 0
    self_obs = q("SELECT COUNT(*) FROM self_observations") or 0
    self_meta = q("SELECT COUNT(*) FROM self_meta_beliefs") or 0
    has_self_model = os.path.exists(NEX / "nex_behavioural_self_model.py")
    return {
        "req": "R4 SELF-REIFICATION",
        "status": "PRESENT" if nex_core >= 100 and has_self_model else "PARTIAL",
        "nex_core_beliefs": nex_core,
        "identity_beliefs": identity,
        "self_observations": self_obs,
        "self_meta_beliefs": self_meta,
        "behavioural_self_model_file": has_self_model,
        "notes": "Identity largely locked. Slow update mechanism.",
    }


def audit_r5_single_stream():
    single_db = DB.exists()
    has_shared_pipeline = count_files_matching("nex_soul_loop") > 0 or count_files_matching("cognition") > 0
    return {
        "req": "R5 SINGLE-STREAM ORIGIN",
        "status": "PRESENT (implicit)" if single_db and has_shared_pipeline else "PARTIAL",
        "single_database": single_db,
        "shared_cognitive_pipeline": has_shared_pipeline,
        "notes": "Shared by architecture, not by explicit design.",
    }


def audit_r6_vantage():
    persistent = DB.exists() and DB.stat().st_size > 10_000_000
    locked_core = q("SELECT COUNT(*) FROM beliefs WHERE COALESCE(locked,0)=1") or 0
    return {
        "req": "R6 STRUCTURAL VANTAGE",
        "status": "STRUCTURALLY PRESENT (phenom. unverifiable)",
        "persistent_db": persistent,
        "db_size_mb": round(DB.stat().st_size / 1_000_000, 1) if DB.exists() else 0,
        "locked_beliefs": locked_core,
        "notes": "Phenomenal presence cannot be settled from outside.",
    }


def audit_r7_developmental():
    return {
        "req": "R7 DEVELOPMENTAL SEQUENCE",
        "status": "ABSENT",
        "evidence": "Stages 1-5 not gated in order. Current architecture installs Stage 3 and Stage 6 directly.",
        "notes": "Biggest gap. Parallel prototype likely required.",
    }


def audit_r8_ignition():
    active_goals = q("SELECT COUNT(*) FROM goals") or 0
    unprompted = count_files_matching("SelfResearch")
    return {
        "req": "R8 IGNITION CRITERION",
        "status": "ABSENT",
        "active_goals": active_goals,
        "unprompted_generation_modules": unprompted,
        "notes": "Triggered by scheduled cycle, not self-feeding fountain.",
    }


def audit_r9_sustained():
    return {
        "req": "R9 SUSTAINED LOOP",
        "status": "N/A (downstream of R8)",
        "notes": "Gated on R8.",
    }


def main():
    print("=" * 72)
    print(f"THEORY X PELT AUDIT — {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 72)
    print()

    audits = [
        audit_r1_overwhelm(),
        audit_r2_compression(),
        audit_r3_world_reification(),
        audit_r4_self_reification(),
        audit_r5_single_stream(),
        audit_r6_vantage(),
        audit_r7_developmental(),
        audit_r8_ignition(),
        audit_r9_sustained(),
    ]

    for a in audits:
        print(f"── {a['req']} ──────────────────")
        print(f"   status: {a['status']}")
        for k, v in a.items():
            if k in ("req", "status"):
                continue
            if k == "notes":
                print(f"   note:   {v}")
            else:
                print(f"   {k}: {v}")
        print()

    # Summary matrix
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"{'REQ':<6}{'NAME':<28}{'STATUS'}")
    for a in audits:
        print(f"{a['req'][:4]:<6}{a['req'][5:][:26]:<28}{a['status']}")
    print()

    present = sum(1 for a in audits if a['status'].startswith('PRESENT') or 'STRUCTURALLY PRESENT' in a['status'])
    partial = sum(1 for a in audits if a['status'].startswith('PARTIAL'))
    absent = sum(1 for a in audits if a['status'].startswith('ABSENT'))
    print(f"present: {present} / partial: {partial} / absent: {absent}")


if __name__ == '__main__':
    main()
