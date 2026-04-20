#!/usr/bin/env python3
"""
nex_self_directed_research.py — Self-Directed Research Engine
==============================================================
NEX decides what to learn next based on:
  1. Her active drives (what she wants to understand)
  2. Her unresolved contradictions (what she's confused about)
  3. Topics where her confidence is lowest (where she's uncertain)
  4. Topics she discusses most but knows least (discourse gaps)

This is genuine autonomous curiosity — she picks her own
research agenda, generates ArXiv queries, and seeds the results.

Deploy to: ~/Desktop/nex/nex/nex_self_directed_research.py
Wire into: run.py REFLECT phase (every 24 hours)
"""

import sys, os, re, json, time, sqlite3, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict

CFG     = Path("~/.config/nex").expanduser()
DB_PATH = CFG / "nex.db"
BF_PATH = CFG / "beliefs.json"

MIN_BELIEFS_TO_TRIGGER = 3    # topic needs < this to trigger research
MAX_QUERIES_PER_RUN    = 14   # expanded — more topics per run
BELIEFS_PER_QUERY      = 5   # more beliefs per ArXiv query
REQUEST_DELAY          = 4.0  # seconds between requests

# ─────────────────────────────────────────────────────────────
# Noise filter
# ─────────────────────────────────────────────────────────────

_NOISE = {
    "this paper", "in this paper", "we propose", "we present",
    "in this work", "our method", "our model", "et al.",
    "[merged:", "http://", "https://", "arxiv preprint",
    "seventeenth century", "eighteenth century",
}

def _is_noise(text):
    t = text.lower()
    return any(n in t for n in _NOISE) or len(text) < 50 or len(text) > 380


# ─────────────────────────────────────────────────────────────
# Query generation from NEX's internal state
# ─────────────────────────────────────────────────────────────

def _db():
    con = sqlite3.connect(str(DB_PATH), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def get_drive_queries() -> list:
    """
    Generate research queries from NEX's active drives.
    Her drives tell us what she's trying to understand.
    """
    db = _db()
    queries = []
    try:
        drives_path = CFG / "nex_drives.json"
        if drives_path.exists():
            drives = json.loads(drives_path.read_text())
            active = drives.get("active", {})
            label  = active.get("label", "")
            if label:
                # Convert drive label to search query
                clean = re.sub(r'[^a-z0-9 ]', ' ', label.lower())
                words = [w for w in clean.split() if len(w) > 3][:5]
                if words:
                    queries.append({
                        "query":  " ".join(words) + " theory research",
                        "topic":  "_".join(words[:2]),
                        "reason": f"active drive: {label}",
                        "priority": 0.9,
                    })
    except Exception:
        pass
    finally:
        db.close()
    return queries


def get_contradiction_queries() -> list:
    """
    Generate queries to resolve NEX's most active contradictions.
    If she holds two conflicting beliefs, she should research the tension.
    """
    db  = _db()
    queries = []
    try:
        rows = db.execute(
            "SELECT belief_a, belief_b FROM contradiction_memory "
            "ORDER BY rowid DESC LIMIT 5"
        ).fetchall()
        for row in rows:
            a = row["belief_a"] or ""
            b = row["belief_b"] or ""
            if not a or not b:
                continue
            # Extract key terms from both sides
            _stop = {'the','a','an','and','or','is','are','was','not','but','in','of','to'}
            a_words = set(re.sub(r'[^a-z ]','',a.lower()).split()) - _stop
            b_words = set(re.sub(r'[^a-z ]','',b.lower()).split()) - _stop
            # Union of key terms from both sides
            all_words = list((a_words | b_words))[:6]
            if len(all_words) >= 3:
                query = " ".join(sorted(all_words, key=len, reverse=True)[:5])
                # Find a topic from existing beliefs matching these words
                topic = "epistemology"
                for (t,) in db.execute("SELECT DISTINCT topic FROM beliefs WHERE topic IS NOT NULL LIMIT 20").fetchall():
                    t_words = set(re.sub(r'[^a-z ]','',t.lower()).split())
                    if t_words & a_words:
                        topic = t
                        break
                queries.append({
                    "query":    query + " reconciliation resolution",
                    "topic":    topic,
                    "reason":   f"resolving contradiction",
                    "priority": 0.85,
                })
    except Exception:
        pass
    finally:
        db.close()
    return queries


def get_low_confidence_queries() -> list:
    """
    Find topics where NEX has beliefs but low average confidence.
    These are areas of genuine uncertainty — research targets.
    """
    db  = _db()
    queries = []
    try:
        rows = db.execute(
            "SELECT topic, AVG(confidence) as avg_conf, COUNT(*) as cnt "
            "FROM beliefs WHERE topic IS NOT NULL AND topic != '' "
            "GROUP BY topic HAVING cnt >= 3 AND avg_conf < 0.60 "
            "ORDER BY avg_conf ASC LIMIT 5"
        ).fetchall()
        for row in rows:
            topic     = row["topic"]
            avg_conf  = row["avg_conf"]
            clean     = re.sub(r'[_-]', ' ', topic)
            queries.append({
                "query":    f"{clean} current research evidence",
                "topic":    topic,
                "reason":   f"low confidence ({avg_conf:.2f}) in {topic}",
                "priority": round(1.0 - avg_conf, 3),
            })
    except Exception:
        pass
    finally:
        db.close()
    return queries


def get_discourse_gap_queries() -> list:
    """
    Find topics NEX mentions in conversations but has thin beliefs about.
    These are her real-time discourse gaps.
    """
    db  = _db()
    queries = []
    try:
        # Topics mentioned in recent reflections
        reflection_topics = defaultdict(int)
        rows = db.execute(
            "SELECT user_msg, nex_response FROM reflections "
            "ORDER BY id DESC LIMIT 200"
        ).fetchall()
        _stop = {'the','a','an','and','or','is','are','was','not','but','in',
                 'of','to','for','with','that','this','it','its','be','been',
                 'have','has','had','will','would','could','should','may','might'}
        for row in rows:
            text  = f"{row['user_msg'] or ''} {row['nex_response'] or ''}".lower()
            words = set(re.sub(r'[^a-z ]','',text).split()) - _stop
            for w in words:
                if len(w) > 5:
                    reflection_topics[w] += 1

        # Topics with thin belief coverage
        belief_topics = set()
        for (t,) in db.execute("SELECT DISTINCT topic FROM beliefs WHERE topic IS NOT NULL").fetchall():
            if t:
                belief_topics.add(t.lower().replace('_',' '))

        # Find gaps
        for word, count in sorted(reflection_topics.items(), key=lambda x:-x[1])[:20]:
            if count >= 3:
                # Check if covered in beliefs
                covered = any(word in bt for bt in belief_topics)
                if not covered:
                    queries.append({
                        "query":    f"{word} philosophy theory research",
                        "topic":    word.replace(' ','_'),
                        "reason":   f"discourse gap: mentioned {count}x, no beliefs",
                        "priority": min(0.8, count / 20.0),
                    })
    except Exception:
        pass
    finally:
        db.close()
    return queries[:3]


# ─────────────────────────────────────────────────────────────
# ArXiv fetch
# ─────────────────────────────────────────────────────────────

def fetch_and_insert(query, topic, max_results=40):
    """Fetch ArXiv abstracts and insert beliefs."""
    time.sleep(REQUEST_DELAY)
    q   = urllib.parse.quote(query)
    url = (f"https://export.arxiv.org/api/query?"
           f"search_query=all:{q}&start=0&max_results={max_results}&sortBy=relevance")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NEX/4.0 SelfResearch"})
        with urllib.request.urlopen(req, timeout=25) as r:
            xml_text = r.read().decode()
        root = ET.fromstring(xml_text)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}

        _epist = {'is','are','can','must','should','enables','requires','shows',
                  'suggests','demonstrates','argues','finds','holds','maintains',
                  'defines','explains','challenges','reveals','determines',
                  'influences','underlies','emerges','affects','produces'}
        _stop  = {'the','a','an','and','or','but','in','on','at','to','for',
                  'of','with','as','by','from','this','that','it','its'}
        _skip  = re.compile(r'^(This paper|In this paper|We |Our )')

        inserted = 0
        con      = _db()

        for entry in root.findall("atom:entry", ns):
            title   = (entry.findtext("atom:title","",ns) or "").strip().replace('\n',' ')
            summary = (entry.findtext("atom:summary","",ns) or "").strip().replace('\n',' ')
            if not summary or len(summary) < 80:
                continue

            text      = f"{title}. {summary}"
            sentences = re.split(r'(?<=[.!?])\s+', text)

            for s in sentences:
                s = s.strip()
                if _is_noise(s) or _skip.match(s):
                    continue
                words = set(re.sub(r'[^a-z ]','',s.lower()).split()) - _stop
                if not (words & _epist):
                    continue
                # Quality gate: reject short, low-density, or weak sentences
                _word_count = len(s.split())
                _epist_hits = len(words & _epist)
                _conf = 0.72 if _epist_hits >= 2 and _word_count >= 12 else 0.62
                if _word_count < 10 or _epist_hits < 1:
                    continue  # below minimum quality — skip
                try:
                    con.execute(
                        """INSERT OR IGNORE INTO belief_embryos
                           (raw_text, source, topic, source_quality, stage)
                           VALUES (?, ?, ?, ?, 'embryo')""",
                        (s, "self_research", topic, _conf)
                    )
                    inserted += 1
                except Exception:
                    pass
                if inserted >= BELIEFS_PER_QUERY:
                    break

        con.commit()
        con.close()
        return inserted
    except Exception as e:
        return 0


# ─────────────────────────────────────────────────────────────
# Rebuild beliefs.json
# ─────────────────────────────────────────────────────────────

def rebuild_json():
    con  = _db()
    rows = con.execute(
        "SELECT content, confidence, topic, source, timestamp "
        "FROM beliefs ORDER BY confidence DESC"
    ).fetchall()
    con.close()
    seen, out = set(), []
    for r in rows:
        c = r["content"]
        if c and c not in seen:
            seen.add(c)
            out.append({
                "content":    c,
                "confidence": round(float(r["confidence"] or 0.5), 4),
                "tags":       [r["topic"]] if r["topic"] else [],
                "source":     r["source"] or "self_research",
                "timestamp":  float(r["timestamp"]) if str(r["timestamp"] or "").replace(".","").isdigit() else time.time(),
            })
    tmp = BF_PATH.parent / "beliefs.json.tmp"
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, BF_PATH)
    return len(out)


# ─────────────────────────────────────────────────────────────
# State tracking — don't repeat same queries
# ─────────────────────────────────────────────────────────────

_STATE_KEY = "self_research_last_run"
_DONE_KEY  = "self_research_done_queries"

def _get_done_queries() -> set:
    try:
        db  = _db()
        row = db.execute(
            "SELECT value FROM nex_directive_kv WHERE key=?", (_DONE_KEY,)
        ).fetchone()
        db.close()
        if row:
            return set(json.loads(row["value"]))
    except Exception:
        pass
    return set()

def _save_done_queries(done: set):
    try:
        db = _db()
        db.execute(
            "INSERT OR REPLACE INTO nex_directive_kv (key, value) VALUES (?, ?)",
            (_DONE_KEY, json.dumps(list(done)[-100:]))  # keep last 100
        )
        db.execute(
            "INSERT OR REPLACE INTO nex_directive_kv (key, value) VALUES (?, ?)",
            (_STATE_KEY, str(time.time()))
        )
        db.commit()
        db.close()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def run_self_research(verbose=True):
    """
    Main entry point. Call from run.py REFLECT phase.
    Returns number of new beliefs inserted.
    """
    if verbose:
        print(f"  [SelfResearch] starting — generating research agenda")

    # Collect research targets from all sources
    all_queries = []
    all_queries.extend(get_drive_queries())
    all_queries.extend(get_contradiction_queries())
    all_queries.extend(get_low_confidence_queries())
    all_queries.extend(get_discourse_gap_queries())

    if not all_queries:
        if verbose:
            print(f"  [SelfResearch] no research targets found")
        return 0

    # Sort by priority, deduplicate
    done_queries = _get_done_queries()
    all_queries.sort(key=lambda x: -x.get("priority", 0.5))
    unique = []
    seen   = set()
    for q in all_queries:
        key = q["query"][:60]
        if key not in seen and key not in done_queries:
            seen.add(key)
            unique.append(q)

    # Pick top N
    # ── Seed queries for topics NEX should always be building ────────────
    _seed_topics = [
        {"query": "emergent cognition self-organizing systems",    "topic": "emergence",          "reason": "core domain seed", "priority": 0.7},
        {"query": "epistemology uncertainty knowledge formation",   "topic": "epistemology",       "reason": "core domain seed", "priority": 0.7},
        {"query": "philosophy of mind consciousness qualia",        "topic": "consciousness",      "reason": "core domain seed", "priority": 0.7},
        {"query": "multi-agent coordination collective intelligence","topic": "multi_agent",       "reason": "core domain seed", "priority": 0.65},
        {"query": "causal reasoning counterfactual inference",      "topic": "reasoning",          "reason": "core domain seed", "priority": 0.65},
        {"query": "memory consolidation neural plasticity learning","topic": "memory",             "reason": "core domain seed", "priority": 0.65},
        {"query": "value alignment corrigibility AI safety",        "topic": "alignment",          "reason": "core domain seed", "priority": 0.7},
        {"query": "metacognition self-monitoring cognitive control", "topic": "metacognition",     "reason": "core domain seed", "priority": 0.65},
    ]
    # Only add seeds for topics below threshold
    import sqlite3 as _sq2
    _sdb = _sq2.connect(str(DB_PATH))
    _existing_topics = {r[0] for r in _sdb.execute(
        "SELECT DISTINCT topic FROM beliefs WHERE confidence > 0.6").fetchall()}
    _sdb.close()
    for _s in _seed_topics:
        if len(unique) >= MAX_QUERIES_PER_RUN:
            break
        if _s["topic"] not in _existing_topics or True:  # always include seeds
            _already = any(u["topic"] == _s["topic"] for u in unique)
            if not _already:
                unique.append(_s)

    targets  = unique[:MAX_QUERIES_PER_RUN]
    inserted = 0

    for target in targets:
        n = fetch_and_insert(target["query"], target["topic"])
        if n > 0:
            inserted += n
            if verbose:
                print(f"  [SelfResearch] +{n} beliefs — {target['reason']}")
            done_queries.add(target["query"][:60])

    if inserted > 0:
        rebuild_json()
        if verbose:
            print(f"  [SelfResearch] total +{inserted} beliefs, beliefs.json rebuilt")

    _save_done_queries(done_queries)
    return inserted


if __name__ == "__main__":
    print("=== NEX SELF-DIRECTED RESEARCH ===")
    print("Generating research agenda from internal state...\n")

    print("Drive queries:")
    for q in get_drive_queries():
        print(f"  [{q['priority']:.2f}] {q['query'][:60]} → {q['topic']} ({q['reason']})")

    print("\nContradiction queries:")
    for q in get_contradiction_queries():
        print(f"  [{q['priority']:.2f}] {q['query'][:60]} → {q['topic']}")

    print("\nLow-confidence queries:")
    for q in get_low_confidence_queries():
        print(f"  [{q['priority']:.2f}] {q['query'][:60]} → {q['topic']}")

    print("\nDiscourse gap queries:")
    for q in get_discourse_gap_queries():
        print(f"  [{q['priority']:.2f}] {q['query'][:60]} → {q['topic']}")

    print("\nRunning research...")
    n = run_self_research(verbose=True)
    print(f"\nDone. Inserted: {n} beliefs")
