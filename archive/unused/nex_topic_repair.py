#!/usr/bin/env python3
"""
nex_topic_repair.py — Topic Repair Cron Job
=============================================
Detects topics with < 10 beliefs and reseeds them from ArXiv.
Designed to run as a cron job at low-traffic hours.

Cron setup:
  crontab -e
  0 3 * * * cd /home/rr/Desktop/nex && source venv/bin/activate && python3 ~/Downloads/nex_topic_repair.py >> /tmp/nex_topic_repair.log 2>&1

Also repairs:
  - Removes remaining [merged:N] noise
  - Rebuilds beliefs.json atomically after repairs
  - Runs opinion refresh if beliefs changed significantly
"""

import sys, os, sqlite3, json, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path("~/Desktop/nex").expanduser()))

DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"
BF_PATH = Path("~/.config/nex/beliefs.json").expanduser()
MIN_BELIEFS_PER_TOPIC = 10

# Topics that need ArXiv queries if thin
TOPIC_QUERIES = {
    "free_will": [
        "free will determinism compatibilism philosophy",
        "libertarian free will moral responsibility agent causation",
        "neuroscience free will conscious decision Libet",
        "hard determinism compatibilism Frankfurt cases",
    ],
    "game_theory": [
        "game theory Nash equilibrium cooperation strategy",
        "mechanism design incentive compatibility social choice",
        "evolutionary game theory cooperation altruism",
        "multi agent cooperation coordination game theory",
        "prisoner dilemma cooperation defection game theory",
    ],
    "decision_theory": [
        "decision theory expected utility rational choice",
        "causal decision theory evidential Newcomb problem",
        "updateless decision theory timeless agents",
        "bounded rationality satisficing Herbert Simon",
    ],
    "political_philosophy": [
        "justice fairness political philosophy Rawls",
        "democracy legitimacy political authority consent",
        "liberalism rights individual liberty Mill",
        "social contract Locke Rousseau Hobbes political",
        "power structures governance institutions political",
    ],
    "metaphysics": [
        "metaphysics ontology existence properties",
        "persistence identity time four dimensionalism",
        "causation counterfactual dependence metaphysics",
        "abstract objects nominalism platonism",
        "emergence reduction levels explanation metaphysics",
    ],
    "corrigibility": [
        "corrigibility AI safety shutdown problem",
        "corrigible AI agent human oversight control",
        "interruptible AI agent corrigibility reinforcement",
    ],
    "deceptive_alignment": [
        "deceptive alignment mesa optimization inner alignment",
        "treacherous turn AI deceptive instrumental goal",
        "hidden goals AI systems deceptive behavior",
    ],
    "interpretability": [
        "mechanistic interpretability neural network circuits",
        "explainability AI transparency interpretable models",
        "probing classifier representation linear model",
        "feature visualization neural network understanding",
    ],
    "agency": [
        "agency autonomy rational action philosophy",
        "artificial agent autonomy goal directed behavior",
        "embedded agency decision theory environment",
        "intentional agency causation action philosophy",
    ],
}

# ─────────────────────────────────────────────────────────────
# Noise filter
# ─────────────────────────────────────────────────────────────

_NOISE = {
    "this paper", "in this paper", "we propose", "we present",
    "in this work", "our method", "our model", "et al.",
    "arxiv preprint", "seventeenth century", "eighteenth century",
    "algebra", "tensor product", "lemma ", " theorem ",
    "[merged:", "http://", "https://",
}

def _is_noise(text):
    t = text.lower()
    return any(n in t for n in _NOISE) or len(text) < 50 or len(text) > 380


# ─────────────────────────────────────────────────────────────
# ArXiv fetch with rate limit respect
# ─────────────────────────────────────────────────────────────

def fetch_arxiv(query, max_results=50, delay=4.0):
    """Fetch ArXiv abstracts with rate limit respect."""
    time.sleep(delay)
    q   = urllib.parse.quote(query)
    url = (f"https://export.arxiv.org/api/query?"
           f"search_query=all:{q}&start=0&max_results={max_results}&sortBy=relevance")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NEX/4.0 TopicRepair"})
        with urllib.request.urlopen(req, timeout=25) as r:
            xml_text = r.read().decode()
        root = ET.fromstring(xml_text)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        texts = []
        for entry in root.findall("atom:entry", ns):
            title   = (entry.findtext("atom:title","",ns) or "").strip().replace('\n',' ')
            summary = (entry.findtext("atom:summary","",ns) or "").strip().replace('\n',' ')
            if summary and len(summary) > 80:
                texts.append(f"{title}. {summary}")
        return texts
    except Exception as e:
        print(f"  [topic_repair] fetch error: {e}")
        return []


def extract_simple(text, max_b=3):
    """Simple sentence extractor."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.replace('\n',' '))
    _epist    = {'is','are','can','must','should','enables','requires','shows',
                 'suggests','demonstrates','indicates','argues','finds','holds',
                 'maintains','defines','explains','challenges','reveals',
                 'determines','influences','underlies','emerges','affects'}
    _stop     = {'the','a','an','and','or','but','in','on','at','to','for',
                 'of','with','as','by','from','this','that','it','its'}
    _skip     = re.compile(r'^(This paper|In this paper|We |Our )')
    results   = []
    for s in sentences:
        s = s.strip()
        if _is_noise(s): continue
        if _skip.match(s): continue
        words = set(re.sub(r'[^a-z ]','',s.lower()).split()) - _stop
        if words & _epist:
            results.append(s)
        if len(results) >= max_b:
            break
    return results


# ─────────────────────────────────────────────────────────────
# Main repair logic
# ─────────────────────────────────────────────────────────────

def repair():
    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] NEX TOPIC REPAIR starting")

    con = sqlite3.connect(DB_PATH, timeout=15)
    start_count = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    inserted_total = 0

    # Step 1: Clean noise
    n_merged = con.execute("DELETE FROM beliefs WHERE content LIKE '%[merged:%'").rowcount
    n_noise  = con.execute(
        "DELETE FROM beliefs WHERE content LIKE '%http://%' OR content LIKE '%https://%'"
    ).rowcount
    con.commit()
    if n_merged + n_noise > 0:
        print(f"  Cleaned: {n_merged} [merged:N], {n_noise} URL beliefs")

    # Step 2: Check which topics are thin
    topic_counts = {}
    for (topic, cnt) in con.execute(
        "SELECT topic, COUNT(*) FROM beliefs WHERE topic IS NOT NULL GROUP BY topic"
    ).fetchall():
        topic_counts[topic] = cnt

    thin_topics = [
        t for t, queries in TOPIC_QUERIES.items()
        if topic_counts.get(t, 0) < MIN_BELIEFS_PER_TOPIC
    ]

    if not thin_topics:
        print(f"  All topics healthy (>= {MIN_BELIEFS_PER_TOPIC} beliefs each)")
    else:
        print(f"  Thin topics: {thin_topics}")

        # Step 3: Reseed thin topics
        for topic in thin_topics:
            queries  = TOPIC_QUERIES[topic]
            topic_n  = 0

            for query in queries:
                texts = fetch_arxiv(query, max_results=50, delay=5.0)
                for text in texts:
                    for belief in extract_simple(text, max_b=3):
                        if not _is_noise(belief):
                            try:
                                con.execute(
                                    "INSERT INTO beliefs "
                                    "(content,confidence,topic,source,timestamp) "
                                    "VALUES (?,?,?,?,?)",
                                    (belief, 0.68, topic, "topic_repair", time.time())
                                )
                                topic_n += 1
                                inserted_total += 1
                            except Exception:
                                pass
                con.commit()

            print(f"  {topic}: +{topic_n} beliefs")

    # Step 4: Rebuild beliefs.json if anything changed
    if inserted_total > 0 or n_merged > 0:
        rows = con.execute(
            "SELECT content, confidence, topic, source, timestamp "
            "FROM beliefs ORDER BY confidence DESC"
        ).fetchall()
        seen, out = set(), []
        for r in rows:
            if r[0] and r[0] not in seen:
                seen.add(r[0])
                out.append({
                    "content":    r[0],
                    "confidence": round(float(r[1] or 0.5), 4),
                    "tags":       [r[2]] if r[2] else [],
                    "source":     r[3] or "repair",
                    "timestamp":  float(r[4] or time.time()),
                })
        tmp = BF_PATH.parent / "beliefs.json.tmp"
        tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, BF_PATH)
        print(f"  beliefs.json rebuilt: {len(out)} beliefs")

    final = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    con.close()

    print(f"  Started: {start_count}  Inserted: {inserted_total}  Final: {final}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DONE\n")


if __name__ == "__main__":
    repair()
