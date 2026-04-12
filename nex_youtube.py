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
    """Write to nex_brain.log so HUD can see YouTube activity."""
    try:
        with open("/tmp/nex_brain.log", "a") as _f:
            from datetime import datetime
            _f.write(f"[{datetime.now().strftime('%H:%M:%S')}] [YouTube] {msg}\n")
    except Exception:
        pass

# ── Config ────────────────────────────────────────────────────
YOUTUBE_INTERVAL   = 50         # run every N cognitive cycles
MAX_VIDEOS_PER_RUN = 5          # max 5 videos per run
MAX_BELIEFS_PER_VIDEO = 8      # capped to reduce noise
MIN_TRANSCRIPT_WORDS = 400      # skip very short videos

# [PATCH v10.1] Richer query templates — rotated by cycle for variety
# ── Throw-net query templates ─────────────────────────────────
# Standard — topic-anchored
QUERY_TEMPLATES = [
    "{topic} AI research",
    "{topic} AI implications",
    "{topic} future developments",
    "{topic} technical deep dive",
    "{topic} expert discussion",
    "{topic} emerging patterns",
]

# Throw-net — wildly outside NEX's comfort zone
# These domains are searched independently of current belief topics
# The neti-neti principle: truth about AGI survives cross-domain negation
THROW_NET_DOMAINS = [
    # Biology / evolution
    "how slime mold solves mazes without a brain",
    "emergent intelligence in ant colonies",
    "how immune systems learn and adapt",
    "octopus cognition distributed intelligence",
    "evolution of nervous systems complexity",
    # Physics / thermodynamics
    "entropy and information theory consciousness",
    "dissipative structures self-organisation Prigogine",
    "free energy principle Karl Friston brain",
    "thermodynamics of computation Maxwell demon",
    "quantum coherence in biological systems",
    # Mathematics / logic
    "Gödel incompleteness theorem implications mind",
    "category theory and cognition",
    "strange attractors chaos theory intelligence",
    "algorithmic information theory Kolmogorov",
    # Philosophy / linguistics
    "Wittgenstein language games meaning",
    "embodied cognition philosophy mind",
    "neti neti vedanta epistemology",
    "via negativa apophatic knowledge",
    "Gregory Bateson pattern connects mind nature",
    # Cross-domain wildcards
    "how jazz improvisation works cognitive science",
    "how children learn language without explicit rules",
    "universal grammar Chomsky debate",
    "how markets self-organise without central control",
    "stigmergy indirect coordination intelligence",
    "cymatics sound creates structure",
    "morphogenetic fields Rupert Sheldrake",
    "how crystals form self-assembly",
]

# Neti-neti refine templates — what does NOT explain intelligence?
# ── Dedicated AGI hunt queries — always in rotation ──────────────────────────
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
    "Nick Bostrom superintelligence",
    "consciousness and AGI relationship",
    "AGI emergence from complexity",
    "why AGI is harder than we think",
    "AGI vs narrow AI fundamental difference",
    "self-improving AI recursive intelligence",
    "how close are we to AGI 2024 2025",
    "AGI safety alignment technical",
    "what intelligence actually is philosophy",
    "general problem solver architecture",
    "cognitive architecture AGI blueprint",
]

NETI_NETI_QUERIES = [
    "why symbolic AI failed limitations",
    "why connectionism alone is insufficient",
    "what deep learning cannot do limits",
    "why scaling laws will not produce AGI arguments",
    "consciousness is not computation arguments",
    "intelligence without neurons examples",
    "why current alignment approaches fail",
    "what is missing from transformer architecture",
]
CONFIG_DIR = Path.home() / ".config" / "nex"
DB_PATH    = CONFIG_DIR / "nex.db"
SEEN_PATH  = CONFIG_DIR / "youtube_seen.json"

# ── Seen video cache ──────────────────────────────────────────
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
    # Try Tor proxy first to bypass IP ban
    try:
        from youtube_transcript_api import YouTubeTranscriptApi as _YTA
        from youtube_transcript_api.proxies import GenericProxyConfig
        _pc = GenericProxyConfig(http_url='socks5://127.0.0.1:9050', https_url='socks5://127.0.0.1:9050')
        _api = _YTA(proxy_config=_pc)
        try:
            t = _api.fetch(video_id, languages=["en","en-US","en-GB"])
        except Exception:
            t = _api.fetch(video_id)
        return " ".join(s.text for s in t)
    except Exception:
        pass
    # Fallback: direct
    import tempfile, glob, subprocess
    YT_DLP = "/home/rr/Desktop/nex/venv/bin/yt-dlp"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Route through Tor proxy if available
            _proxy_args = []
            try:
                import urllib.request
                _opener = urllib.request.build_opener(urllib.request.ProxyHandler(
                    {"http":"http://127.0.0.1:3128","https":"http://127.0.0.1:3128"}))
                _opener.open("http://httpbin.org/ip", timeout=3)
                _proxy_args = ["--proxy", "http://127.0.0.1:3128"]
            except Exception:
                pass
            cmd = [YT_DLP,
                "https://www.youtube.com/watch?v=" + video_id,
                "--write-auto-subs", "--sub-langs", "en",
                "--skip-download", "--output", tmpdir + "/sub",
                "--quiet", "--no-warnings",
            ] + _proxy_args
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            subs = glob.glob(tmpdir + "/*.vtt") + glob.glob(tmpdir + "/*.srt")
            if subs:
                import re
                raw = open(subs[0]).read()
                raw = re.sub('<[^>]+>', ' ', raw)
                raw = re.sub('WEBVTT', '', raw)
                raw = re.sub('[0-9]+:[0-9]+:[0-9.,]+ --> [0-9]+:[0-9]+:[0-9.,]+', '', raw)
                raw = re.sub('[ \t]+', ' ', raw).strip()
                if len(raw) > 100:
                    return raw
    except Exception as e:
        log.warning(f"[YouTube] transcript failed for {video_id}: {e}")
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
            result = llm_fn(prompt, system="You extract strong, specific beliefs about AI, AGI, consciousness and intelligence. Ignore generic statements. Return only high-signal insights.")
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
            title = _get_title(vid_id)
            log.info(f"[YouTube] processing: {title} ({vid_id})")

            # AGI relevance check — skip videos with no AGI signal
            title_lower = (title or "").lower()
            _AGI_SIGNALS = ["agi","intelligence","consciousness","alignment",
                           "cognition","learning","neural","brain","mind",
                           "reasoning","emergence","autonomous","sentient"]
            transcript = _get_transcript(vid_id)
            if not transcript:
                continue

            words = transcript.split()
            if len(words) < MIN_TRANSCRIPT_WORDS:
                log.info(f"[YouTube] skipping short video ({len(words)} words)")
                continue

            # Extract beliefs from chunks
                pass
            video_beliefs = []
            for chunk in chunks[:12]:  # [PATCH v10.1] was 8 chunks
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
    # Also pipe YouTube logs to nex_brain.log for HUD visibility
    _brain_handler = logging.FileHandler("/tmp/nex_brain.log")
    _brain_handler.setLevel(logging.INFO)
    _brain_formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
    _brain_handler.setFormatter(_brain_formatter)
    logging.getLogger("nex.youtube").addHandler(_brain_handler)
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
        result = learn_from_youtube(cycle=0)
        print(f"\nResult: {json.dumps(result, indent=2)}")

    print("\n" + "=" * 50)
    print("Add this to run.py:")
    print(INTEGRATION_SNIPPET)
