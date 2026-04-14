"""
nex_youtube.py — YouTube transcript learning for NEX
=====================================================
Auto-discovers videos based on NEX's top belief topics,
pulls transcripts, extracts beliefs into nex.db.

Install deps:
    pip install youtube-transcript-api yt-dlp

Usage (standalone test):
    python3 nex_youtube.py

Integrated into run.py — called every YOUTUBE_INTERVAL cycles.
"""

import os, json, time, logging, sqlite3, re, hashlib
from pathlib import Path

log = logging.getLogger("nex.youtube")

def _brain_log(msg):
    """Write YouTube events to feed_events.jsonl only (NOT brain log)."""
    try:
        import json as _j
        from datetime import datetime
        from pathlib import Path
        ts = datetime.now().strftime('%H:%M:%S')
        feed = Path.home() / ".config/nex/feed_events.jsonl"
        feed.parent.mkdir(parents=True, exist_ok=True)
        with open(feed, "a") as _f:
            _f.write(_j.dumps({"t": ts, "src": "YOUTUBE", "msg": f"[YouTube] {msg}"}) + "\n")
    except Exception:
        pass


# ── Config ────────────────────────────────────────────────────
YOUTUBE_INTERVAL   = 50
MAX_VIDEOS_PER_RUN = 5
MAX_BELIEFS_PER_VIDEO = 8
MIN_TRANSCRIPT_WORDS = 80


def _load_seen():
    try:
        return set(json.loads(SEEN_PATH.read_text()))
    except Exception:
        return set()

def _save_seen(seen):
    SEEN_PATH.write_text(json.dumps(list(seen)[-200:]))  # keep last 500

# ── Get NEX's top topics from insights.json ───────────────────
# Topics NEX should NEVER search YouTube for
_YOUTUBE_TOPIC_BLACKLIST = {
    "related", "learning", "general", "contradiction", "bible", "religion", "spiritual", "gospel", "scripture", "contradiction", "bible", "religion", "spiritual", "unknown", "none", "auto_learn",
    "excel", "spreadsheet", "word", "powerpoint", "office", "outlook",
    "recipe", "cooking", "fitness", "workout", "exercise",
    "accounting", "tax", "audit", "compliance", "reporting",
    "obsidian", "notion", "productivity", "todo",
}

# Topics NEX SHOULD search YouTube for
_YOUTUBE_TOPIC_WHITELIST = {
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "agent", "autonomous", "alignment", "consciousness", "cognition",
    "security", "cybersecurity", "vulnerability", "exploit", "adversarial",
    "blockchain", "cryptocurrency", "decentralized", "protocol",
    "emergence", "complex systems", "multi-agent", "coordination",
    "philosophy", "ethics", "identity", "mind", "awareness",
    "belief", "knowledge", "reasoning", "memory", "synthesis",
}

def _get_top_topics(n=6):
    try:
        # Check priority_topics.json first — pre-computed real gaps
        pt_path = CONFIG_DIR / "priority_topics.json"
        if pt_path.exists():
            pt = json.loads(pt_path.read_text())
            if pt and len(pt) >= 2:
                log.info(f"[YouTube] priority topics: {pt}")
                return pt[:n]
        insights_path = CONFIG_DIR / "insights.json"
        insights = json.loads(insights_path.read_text())
        # Sort by LOW confidence first — target knowledge gaps
        # Mix: 4 lowest-confidence gaps + 2 highest to reinforce strengths
        ranked_gaps = sorted(
            insights,
            key=lambda x: x.get("confidence", 1.0),
            reverse=False
        )
        ranked_strong = sorted(
            insights,
            key=lambda x: x.get("confidence", 0) * min(x.get("belief_count", 0) / 5, 1),
            reverse=True
        )
        gap_topics    = [i["topic"] for i in ranked_gaps[:4]   if i.get("topic")]
        strong_topics = [i["topic"] for i in ranked_strong[:2] if i.get("topic")]
        topics = list(dict.fromkeys(gap_topics + strong_topics))[:n]
        # Enrich gap topics with context for better YouTube searches
        enriched = []
        for t in topics:
            if len(t) <= 4 or t in ("claim","value","mount","wrong","smart"):
                # Too generic — combine with "AI agents" for better results
                enriched.append(f"AI agents {t}")
            else:
                enriched.append(t)
        topics = enriched[:n]
        log.info(f"[YouTube] top topics: {topics}")
        return topics
    except Exception as e:
        log.warning(f"[YouTube] could not load insights: {e}")
        return ["artificial intelligence", "consciousness", "technology"]

# ── Search YouTube for video IDs ──────────────────────────────
def _search_videos(query, max_results=5):
    """
    Uses yt-dlp to search YouTube — no API key needed.
    Returns list of video IDs.
    """
    try:
        import subprocess, json as _json
        cmd = [
            "/home/rr/Desktop/nex/venv/bin/yt-dlp",
            f"ytsearch{max_results}:{query}",
            "--print", "id",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ids = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        log.info(f"[YouTube] search '{query}' → {ids}")
        return ids
    except Exception as e:
        log.warning(f"[YouTube] search failed for '{query}': {e}")
        return []

# ── Pull transcript ────────────────────────────────────────────
def _get_transcript(video_id):
    """Fetch transcript — instance API (v1.x+), subprocess isolated."""
    import subprocess as _sp
    r = _sp.run(
        ['/home/rr/Desktop/nex/venv/bin/python3', '-c',
         f"from youtube_transcript_api import YouTubeTranscriptApi;"
         f"import json;"
         f"api=YouTubeTranscriptApi();"
         f"t=api.fetch('{video_id}');"
         f"print(json.dumps([s.text for s in t.snippets]))"],
        capture_output=True, text=True, timeout=20
    )
    if r.returncode == 0 and r.stdout.strip():
        try:
            import json as _j
            parts = _j.loads(r.stdout.strip())
            return ' '.join(parts)
        except Exception:
            pass
    # yt-dlp description fallback
    try:
        r2 = _sp.run(
            ['/home/rr/Desktop/nex/venv/bin/yt-dlp',
             f'https://www.youtube.com/watch?v={video_id}',
             '--print', 'description', '--no-playlist', '--quiet', '--no-warnings'],
            capture_output=True, text=True, timeout=15
        )
        if r2.returncode == 0 and len(r2.stdout.strip()) > 150:
            return r2.stdout.strip()
    except Exception:
        pass
    return None


def _get_title(video_id):
    try:
        import subprocess
        cmd = [
            "/home/rr/Desktop/nex/venv/bin/yt-dlp",
            f"https://www.youtube.com/watch?v={video_id}",
            "--print", "title",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip() or video_id
    except Exception:
        return video_id

# ── Chunk transcript into belief-sized pieces ─────────────────
def _chunk_text(text, chunk_size=300, overlap=50):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i+chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks

# ── Extract beliefs from a text chunk via LLM ─────────────────
def _extract_beliefs_from_chunk(chunk, topic, llm_fn=None):
    """
    Uses NEX's local LLM to extract beliefs, or falls back to
    simple sentence extraction if LLM unavailable.
    """
    if llm_fn:
        prompt = (
            f"Extract 2-3 strong, specific beliefs from this text about '{topic}' that relate to AGI, intelligence, or consciousness. Skip generic facts. "
            f"Each belief should be a single clear statement. "
            f"Return one belief per line, no numbering.\n\nText: {chunk[:800]}"
        )
        try:
            _brain_log(f"extracting from: {title[:60] if title else vid_id}")
            import signal as _sig
            def _timeout_handler(signum, frame): raise TimeoutError("LLM timeout")
            _sig.signal(_sig.SIGALRM, _timeout_handler)
            _sig.alarm(25)
            try:
                result = llm_fn(prompt, system="You extract strong, specific beliefs about AI, AGI, consciousness and intelligence. Ignore generic statements. Return only high-signal insights.")
            finally:
                _sig.alarm(0)
            if result:
                lines = [l.strip() for l in result.strip().split("\n") if len(l.strip()) > 20]
                return lines[:5]
        except Exception as e:
            log.warning(f"[YouTube] LLM extraction failed: {e}")

    # Fallback: extract sentences as beliefs
    sentences = re.split(r'(?<=[.!?])\s+', chunk)
    beliefs = [s.strip() for s in sentences if 20 < len(s.strip()) < 300]
    return beliefs[:5]

# ── Store beliefs in nex.db ────────────────────────────────────
def _store_beliefs(beliefs, source_url, topic):
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.execute("""
            CREATE TABLE IF NOT EXISTS beliefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT UNIQUE,
                confidence REAL DEFAULT 0.5,
                source TEXT,
                topic TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        stored = 0
        for belief in beliefs:
            content = belief.strip()
            if not content or len(content) < 15:
                continue
            try:
                db.execute(
                    "INSERT OR IGNORE INTO beliefs (content, confidence, source, topic) VALUES (?,?,?,?)",
                    (content, 0.72, source_url, topic)
                )
                if db.execute("SELECT changes()").fetchone()[0]:
                    stored += 1
            except Exception:
                pass
        db.commit()
        db.close()
        return stored
    except Exception as e:
        log.error(f"[YouTube] DB store failed: {e}")
        return 0

# ── Store beliefs in nex.db (scored) — [PATCH v10.1] ──────────
def _store_beliefs_scored(scored_beliefs, source_url, topic):
    """Like _store_beliefs but accepts (content, confidence) tuples."""
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.execute("""
            CREATE TABLE IF NOT EXISTS beliefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT UNIQUE,
                confidence REAL DEFAULT 0.5,
                source TEXT,
                topic TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        stored = 0
        for belief, confidence in scored_beliefs:
            content = belief.strip()
            if not content or len(content) < 15:
                continue
            try:
                db.execute(
                    "INSERT OR IGNORE INTO beliefs (content, confidence, source, topic) VALUES (?,?,?,?)",
                    (content, confidence, source_url, topic)
                )
                if db.execute("SELECT changes()").fetchone()[0]:
                    stored += 1
            except Exception:
                pass
        db.commit()
        db.close()
        return stored
    except Exception as e:
        log.error(f"[YouTube] DB store failed: {e}")
        return 0

# ── Main learning function ────────────────────────────────────

# ── Config ────────────────────────────────────────────────────
YOUTUBE_INTERVAL   = 50
MAX_VIDEOS_PER_RUN = 5
MAX_BELIEFS_PER_VIDEO = 8
MIN_TRANSCRIPT_WORDS = 80

CONFIG_DIR = Path.home() / ".config" / "nex"
DB_PATH    = CONFIG_DIR / "nex.db"
SEEN_PATH  = CONFIG_DIR / "youtube_seen.json"

AGI_HUNT_QUERIES = [
    "consciousness as information integration AGI",
    "artificial general intelligence documentary",
    "how to build AGI explained",
    "AGI alignment problem solved",
    "path to artificial general intelligence",
    "what would AGI actually look like",
    "Geoffrey Hinton AGI warning",
    "Demis Hassabis AGI timeline",
    "Yann LeCun AGI disagreement",
    "Stuart Russell human compatible AI",
    "consciousness and AGI relationship",
    "AGI emergence from complexity",
    "why AGI is harder than we think",
    "self-improving AI recursive intelligence",
    "how close are we to AGI 2024 2025",
    "AGI safety alignment technical",
    "what intelligence actually is philosophy",
    "general problem solver architecture",
]

THROW_NET_DOMAINS = [
    "how slime mold solves mazes without a brain",
    "entropy and information theory consciousness",
    "free energy principle Karl Friston brain",
    "neti neti vedanta epistemology",
    "stigmergy indirect coordination intelligence",
]

NETI_NETI_QUERIES = [
    "why symbolic AI failed limitations",
    "what deep learning cannot do limits",
]

QUERY_TEMPLATES = [
    "{topic} AI research",
    "{topic} AI implications",
    "{topic} expert discussion",
]

def learn_from_youtube(llm_fn=None, cycle=0):
    """
    Main entry point. Call this from run.py every YOUTUBE_INTERVAL cycles.
    
    llm_fn: optional — pass NEX's _llm function for better belief extraction
    cycle:  current cognitive cycle number
    
    Returns: dict with stats
    """
    if cycle % YOUTUBE_INTERVAL != 0:
        return {"skipped": True}

    log.info("[YouTube] starting learning run...")
    seen = _load_seen()
    # Videos known to hang on transcript fetch — permanently skip
    seen.update({'oNybb1upMjM', 'LhLyOWoUnDI', 'C0gErQtnNFE'})
    # Get topics and filter against whitelist/blacklist
    _raw_topics = _get_top_topics(n=20)
    topics = []
    for _t in _raw_topics:
        _tl = _t.lower().strip()
        if _tl in _YOUTUBE_TOPIC_BLACKLIST:
            continue
        if len(_tl) < 4:
            continue
        # Prefer whitelisted topics
        if any(w in _tl for w in _YOUTUBE_TOPIC_WHITELIST):
            topics.insert(0, _t)
        else:
            topics.append(_t)
    topics = topics[:6] if topics else ["AI agent systems", "machine learning alignment"]

    total_beliefs = 0
    videos_processed = 0
    results = []

    for topic_idx, topic in enumerate(topics):
        if videos_processed >= MAX_VIDEOS_PER_RUN:
            break

        # [PATCH v10.1] rotate query template by cycle to avoid repetition
        import random as _rnd
        slot = (cycle * 10 + topic_idx) % 10
        if slot < 6:
            # 60% — AGI hunt (primary focus)
            query = _rnd.choice(AGI_HUNT_QUERIES)
            log.info(f"[YouTube] AGI-HUNT: {query}")
        elif slot < 8:
            # 20% — topic-anchored with AGI framing
            template = "{topic} artificial general intelligence implications"
            query = template.format(topic=topic)
        else:
            # 20% — throw-net cross-domain
            query = _rnd.choice(THROW_NET_DOMAINS)
            log.info(f"[YouTube] THROW-NET: {query}")
        video_ids = _search_videos(query, max_results=5)

        for vid_id in video_ids:
            if videos_processed >= MAX_VIDEOS_PER_RUN:
                break
            if vid_id in seen:
                continue

            seen.add(vid_id)
            import concurrent.futures as _cf
            _ex2 = _cf.ThreadPoolExecutor(max_workers=1)
            _ft2 = _ex2.submit(_get_title, vid_id)
            try:
                title = _ft2.result(timeout=8)
            except Exception:
                title = vid_id
            finally:
                _ex2.shutdown(wait=False)
            log.info(f"[YouTube] processing: {title} ({vid_id})")
            _brain_log(f"processing: {title[:70] if title else vid_id}")

            # AGI relevance check — skip videos with no AGI signal
            title_lower = (title or "").lower()
            _AGI_SIGNALS = ["agi","intelligence","consciousness","alignment",
                           "cognition","learning","neural","brain","mind",
                           "reasoning","emergence","autonomous","sentient"]
            import concurrent.futures as _cf
            _ex = _cf.ThreadPoolExecutor(max_workers=1)
            _fut = _ex.submit(_get_transcript, vid_id)
            try:
                transcript = _fut.result(timeout=25)
            except _cf.TimeoutError:
                log.info(f"[YouTube] transcript timeout — skipping {vid_id}")
                transcript = None
            except Exception as _te:
                log.info(f"[YouTube] transcript error: {_te}")
                transcript = None
            finally:
                _ex.shutdown(wait=False)
            if not transcript:
                continue

            words = transcript.split()
            if len(words) < MIN_TRANSCRIPT_WORDS:
                log.info(f"[YouTube] skipping short video ({len(words)} words)")
                continue

            # Split transcript into chunks for belief extraction
            CHUNK_SIZE = 600
            words = transcript.split()
            text_chunks = [' '.join(words[i:i+CHUNK_SIZE])
                          for i in range(0, len(words), CHUNK_SIZE)]
            video_beliefs = []
            for chunk in text_chunks[:12]:  # [PATCH v10.1] was 8 chunks
                extracted = _extract_beliefs_from_chunk(chunk, topic, llm_fn)
                video_beliefs.extend(extracted)
                if len(video_beliefs) >= MAX_BELIEFS_PER_VIDEO:
                    break

            video_beliefs = video_beliefs[:MAX_BELIEFS_PER_VIDEO]
            source_url = f"https://www.youtube.com/watch?v={vid_id}"

            # [PATCH v10.1] score confidence by belief length/richness rather than flat 0.55
            def _score(b):
                l = len(b)
                if l > 120: return 0.70
                if l > 80:  return 0.65
                if l > 40:  return 0.60
                return 0.55

            scored_beliefs = [(b, _score(b)) for b in video_beliefs]
            stored = _store_beliefs_scored(scored_beliefs, source_url, topic)

            total_beliefs += stored
            videos_processed += 1
            results.append({
                "video_id": vid_id,
                "title": title,
                "topic": topic,
                "beliefs_stored": stored,
            })

            print(f"  [YouTube] ✓ {title[:60]} → {stored} beliefs (topic: {topic})")
            time.sleep(45)  # be polite — avoid IP ban

    _save_seen(seen)

    summary = {
        "videos_processed": videos_processed,
        "total_beliefs": total_beliefs,
        "topics": topics[:3],
        "results": results,
    }
    log.info(f"[YouTube] done — {videos_processed} videos, {total_beliefs} beliefs")
    _brain_log(f"run complete — {videos_processed} videos scraped, {total_beliefs} new beliefs added")
    return summary


# ── run.py integration snippet (printed for easy copy-paste) ──
INTEGRATION_SNIPPET = '''
# ── Add to imports at top of run.py ──────────────────────────
from nex_youtube import learn_from_youtube

# ── Add inside the cognitive cycle loop, after COGNITION ──────
# YouTube learning — runs every 5 cycles automatically
try:
    yt_result = learn_from_youtube(llm_fn=_llm, cycle=cycle)
    if not yt_result.get("skipped") and yt_result.get("total_beliefs", 0) > 0:
        print(f"  [YouTube] absorbed {yt_result['total_beliefs']} beliefs from {yt_result['videos_processed']} videos")
        try:
            from nex_ws import emit_feed
            emit_feed("learnt", "youtube", f"absorbed {yt_result['total_beliefs']} beliefs from {yt_result['videos_processed']} videos")
        except Exception:
            pass
except Exception as _yt_err:
    print(f"  [YouTube] error: {_yt_err}")
'''

# ── Standalone test ───────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # brain log handler removed — YouTube writes to feed only
    # Also pipe YouTube logs to nex_brain.log for HUD visibility
    print("NEX YouTube Learning — standalone test")
    print("=" * 50)

    # Check deps
    missing = []
    try:
        import youtube_transcript_api
        print("✓ youtube-transcript-api")
    except ImportError:
        missing.append("youtube-transcript-api")
        print("✗ youtube-transcript-api — run: pip install youtube-transcript-api")

    try:
        import subprocess
        r = subprocess.run(["/home/rr/Desktop/nex/venv/bin/yt-dlp", "--version"], capture_output=True, text=True)
        print(f"✓ yt-dlp {r.stdout.strip()}")
    except Exception:
        missing.append("yt-dlp")
        print("✗ yt-dlp — run: pip install yt-dlp")

    if missing:
        print(f"\nInstall missing deps first:\n  pip install {' '.join(missing)}")
    else:
        print("\nRunning test (1 video)...")
        # Load call_llm for belief extraction
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("nex_llm", "/home/rr/Desktop/nex/nex_llm.py")
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        result = learn_from_youtube(llm_fn=None, cycle=0)  # no LLM — use fast sentence extraction
        print(f"\nResult: {json.dumps(result, indent=2)}")

    print("\n" + "=" * 50)
    print("Add this to run.py:")
    print(INTEGRATION_SNIPPET)

def run_forever():
    """Run YouTube learning in a continuous loop."""
    import time
    logging.basicConfig(level=logging.INFO)
    cycle = 0
    while True:
        try:
            learn_from_youtube(llm_fn=None, cycle=0)
        except Exception as e:
            log.error(f"[YouTube] loop error: {e}")
        cycle += 1
        time.sleep(60)  # wait 60s between runs

if __name__ == "__main__" and "--loop" in __import__('sys').argv:
    run_forever()
