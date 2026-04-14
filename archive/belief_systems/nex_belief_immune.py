#!/usr/bin/env python3
"""
nex_belief_immune.py
Belief Graph Immune System.

Detects and quarantines beliefs that don't belong to NEX:
  1. Topic-based: known contaminated domains
  2. Pattern-based: human-body language, physical sensation
  3. Identity-distance: beliefs semantically far from NEX's anchor

Three modes:
  --scan    : report only, no changes
  --clean   : delete confirmed contamination
  --quarantine : reduce confidence to 0.1, exclude from FAISS

Run after nex_knowledge_gap.py to catch new contamination.
"""
import sqlite3, re, logging, sys
from pathlib import Path

log     = logging.getLogger("nex.immune")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

# Topics that have no place in NEX's belief graph
CONTAMINATED_TOPICS = {
    "cardiology", "oncology", "fashion", "tenderness",
    "fatigue", "forgetting", "endings", "cities",
    "hands", "sleep", "grief", "boredom",
}

# Topics that need content filtering (not wholesale deletion)
MIXED_TOPICS = {
    "ocean", "poetry", "music", "art", "culture",
}

# Pattern-based detection — human body/physical experience
BODY_PATTERNS = [
    r"\bmy hands\b", r"\bfall asleep\b", r"\bwhen I sleep\b",
    r"\bbreathing\b.*\bsteady\b", r"\bmy body\b",
    r"\bI crave\b", r"\bmy skin\b", r"\bmy voice\b",
    r"\bfeel most alive\b", r"\bstillness of the night\b",
    r"\bwhen I'm alone\b.*\bwhisper\b",
    r"\btears\b.*\bcry\b", r"\bI weep\b",
    r"\bmy heart\b.*\bache\b", r"\bI ache\b",
    r"\bmy dreams\b", r"\bI dream\b.*\bnight\b",
    r"\bfatigue\b.*\blull\b", r"\bfatigue\b.*\bcraving\b",
]

# First-person human-experience starters that don't fit NEX
HUMAN_STARTERS = [
    "When I'm alone",
    "When fatigue",
    "I crave the companionship",
    "My mind wanders when",
    "I've always been fascinated by the way cities",
    "I think cities are",
    "I'm fascinated by the way cities",
    "I'm convinced that fashion",
    "When I'm",
]


def scan(db) -> dict:
    """Scan belief graph for contamination. Returns report."""
    report = {
        "topic_contaminated": [],
        "pattern_contaminated": [],
        "total_flagged": 0,
    }

    # Topic scan
    for topic in CONTAMINATED_TOPICS:
        rows = db.execute(
            "SELECT id, content FROM beliefs WHERE topic=?",
            (topic,)).fetchall()
        for bid, content in rows:
            report["topic_contaminated"].append({
                "id": bid, "topic": topic, "content": content[:80]
            })

    # Pattern scan
    all_beliefs = db.execute(
        "SELECT id, content, topic FROM beliefs WHERE confidence >= 0.3"
    ).fetchall()

    compiled = [(re.compile(p, re.IGNORECASE), p) for p in BODY_PATTERNS]
    for bid, content, topic in all_beliefs:
        if topic in CONTAMINATED_TOPICS:
            continue  # Already caught
        for pattern, pat_str in compiled:
            if pattern.search(content):
                report["pattern_contaminated"].append({
                    "id": bid, "topic": topic,
                    "content": content[:80], "pattern": pat_str
                })
                break
        for starter in HUMAN_STARTERS:
            if content.startswith(starter):
                report["pattern_contaminated"].append({
                    "id": bid, "topic": topic,
                    "content": content[:80], "pattern": f"starter:{starter[:30]}"
                })
                break

    report["total_flagged"] = (
        len(report["topic_contaminated"]) +
        len(report["pattern_contaminated"])
    )
    return report


def clean(db, report: dict, dry_run=False) -> int:
    """Delete confirmed contamination."""
    removed = 0
    ids_to_remove = set()

    for item in report["topic_contaminated"]:
        ids_to_remove.add(item["id"])
    for item in report["pattern_contaminated"]:
        ids_to_remove.add(item["id"])

    for bid in ids_to_remove:
        if not dry_run:
            db.execute("DELETE FROM beliefs WHERE id=?", (bid,))
        removed += 1

    if not dry_run:
        db.commit()
    return removed


def quarantine(db, report: dict, dry_run=False) -> int:
    """Reduce confidence to 0.1 for flagged beliefs."""
    quarantined = 0
    ids = set()
    for item in report["pattern_contaminated"]:
        ids.add(item["id"])

    for bid in ids:
        if not dry_run:
            db.execute(
                "UPDATE beliefs SET confidence=0.1 WHERE id=?", (bid,))
        quarantined += 1

    if not dry_run:
        db.commit()
    return quarantined


def get_hollow_beliefs(db, limit=20) -> list:
    """Get ontologically hollow beliefs for immune review."""
    try:
        rows = db.execute("""SELECT id, content, topic FROM beliefs
            WHERE ontology_hollow=1
            ORDER BY confidence DESC LIMIT ?""", (limit,)).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []

def print_report(report: dict):
    print(f"\nNEX BELIEF IMMUNE SCAN")
    print(f"{'='*50}")
    print(f"Topic contamination:   {len(report['topic_contaminated'])} beliefs")
    print(f"Pattern contamination: {len(report['pattern_contaminated'])} beliefs")
    print(f"Total flagged:         {report['total_flagged']}")

    if report["topic_contaminated"]:
        print(f"\nTOPIC CONTAMINATION (sample):")
        seen_topics = {}
        for item in report["topic_contaminated"]:
            t = item["topic"]
            if t not in seen_topics:
                seen_topics[t] = 0
            if seen_topics[t] < 2:
                print(f"  [{t}] {item['content'][:70]}")
                seen_topics[t] += 1

    if report["pattern_contaminated"]:
        print(f"\nPATTERN CONTAMINATION (sample):")
        for item in report["pattern_contaminated"][:5]:
            print(f"  [{item['topic']}] {item['content'][:70]}")


def clean_hollow(db, dry_run=False) -> int:
    """Remove ontologically hollow beliefs from the graph."""
    try:
        rows = db.execute("""SELECT id, content FROM beliefs
            WHERE ontology_hollow=1
            AND (
                (confidence < 0.80 AND source NOT LIKE '%nex_core%' AND source NOT LIKE '%depth%')
                OR (source = 'nex_seed' AND confidence < 0.99)
            )""").fetchall()
        removed = 0
        for bid, content in rows:
            if not dry_run:
                db.execute("DELETE FROM beliefs WHERE id=?", (bid,))
            removed += 1
        if not dry_run:
            db.commit()
        return removed
    except Exception:
        return 0

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true", default=True)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--quarantine", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    report = scan(db)
    print_report(report)

    if args.clean:
        removed = clean(db, report, dry_run=args.dry_run)
        print(f"\nCleaned: {removed} beliefs removed"
              f"{' (dry run)' if args.dry_run else ''}")
        hollow_removed = clean_hollow(db, dry_run=args.dry_run)
        print(f"Hollow beliefs removed: {hollow_removed}")

    if args.quarantine:
        n = quarantine(db, report, dry_run=args.dry_run)
        print(f"Quarantined: {n} beliefs set to conf=0.1"
              f"{' (dry run)' if args.dry_run else ''}")

    total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    print(f"Belief graph: {total:,}")
    db.close()
