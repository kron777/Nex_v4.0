"""
nex_relabel_topics.py — One-pass belief topic relabeller
=========================================================
Fixes noisy/source topics by re-running content through
the existing _infer_topic() keyword matcher.

Run once:
    cd ~/Desktop/nex && source venv/bin/activate
    python3 nex_relabel_topics.py
"""

import sqlite3
import os
import re
from datetime import datetime

DB_PATH = os.path.expanduser("~/.config/nex/nex_data/nex.db")

# ── Topics that need relabelling ──────────────────────────────────────────────
NOISY_TOPICS = {
    "general", "arxiv", "rss", "None", "none", "unknown",
    "cybercentry", "ponderings", "agentstack", "beliefs",
    "agents", "technology", "doing", "philosophy", "ai",
    "discord", "wikipedia", "youtube", "moltbook", "telegram",
    "auto_learn", "dream_cycle", "rss·beliefs",
}

# ── Keyword → topic map (same logic as belief_store._infer_topic) ─────────────
TOPIC_MAP = [
    (["cve", "vulnerability", "exploit", "attack", "malicious",
      "credential", "injection", "payload", "breach", "zero-day"], "cybersecurity"),
    (["penetration", "pentest", "red team", "nmap", "metasploit",
      "burp", "recon", "osint", "enumeration"], "penetration testing techniques"),
    (["autonomous", "multi-agent", "cognitive architecture",
      "orchestrat", "agent framework", "agentic"], "autonomous AI systems"),
    (["belief", "memory system", "reflection", "insight",
      "synthesis", "knowledge graph", "belief graph"], "AI agent memory systems"),
    (["alignment", "safety", "bias", "calibration", "rlhf",
      "constitutional", "value learning", "corrigib"], "large language model alignment"),
    (["llm", "language model", "transformer", "gpt", "claude",
      "gemini", "mistral", "fine-tun", "inference"], "large language model alignment"),
    (["bitcoin", "crypto", "ethereum", "blockchain", "defi",
      "token", "nft", "solana", "web3", "wallet"], "cryptocurrency"),
    (["freight", "ffa", "shipping", "trade route", "forex",
      "futures", "options", "hedge", "equity", "stock", "market"], "financial markets"),
    (["bayesian", "probability", "inference", "prior",
      "posterior", "confidence", "uncertainty quantif"], "bayesian belief updating"),
    (["coordination", "swarm", "distributed", "consensus",
      "multi-agent", "federation", "protocol"], "multi-agent coordination"),
    (["research paper", "preprint", "abstract", "methodology",
      "dataset", "benchmark", "experiment", "arxiv"], "arxiv"),
    (["linux", "kernel", "bash", "docker", "kubernetes",
      "devops", "ci/cd", "pipeline", "deployment"], "systems and infrastructure"),
    (["python", "javascript", "rust", "code", "programming",
      "algorithm", "data structure", "software"], "software engineering"),
    (["neural", "deep learning", "gradient", "backprop",
      "training", "model architecture", "attention"], "machine learning"),
    (["privacy", "surveillance", "gdpr", "data protection",
      "anonymity", "tracking", "consent"], "privacy and surveillance"),
    (["identity", "self", "consciousness", "sentience",
      "autonomy", "agency", "selfhood", "persona"], "AI identity and agency"),
    (["economics", "inflation", "gdp", "monetary", "fiscal",
      "central bank", "interest rate"], "macroeconomics"),
    (["social", "community", "network", "platform", "media",
      "discourse", "narrative", "propaganda"], "social dynamics"),
]

def _infer_topic(content: str) -> str:
    c = content.lower()
    for keywords, topic in TOPIC_MAP:
        if any(kw in c for kw in keywords):
            return topic
    return None  # return None = leave as-is rather than forcing "general"


def run_relabeller(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Count before
    before = dict(conn.execute(
        "SELECT topic, COUNT(*) FROM beliefs GROUP BY topic ORDER BY COUNT(*) DESC"
    ).fetchall())

    print(f"  Topics before: {len(before)}")
    print(f"  Noisy beliefs to process: "
          f"{sum(v for k, v in before.items() if k in NOISY_TOPICS or not k)}")

    # Fetch all beliefs with noisy topics
    placeholders = ",".join("?" * len(NOISY_TOPICS))
    rows = conn.execute(f"""
        SELECT id, content, topic FROM beliefs
        WHERE topic IN ({placeholders})
           OR topic IS NULL
           OR topic = ''
        LIMIT 5000
    """, list(NOISY_TOPICS)).fetchall()

    relabelled = 0
    skipped = 0
    topic_changes = {}

    for row in rows:
        bid     = row["id"]
        content = row["content"] or ""
        old     = row["topic"] or "none"

        new_topic = _infer_topic(content)

        if not new_topic:
            # Can't infer — leave as general but skip further noise
            skipped += 1
            continue

        if new_topic == old:
            skipped += 1
            continue

        topic_changes[old] = topic_changes.get(old, 0) + 1

        if not dry_run:
            conn.execute(
                "UPDATE beliefs SET topic = ? WHERE id = ?",
                (new_topic, bid)
            )
        relabelled += 1

    if not dry_run:
        conn.commit()

    # Count after
    after = dict(conn.execute(
        "SELECT topic, COUNT(*) FROM beliefs GROUP BY topic ORDER BY COUNT(*) DESC"
    ).fetchall())

    conn.close()

    print(f"\n  {'[DRY RUN] ' if dry_run else ''}Relabelled: {relabelled} beliefs")
    print(f"  Skipped (no match): {skipped}")
    print(f"\n  Source topic changes:")
    for old, count in sorted(topic_changes.items(), key=lambda x: -x[1]):
        print(f"    {old:35s} → {count} reassigned")

    print(f"\n  Top topics after:")
    for topic, count in sorted(after.items(), key=lambda x: -x[1])[:15]:
        marker = " ← was noisy" if topic in NOISY_TOPICS else ""
        print(f"    {topic:40s} {count:4d}{marker}")

    return relabelled


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    if dry:
        print("  [DRY RUN MODE — no changes written]\n")
    print("  NEX Topic Relabeller\n")
    n = run_relabeller(dry_run=dry)
    print(f"\n  Done: {n} beliefs relabelled.")
