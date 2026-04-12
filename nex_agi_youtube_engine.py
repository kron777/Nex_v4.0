import time
#!/usr/bin/env python3
"""
nex_agi_youtube_engine.py
=========================
Proper AGI belief distillation from YouTube transcripts.

Replaces the shallow chunk→store pipeline with:
1. AGI-focused video search
2. LLM distillation with a strong extraction prompt
3. Belief strength scoring
4. Novelty testing against existing belief graph
5. Cross-video synthesis

Drop into ~/Desktop/nex/ and import from run.py or call standalone.
"""

import sqlite3, subprocess, json, re, time, logging
from pathlib import Path
from nex_youtube_rotator import yt_fetch, yt_status_string  # NEX IP rotator

log = logging.getLogger("nex.agi_youtube")

DB_PATH   = Path.home() / ".config/nex/nex.db"
SEEN_PATH = Path.home() / ".config/nex/agi_youtube_seen.json"
YT_BIN    = "/home/rr/Desktop/nex/venv/bin/yt-dlp"

MAX_VIDEOS      = 3
MAX_BELIEFS     = 15   # per video — quality over quantity
MIN_BELIEF_LEN  = 40
MIN_STRENGTH    = 0.55 # discard weak beliefs

# ── AGI-focused search queries ─────────────────────────────────────────────────

AGI_SEARCH_QUERIES = [
    # Direct AGI theory
    "artificial general intelligence how it works explained",
    "what is AGI and how do we get there",
    "path to artificial general intelligence 2024 2025",
    "AGI alignment problem technical explanation",
    "why AGI is different from narrow AI",
    # Key thinkers
    "Geoffrey Hinton AGI consciousness warning",
    "Yann LeCun AGI world model theory",
    "Demis Hassabis AGI DeepMind approach",
    "Stuart Russell human compatible AI alignment",
    "Yoshua Bengio AGI safety consciousness",
    "Ilya Sutskever AGI scaling hypothesis",
    "Sam Altman AGI timeline prediction",
    # Technical approaches
    "cognitive architecture artificial general intelligence",
    "self-improving AI recursive intelligence explanation",
    "AGI emergence from large language models",
    "world models and AGI planning",
    "consciousness and artificial general intelligence",
    "embodied cognition path to AGI",
    # Philosophy of mind / AGI
    "what is intelligence really philosophy",
    "Chinese room argument AGI consciousness Searle",
    "integrated information theory consciousness IIT",
    "global workspace theory artificial consciousness",
    "free energy principle brain AGI Friston",
    # Cross-domain (throw-net)
    "emergence complexity intelligence self-organisation",
    "how slime mold intelligence distributed cognition",
    "ant colony intelligence emergence no brain",
    "strange attractors chaos intelligence pattern",
    "thermodynamics information intelligence Maxwell demon",
    # Neti-neti (what doesn't work)
    "why deep learning alone cannot achieve AGI",
    "limits of current AI what is missing",
    "why scaling laws will not produce AGI arguments against",
    "what current AI systems fundamentally cannot do",
    "problems with transformer architecture intelligence",
]

THROW_NET_QUERIES = [
    "octopus distributed intelligence cognition",
    "Godel incompleteness mind consciousness implications",
    "category theory cognition mathematical structure",
    "Hofstadter strange loop self-reference consciousness",
    "Bateson pattern connects mind nature ecology",
    "via negativa apophatic knowledge neti-neti",
    "dissipative structures Prigogine self-organisation intelligence",
    "morphogenesis biological pattern formation intelligence",
    "cymatics vibration pattern emergence",
    "stigmergy indirect coordination intelligence swarms",
]

# ── LLM interface ──────────────────────────────────────────────────────────────

def _llm_call(prompt, system="You are a rigorous philosophical analyst.", timeout=45):
    """Call local LLM directly."""
    try:
        import requests
        payload = {
            "model": "local",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 600,
            "temperature": 0.3,
        }
        r = requests.post(
            "http://localhost:8080/v1/chat/completions",
            json=payload, timeout=timeout
        )
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"LLM call failed: {e}")
        return None

# ── Video search ───────────────────────────────────────────────────────────────

def _load_seen():
    try:
        return set(json.loads(SEEN_PATH.read_text()))
    except:
        return set()

def _save_seen(seen):
    SEEN_PATH.write_text(json.dumps(list(seen)[-300:]))

def _search(query, n=5):
    try:
        cmd = [YT_BIN, f"ytsearch{n}:{query}", "--print", "id", "--no-playlist", "--quiet", "--no-warnings"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ids = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        log.info(f"[AGI-YT] search '{query[:50]}' → {ids}")
        return ids
    except Exception as e:
        log.warning(f"[AGI-YT] search failed: {e}")
        return []

def _get_title(video_id):
    try:
        cmd = [YT_BIN, f"https://youtube.com/watch?v={video_id}", "--print", "title", "--quiet", "--no-warnings"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except:
        return video_id

def _get_transcript(video_id):
    """Fetch transcript via Tor to bypass IP ban, fallback to direct."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import GenericProxyConfig

    # Try via Tor first
    try:
        pc = GenericProxyConfig(
            http_url="socks5://127.0.0.1:9050",
            https_url="socks5://127.0.0.1:9050"
        )
        api = YouTubeTranscriptApi(proxy_config=pc)
        try:
            segs = list(api.fetch(video_id, languages=["en","en-US","en-GB"]))
        except Exception:
            segs = list(api.fetch(video_id))
        if segs:
            log.info(f"[AGI-YT] Tor transcript OK: {video_id} ({len(segs)} segs)")
            return " ".join(s.text for s in segs)
    except Exception as e:
        log.warning(f"[AGI-YT] Tor failed {video_id}: {e}")

    # Fallback: direct (likely blocked)
    try:
        api2 = YouTubeTranscriptApi()
        try:
            segs = list(api2.fetch(video_id, languages=["en","en-US","en-GB"]))
        except Exception:
            segs = list(api2.fetch(video_id))
        return " ".join(s.text for s in segs)
    except Exception as e:
        log.warning(f"[AGI-YT] transcript failed {video_id}: {e}")
        return ""

def _distill_transcript(transcript, title, llm_fn=None):
    """Extract strong AGI-relevant beliefs from transcript."""
    # Use middle section — usually most substantive
    words = transcript.split()
    n = len(words)
    if n > 2000:
        # Take three sections: 20-40%, 40-60%, 60-80%
        sections = [
            " ".join(words[int(n*0.2):int(n*0.4)]),
            " ".join(words[int(n*0.4):int(n*0.6)]),
            " ".join(words[int(n*0.6):int(n*0.8)]),
        ]
    else:
        sections = [transcript]

    all_beliefs = []
    caller = llm_fn or _llm_call

    for section in sections[:2]:  # max 2 sections per video
        prompt = DISTILL_PROMPT.format(
            transcript=section[:1200],
            n=6
        )

        try:
            if llm_fn:
                result = llm_fn(prompt, system="You extract strong philosophical and scientific claims about intelligence and AGI.")
            else:
                result = _llm_call(prompt)

            if not result or "IRRELEVANT" in result.upper():
                continue

            lines = [l.strip() for l in result.strip().split("\n")
                     if len(l.strip()) > MIN_BELIEF_LEN and not l.strip().startswith("#")]
            all_beliefs.extend(lines[:6])
        except Exception as e:
            log.warning(f"[AGI-YT] distill failed: {e}")

    return all_beliefs[:MAX_BELIEFS]

def _score_belief(belief, llm_fn=None):
    """Score belief strength 0-1."""
    try:
        prompt = SCORE_PROMPT.format(belief=belief[:300])
        if llm_fn:
            result = llm_fn(prompt, system="You rate the strength and specificity of beliefs about intelligence.")
        else:
            result = _llm_call(prompt, timeout=15)
        if result:
            match = re.search(r'(0\.\d+|1\.0|0|1)', result.strip())
            if match:
                return float(match.group(1))
    except:
        pass
    return 0.6  # default

def _is_novel(belief_text, con):
    """Check if belief is genuinely new vs existing graph."""
    try:
        words = [w for w in belief_text.lower().split() if len(w) > 6][:6]
        if not words:
            return True
        match_count = 0
        for w in words:
            rows = con.execute(
                "SELECT COUNT(*) FROM beliefs WHERE LOWER(content) LIKE ? AND confidence > 0.70",
                (f"%{w}%",)
            ).fetchone()
            if rows and rows[0] > 0:
                match_count += 1
        # Novel if fewer than 60% of key words already covered
        return match_count < len(words) * 0.6
    except:
        return True

# ── Store to DB ────────────────────────────────────────────────────────────────

def _store(beliefs_scored, video_id, title, topic, con):
    stored = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for content, confidence in beliefs_scored:
        if len(content) < MIN_BELIEF_LEN or len(content) > 500:
            continue
        try:
            con.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, confidence, topic, source, origin, timestamp, created_at)
                VALUES (?,?,?,?,?,?,?)
            """, (
                content[:500], confidence, topic,
                f"youtube:{video_id}", "agi_youtube_engine",
                now, now
            ))
            stored += 1
        except Exception as e:
            log.debug(f"Store failed: {e}")
    con.commit()
    return stored

# ── Cross-video synthesis ──────────────────────────────────────────────────────

SYNTH_PROMPT = """You have distilled beliefs about AGI from multiple YouTube videos.
Here are the strongest beliefs collected:

{beliefs}

Synthesise these into 3 META-BELIEFS — higher-order insights that emerge from seeing these together.
Each meta-belief should:
- Say something that none of the individual beliefs says alone
- Be relevant to understanding how AGI might be achieved or why it's hard
- Be specific and defensible

One meta-belief per line, no preamble:"""

def _synthesise(all_beliefs, llm_fn=None):
    """Generate cross-video synthesis beliefs."""
    if len(all_beliefs) < 4:
        return []
    sample = "\n".join(f"- {b}" for b in all_beliefs[:12])
    try:
        if llm_fn:
            result = llm_fn(SYNTH_PROMPT.format(beliefs=sample))
        else:
            result = _llm_call(SYNTH_PROMPT.format(beliefs=sample))
        if result:
            lines = [l.strip() for l in result.strip().split("\n")
                     if len(l.strip()) > MIN_BELIEF_LEN]
            return [(l, 0.82) for l in lines[:3]]
    except Exception as e:
        log.warning(f"[AGI-YT] synthesis failed: {e}")
    return []

# ── Main entry point ───────────────────────────────────────────────────────────

def run_agi_youtube_engine(llm_fn=None, cycle=0, max_videos=MAX_VIDEOS):
    """
    Main entry point. Call from run.py every N cycles.
    Returns dict with stats.
    """
    log.info("[AGI-YT] starting distillation run...")
    seen = _load_seen()

    # Pick queries — rotate through AGI hunt + throw-net
    import random
    queries = []
    # Always include 2 AGI-focused queries
    queries.extend(random.sample(AGI_SEARCH_QUERIES, min(3, len(AGI_SEARCH_QUERIES))))
    # Every other cycle add a throw-net query
    if cycle % 75 == 0:
        queries.append(random.choice(THROW_NET_QUERIES))

    # Collect candidate videos
    candidates = []
    for q in queries:
        ids = _search(q, n=3)
        for vid_id in ids:
            if vid_id not in seen and vid_id not in [c[0] for c in candidates]:
                candidates.append((vid_id, q))
        if len(candidates) >= max_videos * 2:
            break

    if not candidates:
        log.info("[AGI-YT] no new videos found")
        return {"videos": 0, "beliefs": 0, "skipped": True}

    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row

    total_beliefs = 0
    videos_done = 0
    all_distilled = []
    results = []

    for vid_id, query in candidates[:max_videos]:
        log.info(f"[AGI-YT] processing: {vid_id} (from: {query[:40]})")

        time.sleep(60)  # rate limit — avoid IP ban
        transcript = _get_transcript(vid_id)
        seen.add(vid_id)

        if not transcript:
            log.info(f"[AGI-YT] no transcript for {vid_id}")
            continue

        title = _get_title(vid_id)
        topic = "agi"  # all AGI engine beliefs go to agi topic

        # Distill
        raw_beliefs = _distill_transcript(transcript, title, llm_fn)
        if not raw_beliefs:
            log.info(f"[AGI-YT] no beliefs distilled from {title[:50]}")
            continue

        # Score + novelty filter
        scored = []
        for belief in raw_beliefs:
            if not _is_novel(belief, con):
                log.debug(f"[AGI-YT] not novel: {belief[:60]}")
                continue
            score = _score_belief(belief, llm_fn)
            if score >= MIN_STRENGTH:
                scored.append((belief, round(score, 3)))
                all_distilled.append(belief)

        if not scored:
            log.info(f"[AGI-YT] no beliefs passed quality filter for {title[:50]}")
            continue

        n = _store(scored, vid_id, title, topic, con)
        total_beliefs += n
        videos_done += 1
        log.info(f"[AGI-YT] ✓ {title[:60]} → {n} beliefs (strength≥{MIN_STRENGTH})")
        results.append({"video_id": vid_id, "title": title, "beliefs": n})

    # Cross-video synthesis
    if all_distilled and videos_done >= 2:
        synth = _synthesise(all_distilled, llm_fn)
        if synth:
            n = _store(synth, "synthesis", "cross-video synthesis", "agi", con)
            total_beliefs += n
            log.info(f"[AGI-YT] synthesis: {n} meta-beliefs generated")

    con.close()
    _save_seen(seen)

    log.info(f"[AGI-YT] done — {videos_done} videos, {total_beliefs} beliefs")
    return {
        "videos": videos_done,
        "beliefs": total_beliefs,
        "results": results,
        "skipped": False,
    }

# ── CLI test ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    result = run_agi_youtube_engine(cycle=0)
    print(f"\nResult: {json.dumps(result, indent=2)}")
