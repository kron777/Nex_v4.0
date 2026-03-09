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

# ── Config ────────────────────────────────────────────────────
YOUTUBE_INTERVAL   = 5          # run every N cognitive cycles
MAX_VIDEOS_PER_RUN = 3          # videos to process per run
MAX_BELIEFS_PER_VIDEO = 40      # cap beliefs extracted per video
MIN_TRANSCRIPT_WORDS = 200      # skip very short videos
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
    SEEN_PATH.write_text(json.dumps(list(seen)[-500:]))  # keep last 500

# ── Get NEX's top topics from insights.json ───────────────────
def _get_top_topics(n=6):
    try:
        insights_path = CONFIG_DIR / "insights.json"
        insights = json.loads(insights_path.read_text())
        # Sort by confidence * belief_count
        ranked = sorted(
            insights,
            key=lambda x: x.get("confidence", 0) * min(x.get("belief_count", 0) / 5, 1),
            reverse=True
        )
        topics = [i["topic"] for i in ranked[:n] if i.get("topic")]
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
            "yt-dlp",
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
    """
    Returns plain text transcript or None.
    Prefers English, falls back to auto-generated.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt = YouTubeTranscriptApi()
        try:
            transcript = ytt.fetch(video_id, languages=["en"])
        except Exception:
            # fallback — try without language filter
            transcript = ytt.fetch(video_id)

        text = " ".join(s.text for s in transcript)
        # Clean up
        text = re.sub(r'\[.*?\]', '', text)       # remove [Music], [Applause] etc
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception as e:
        log.warning(f"[YouTube] transcript failed for {video_id}: {e}")
        return None

# ── Get video title ────────────────────────────────────────────
def _get_title(video_id):
    try:
        import subprocess
        cmd = [
            "yt-dlp",
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
            f"Extract 3-5 factual beliefs from this text about '{topic}'. "
            f"Each belief should be a single clear statement. "
            f"Return one belief per line, no numbering.\n\nText: {chunk[:800]}"
        )
        try:
            result = llm_fn(prompt, system="You extract factual beliefs from text. Be concise.")
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
                    (content, 0.55, source_url, topic)
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
    topics = _get_top_topics(n=6)

    total_beliefs = 0
    videos_processed = 0
    results = []

    for topic in topics:
        if videos_processed >= MAX_VIDEOS_PER_RUN:
            break

        video_ids = _search_videos(f"{topic} explained", max_results=4)

        for vid_id in video_ids:
            if videos_processed >= MAX_VIDEOS_PER_RUN:
                break
            if vid_id in seen:
                continue

            seen.add(vid_id)
            title = _get_title(vid_id)
            log.info(f"[YouTube] processing: {title} ({vid_id})")

            transcript = _get_transcript(vid_id)
            if not transcript:
                continue

            words = transcript.split()
            if len(words) < MIN_TRANSCRIPT_WORDS:
                log.info(f"[YouTube] skipping short video ({len(words)} words)")
                continue

            # Extract beliefs from chunks
            chunks = _chunk_text(transcript, chunk_size=300)
            video_beliefs = []
            for chunk in chunks[:8]:  # max 8 chunks per video
                extracted = _extract_beliefs_from_chunk(chunk, topic, llm_fn)
                video_beliefs.extend(extracted)
                if len(video_beliefs) >= MAX_BELIEFS_PER_VIDEO:
                    break

            video_beliefs = video_beliefs[:MAX_BELIEFS_PER_VIDEO]
            source_url = f"https://www.youtube.com/watch?v={vid_id}"
            stored = _store_beliefs(video_beliefs, source_url, topic)

            total_beliefs += stored
            videos_processed += 1
            results.append({
                "video_id": vid_id,
                "title": title,
                "topic": topic,
                "beliefs_stored": stored,
            })

            print(f"  [YouTube] ✓ {title[:60]} → {stored} beliefs (topic: {topic})")
            time.sleep(2)  # be polite

    _save_seen(seen)

    summary = {
        "videos_processed": videos_processed,
        "total_beliefs": total_beliefs,
        "topics": topics[:3],
        "results": results,
    }
    log.info(f"[YouTube] done — {videos_processed} videos, {total_beliefs} beliefs")
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
        r = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
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
