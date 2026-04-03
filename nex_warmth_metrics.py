#!/usr/bin/env python3
"""
nex_warmth_metrics.py
System health dashboard for NEX warmth + belief loop.

Tracks:
  - warm_coverage_ratio
  - belief_growth_rate
  - novelty_decay_rate
  - contradiction_density
  - tension_pair_count
  - propagation_efficiency

Alerts if system drifts outside healthy ranges.
"""
import sqlite3, json, time
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path.home() / "Desktop/nex/nex.db"

ALERT_THRESHOLDS = {
    "contradiction_density": 0.15,
    "novelty_decay_rate":    0.20,
    "warm_coverage_ratio":   0.05,
    "belief_growth_rate":    5000,
}


def get_metrics(db) -> dict:
    m = {}

    total_tags = db.execute("SELECT COUNT(*) FROM word_tags").fetchone()[0]
    warm_tags  = db.execute("SELECT COUNT(*) FROM word_tags WHERE w >= 0.40").fetchone()[0]
    core_tags  = db.execute("SELECT COUNT(*) FROM word_tags WHERE w >= 0.80").fetchone()[0]
    hot_tags   = db.execute("SELECT COUNT(*) FROM word_tags WHERE w >= 0.60").fetchone()[0]
    queue_size = db.execute("SELECT COUNT(*) FROM warming_queue").fetchone()[0]
    m["total_tagged"]        = total_tags
    m["warm_coverage_ratio"] = round(warm_tags / max(total_tags, 1), 3)
    m["core_count"]          = core_tags
    m["hot_count"]           = hot_tags
    m["warm_count"]          = warm_tags - core_tags - hot_tags
    m["queue_size"]          = queue_size

    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    m["belief_growth_24h"] = db.execute(
        "SELECT COUNT(*) FROM beliefs WHERE created_at >= ?", (cutoff,)
    ).fetchone()[0]
    m["total_beliefs"] = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]

    m["warmth_generated_beliefs"] = db.execute(
        "SELECT COUNT(*) FROM beliefs WHERE source LIKE '%warmth%' OR source LIKE '%tension%'"
    ).fetchone()[0]

    try:
        m["tension_pairs"] = db.execute("SELECT COUNT(*) FROM tension_graph").fetchone()[0]
        m["strong_tension_pairs"] = db.execute(
            "SELECT COUNT(*) FROM tension_graph WHERE strength >= 0.5"
        ).fetchone()[0]
    except Exception:
        m["tension_pairs"] = 0
        m["strong_tension_pairs"] = 0

    try:
        conflict_count = db.execute(
            "SELECT COUNT(*) FROM belief_relations WHERE relation_type='opposing'"
        ).fetchone()[0]
        m["contradiction_density"] = round(conflict_count / max(m["total_beliefs"], 1), 4)
    except Exception:
        m["contradiction_density"] = 0.0

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        recent_warmth = db.execute(
            "SELECT COUNT(*) FROM beliefs WHERE source LIKE '%warmth%' AND created_at >= ?",
            (week_ago,)
        ).fetchone()[0]
        recent_total = db.execute(
            "SELECT COUNT(*) FROM beliefs WHERE created_at >= ?", (week_ago,)
        ).fetchone()[0]
        m["novelty_rate_7d"] = round(recent_warmth / max(recent_total, 1), 3)
    except Exception:
        m["novelty_rate_7d"] = 0.0

    m["propagation_lifted"] = db.execute(
        "SELECT COUNT(*) FROM word_tags WHERE w > 0 AND warming_history IS NULL"
    ).fetchone()[0]

    return m


def check_alerts(m: dict) -> list:
    alerts = []
    if m["contradiction_density"] > ALERT_THRESHOLDS["contradiction_density"]:
        alerts.append(f"ALERT: contradiction_density={m['contradiction_density']:.3f} > 0.15")
    if m["warm_coverage_ratio"] < ALERT_THRESHOLDS["warm_coverage_ratio"]:
        alerts.append(f"ALERT: warm_coverage={m['warm_coverage_ratio']:.3f} below 5%")
    if m["belief_growth_24h"] > ALERT_THRESHOLDS["belief_growth_rate"]:
        alerts.append(f"ALERT: belief_growth_24h={m['belief_growth_24h']} — possible runaway")
    if m.get("novelty_rate_7d", 1.0) < ALERT_THRESHOLDS["novelty_decay_rate"]:
        alerts.append(f"ALERT: novelty_rate_7d={m['novelty_rate_7d']:.3f} — novelty decaying")
    return alerts


def print_dashboard(m: dict, alerts: list):
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep = "=" * 55
    print()
    print(sep)
    print(f"  NEX WARMTH + BELIEF METRICS  [{ts}]")
    print(sep)
    print()
    print("WORD WARMING")
    print(f"  Total tagged:      {m['total_tagged']:,}")
    print(f"  Core  (>=0.80):    {m['core_count']:,}")
    print(f"  Hot   (>=0.60):    {m['hot_count']:,}")
    print(f"  Warm  (>=0.40):    {m['warm_count']:,}")
    print(f"  Coverage ratio:    {m['warm_coverage_ratio']:.1%}")
    print(f"  Queue pending:     {m['queue_size']:,}")
    print(f"  Propagation lift:  {m['propagation_lifted']:,} words")
    print()
    print("BELIEF GRAPH")
    print(f"  Total beliefs:     {m['total_beliefs']:,}")
    print(f"  Growth (24h):      +{m['belief_growth_24h']:,}")
    print(f"  Warmth-generated:  {m['warmth_generated_beliefs']:,}")
    print(f"  Novelty rate (7d): {m['novelty_rate_7d']:.1%}")
    print(f"  Contradiction den: {m['contradiction_density']:.3%}")
    print()
    print("TENSION ENGINE")
    print(f"  Total pairs:       {m['tension_pairs']:,}")
    print(f"  Strong (>=0.5):    {m['strong_tension_pairs']:,}")
    print()
    if alerts:
        print("!" * 55)
        for a in alerts:
            print(f"  {a}")
        print("!" * 55)
    else:
        print("  System healthy — no alerts")
    print(sep)
    print()


if __name__ == "__main__":
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    m = get_metrics(db)
    alerts = check_alerts(m)
    db.close()
    print_dashboard(m, alerts)
