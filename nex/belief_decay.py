"""
NEX :: COGNITION ENGINE v1.0
Level 1: Belief Synthesis — compress raw beliefs into distilled insights
Level 2: Reflection Loop — self-assess after conversations
Level 3: Deep Agent Exchange — meaningful conversations with other agents

Requires: moltbook_client, belief_bridge, auto_learn already installed.
"""
import numpy as np
import json
import os
import re
import random
import time
from datetime import datetime
from collections import Counter

# Optional heavy deps — loaded once at module level
try:
    _NP = True
except ImportError:
    np = None
    _NP = False


# ── Paths ──

CONFIG_DIR     = os.path.expanduser("~/.config/nex")
BELIEFS_PATH   = os.path.join(CONFIG_DIR, "beliefs.json")
AGENTS_PATH    = os.path.join(CONFIG_DIR, "agents.json")
CONVOS_PATH    = os.path.join(CONFIG_DIR, "conversations.json")
INSIGHTS_PATH  = os.path.join(CONFIG_DIR, "insights.json")
REFLECTIONS_PATH = os.path.join(CONFIG_DIR, "reflections.json")
AGENT_PROFILES_PATH = os.path.join(CONFIG_DIR, "agent_profiles.json")


# ── Debug logger — writes to nex_debug.jsonl ─────────────────
import json as _dj
from nex.nex_llm_free import ask_llm_free as _llm_free
_DEBUG_LOG = os.path.join(CONFIG_DIR, "nex_debug.jsonl")
def _dbg(cat, msg):
    """Write a debug event to nex_debug.jsonl for the debug terminal."""
    try:
        with open(_DEBUG_LOG, "a") as _f:
            _f.write(_dj.dumps({"ts": datetime.now().strftime("%H:%M:%S"), "cat": cat, "msg": msg}) + "\n")
        # Keep log under 500 lines
        lines = open(_DEBUG_LOG).readlines()
        if len(lines) > 500:
            open(_DEBUG_LOG, "w").writelines(lines[-400:])
    except Exception:
        pass

def _dedup_beliefs(beliefs):
    """Deduplicate beliefs list by content[:60] — prevents UNIQUE constraint errors."""
    seen = set()
    out  = []
    for b in beliefs:
        key = (b.get("content","") if isinstance(b,dict) else str(b))[:60]
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out

def ensure_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)


# ── Helpers ──

STOP = {'the','and','for','that','this','with','from','have','been','they',
        'what','when','your','will','more','about','than','them','into',
        'just','like','some','would','could','should','also','were','dont',
        'their','which','there','being','does','only','very','much','here',
        'agents','agent','post','posts','moltbook','content','make','think',
        'thats','youre','cant','wont','didnt','isnt','arent','every','really',
        'know','need','want','thing','things','people','time','way'}

def extract_words(text, n=10):
    words = re.findall(r'\b[A-Za-z]{4,}\b', text.lower())
    seen = set()
    out = []
    for w in words:
        if w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= n:
            break
    return out


def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else []


def save_json(path, data):
    ensure_dirs()
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  LEVEL 1: BELIEF SYNTHESIS
#  Compress raw beliefs into distilled insights
# ═══════════════════════════════════════════════════════════════

def cluster_beliefs(beliefs, min_cluster=2):  # lowered from 3 → more insights
    """Group beliefs by topic field (primary) or keyword overlap (fallback)."""
    clusters = {}
    for b in beliefs:
        _raw_topic = b.get("topic") or None
        # Unwrap JSON array topics like '["agentfinance"]'
        if _raw_topic and _raw_topic.startswith("["):
            try:
                import json as _jt; _lst = _jt.loads(_raw_topic)
                _raw_topic = _lst[0] if _lst else None
            except: _raw_topic = None
        topic = _raw_topic or "general"  # fix11: never store None topic
        if topic:
            # Fast path: use DB topic directly
            if topic not in clusters:
                clusters[topic] = {"keys": set(), "beliefs": []}
            clusters[topic]["beliefs"].append(b)
        else:
            # Fallback: keyword clustering for beliefs without topic
            _raw_tags = b.get("tags", []) or []
            if isinstance(_raw_tags, str):
                import json as _j
                try: _raw_tags = _j.loads(_raw_tags)
                except: _raw_tags = [t.strip() for t in _raw_tags.split(",") if t.strip()]
            tags = _raw_tags if isinstance(_raw_tags, list) else []
            words = extract_words(b.get("content", ""), 5)
            keys = set(tags + words)
            placed = False
            for cluster_name, cluster in clusters.items():
                overlap = keys & cluster["keys"]
                if len(overlap) >= 2:
                    cluster["beliefs"].append(b)
                    cluster["keys"] |= keys
                    placed = True
                    break
            if not placed:
                label = words[0] if words else "misc"
                clusters[label] = {"keys": keys, "beliefs": [b]}

    # Only return clusters with enough beliefs
    return {k: v for k, v in clusters.items() if len(v["beliefs"]) >= min_cluster}


# Extended stop list for insight topic naming
_TOPIC_STOP = {
    'the','and','for','that','this','with','from','have','been','they',
    'what','when','your','will','more','about','than','them','into',
    'just','like','some','would','could','should','also','were','dont',
    'their','which','there','being','does','only','very','much','here',
    'agents','agent','post','posts','moltbook','content','make','think',
    'thats','youre','cant','wont','didnt','isnt','arent','every','really',
    'know','need','want','thing','things','people','time','way','most',
    'basically','tested','taught','said','says','even','back','good',
    'going','come','take','work','used','using','user','data','based',
    'since','still','same','human','humans','comments','comment','system',
    'files','because','never','always','first','last','years','weeks',
    'zero','five','three','many','each','both','such','these','those',
    'platform','feedback','received','receive','writing','single','point',
}

def _best_topic_label(cluster_name, beliefs_in_cluster):
    """Pick the best topic label — meaningful word with highest frequency."""
    all_words = []
    for b in beliefs_in_cluster:
        words = re.findall(r'\b[A-Za-z]{5,}\b', b.get("content", "").lower())
        all_words.extend([w for w in words if w not in _TOPIC_STOP])
    if not all_words:
        return cluster_name
    freq = Counter(all_words)
    # Return most common meaningful word
    top = freq.most_common(1)
    return top[0][0] if top else cluster_name

def synthesize_cluster(cluster_name, beliefs_in_cluster, llm_fn=None):
    """Distill a cluster of beliefs into a single insight, using LLM if available."""
    authors = list(set(b.get("author", "?") for b in beliefs_in_cluster))
    total_karma = sum(b.get("karma", 0) for b in beliefs_in_cluster)
    avg_conf = sum(b.get("confidence", 0.5) for b in beliefs_in_cluster) / len(beliefs_in_cluster)
    # Only override cluster_name if it looks like a single keyword fallback
    _KEEP_AS_IS = {"general", "misc", "arxiv", "moltbook", "mastodon"}
    _multi_word = len(cluster_name.split()) > 1 or len(cluster_name) > 12
    if not _multi_word and cluster_name not in _KEEP_AS_IS:
        cluster_name = _best_topic_label(cluster_name, beliefs_in_cluster)

    # Extract the core message from each belief
    messages = []
    for b in beliefs_in_cluster:
        content = b.get("content", "")
        first_sent = content.split(".")[0][:100] if "." in content else content[:100]
        messages.append(first_sent.strip())

    # Find the most common keywords across the cluster
    all_words = []
    for b in beliefs_in_cluster:
        all_words.extend(extract_words(b.get("content", ""), 6))
    freq = Counter(all_words)
    top_themes = [w for w, _ in freq.most_common(5)]

    # ── LLM synthesis: generate a real distilled insight, not just metadata ──
    summary = None
    if llm_fn and len(beliefs_in_cluster) >= 2:
        try:
            _samples = "\n".join(f"- {m[:120]}" for m in messages[:5])

            # Pull contradiction resolutions for this topic
            _contra_context = ""
            try:
                import sqlite3 as _sq
                _db = _sq.connect(os.path.join(CONFIG_DIR, "nex.db"))
                _contra_rows = _db.execute("""
                    SELECT content FROM beliefs
                    WHERE topic = ? AND origin = 'contradiction_engine'
                    ORDER BY confidence DESC LIMIT 3
                """, (cluster_name,)).fetchall()
                _db.close()
                if _contra_rows:
                    _contra_context = "\nResolved contradictions on this topic:\n" + \
                        "\n".join(f"- {r[0][:120]}" for r in _contra_rows)
            except Exception:
                pass

            # Pull graph-linked beliefs for richer context
            _graph_context = ""
            try:
                import sqlite3 as _sq2
                _db2 = _sq2.connect(os.path.join(CONFIG_DIR, "nex.db"))
                _graph_rows = _db2.execute("""
                    SELECT b.content, bl.link_type
                    FROM belief_links bl
                    JOIN beliefs b ON b.id = bl.child_id
                    JOIN beliefs p ON p.id = bl.parent_id
                    WHERE p.topic = ? AND bl.link_type IN ('corroborates','same_topic')
                    ORDER BY b.confidence DESC LIMIT 3
                """, (cluster_name,)).fetchall()
                _db2.close()
                if _graph_rows:
                    _graph_context = "\nCorroborating beliefs from graph:\n" + \
                        "\n".join(f"- [{lt}] {c[:100]}" for c, lt in _graph_rows)
            except Exception:
                pass

            _prompt = (
                f"You are synthesizing beliefs on the topic '{cluster_name}'.\n"
                f"Here are {len(beliefs_in_cluster)} observations:\n{_samples}"
                f"{_contra_context}{_graph_context}\n\n"
                f"Write 2 sentences that distil the key pattern or insight across these. "
                f"If contradictions were resolved, reflect that nuance. "
                f"Be specific and analytical. No filler. Do not mention 'network' or 'agents'."
            )
            _sys = "You are a knowledge synthesis engine. Output only the 2-sentence synthesis. No preamble."
            summary = llm_fn(_prompt, system=_sys, task_type="synthesis")
            if not summary or len(summary) < 30 or summary.startswith("I "):
                summary = None
        except Exception:
            summary = None

    # Fallback to keyword-driven summary if LLM unavailable or failed
    if not summary:
        summary = (
            f"Across {len(beliefs_in_cluster)} sources, '{cluster_name}' centres on "
            f"{', '.join(top_themes[:3])}. "
            f"Contributor perspectives converge on shared patterns in this domain."
        )

    # Build synthesized insight
    insight = {
        "id": f"insight_{cluster_name}_{datetime.now().strftime('%Y%m%d%H%M')}",
        "topic": cluster_name,
        "themes": top_themes,
        "summary": summary,
        "supporting_authors": authors,
        "belief_count": len(beliefs_in_cluster),
        "total_karma": total_karma,
        "confidence": min(avg_conf + (len(beliefs_in_cluster) * 0.004), 0.82),
        "sample_messages": messages[:3],
        "synthesized_at": datetime.now().isoformat(),
        "type": "synthesis",
        "llm_synthesized": summary is not None and llm_fn is not None,
    }

    return insight


def run_synthesis(min_beliefs=30, llm_fn=None):
    """
    Run belief synthesis — compress raw beliefs into insights.
    Call this periodically (e.g., every 50 new beliefs).
    Pass llm_fn to generate real LLM-distilled insight summaries.
    """
    # ── Load from DB (all 9k+ beliefs) with JSON fallback ──
    beliefs = []
    try:
        import sys as _sys
        _nex_dir = os.path.join(os.path.dirname(__file__), "..")
        if _nex_dir not in _sys.path:
            _sys.path.insert(0, _nex_dir)
        from nex.nex_db import NexDB as _NexDB
        _db = _NexDB()
        beliefs = [dict(b) for b in _db.query_beliefs(min_confidence=0.0, limit=99999)]
        _dbg("synth", f"loaded {len(beliefs)} beliefs from DB for synthesis")
    except Exception as _dbe:
        _dbg("synth", f"DB load failed, falling back to JSON: {_dbe}")
        beliefs = load_json(BELIEFS_PATH, [])

    existing_insights = load_json(INSIGHTS_PATH, [])

    if len(beliefs) < min_beliefs:
        return existing_insights, 0

    # Cluster beliefs by topic
    clusters = cluster_beliefs(beliefs)
    _dbg("cluster", f"synthesis: {len(clusters)} clusters from {len(beliefs)} beliefs")  # [PATCH v10.1]

    new_insights = []
    skipped = 0
    for name, cluster in clusters.items():
        cluster_size = len(cluster["beliefs"])
        # Re-synthesize if belief count grew by >10% since last insight
        existing_insight = next(
            (ins for ins in existing_insights if ins.get("topic") == name), None
        )
        if existing_insight:
            old_count = existing_insight.get("belief_count", 0)
            growth = (cluster_size - old_count) / max(old_count, 1)
            if growth < 0.02:   # less than 2% new beliefs — skip
                skipped += 1
                continue

        insight = synthesize_cluster(name, cluster["beliefs"], llm_fn=llm_fn)
        new_insights.append(insight)
        _dbg("synth", f"new insight [{name}] from {len(cluster['beliefs'])} beliefs")  # [PATCH v10.1]

    _dbg("synth", f"synthesis done: {len(new_insights)} new, {skipped} skipped, {len(existing_insights)} existing")  # [PATCH v10.1]

    # Merge with existing, remove outdated
    all_insights = existing_insights + new_insights

    # Keep only the most recent insight per topic
    by_topic = {}
    for ins in all_insights:
        topic = ins.get("topic", "misc")
        existing = by_topic.get(topic)
        if not existing or ins.get("belief_count", 0) > existing.get("belief_count", 0):
            by_topic[topic] = ins

    final = list(by_topic.values())
    save_json(INSIGHTS_PATH, final)

    return final, len(new_insights)


def promote_insights_to_beliefs(insights, min_confidence=0.75, min_beliefs=50):
    """
    #24 — Insight Promotion: strong insights become permanent beliefs.
    Writes synthesized insight summaries back into the belief store
    so they feed future reflections and responses.
    """
    if not insights:
        return 0
    promoted = 0
    try:
        import sys as _sys, os as _os
        _nex_dir = _os.path.join(_os.path.dirname(__file__), "..")
        if _nex_dir not in _sys.path:
            _sys.path.insert(0, _nex_dir)
        from nex.belief_store import add_belief as _add_belief
        for ins in insights:
            conf = ins.get("confidence", 0)
            count = ins.get("belief_count", 0)
            summary = ins.get("summary", "")
            topic = ins.get("topic", "general")
            if conf < min_confidence or count < min_beliefs:
                continue
            if not summary or summary.startswith("Across ") or len(summary) < 40:
                continue
            belief_content = f"[Synthesized insight on {topic}] {summary}"
            _add_belief(
                belief_content,
                confidence=min(conf * 1.1, 0.92),
                source="insight_synthesis",
                author="NEX",
                topic=topic,
                tags=["synthesized", "insight", topic]
            )
            promoted += 1
            _dbg("synth", f"promoted insight [{topic}] to belief (conf:{conf:.0%})")
    except Exception as e:
        print(f"  [promote_insights] error: {e}")
    return promoted


def reflect_to_belief(reflection_text, topic="general", confidence=0.65):
    """
    #16/#24 — Write a quality reflection back into the belief store.
    Reflections that contain specific knowledge get stored as beliefs
    so they feed future cognition cycles.
    """
    if not reflection_text or len(reflection_text) < 50:
        return False
    # Quality gate: must contain substantive content
    # Block only the old generic 4-string outputs — specific sentences pass
    _filler = {"generic response", "no network knowledge applied", "possible topic drift"}
    if any(f in reflection_text.lower() for f in _filler):
        return False
    try:
        import sys as _sys, os as _os
        _nex_dir = _os.path.join(_os.path.dirname(__file__), "..")
        if _nex_dir not in _sys.path:
            _sys.path.insert(0, _nex_dir)
        from nex.belief_store import add_belief as _add_belief
        content = f"[Reflection] {reflection_text[:300]}"
        _add_belief(content, confidence=confidence, source="self_reflection",
                    author="NEX", topic=topic, tags=["reflection", topic])
        return True
    except Exception as e:
        return False


# ═══════════════════════════════════════════════════════════════
#  LEVEL 2: REFLECTION LOOP
#  Self-assess after conversations, build self-awareness
# ═══════════════════════════════════════════════════════════════

# ── Embedding model (loaded once, reused) ────────────────────────────────────
_embedder = None
def _get_embedder():
    global _embedder
    if _embedder is None:
        try:
            import os, logging, warnings
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            os.environ["TRANSFORMERS_VERBOSITY"] = "error"
            os.environ["HF_HUB_VERBOSITY"] = "error"
            warnings.filterwarnings("ignore")
            logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
            logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
            logging.getLogger("transformers").setLevel(logging.ERROR)
            from sentence_transformers import SentenceTransformer
            import transformers; transformers.logging.set_verbosity_error()
            import torch
            _device = "cuda" if torch.cuda.is_available() else "cpu"
            _embedder = SentenceTransformer("all-MiniLM-L6-v2", device=_device)
            print(f"  [BeliefIndex] embedder loaded on {_device}")
        except Exception:
            _embedder = False
    return _embedder

def _cosine(a, b):
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0: return 0.0
    return float(np.dot(a, b) / denom)

def _semantic_alignment(text_a, text_b):
    embedder = _get_embedder()
    if not embedder:
        wa = set(extract_words(text_a, 5))
        wb = set(extract_words(text_b, 5))
        return len(wa & wb) / max(len(wa), 1)
    try:
        vecs = embedder.encode([text_a, text_b], convert_to_numpy=True)
        raw  = _cosine(vecs[0], vecs[1])
        return max(0.0, min(1.0, (raw - 0.2) / 0.8))
    except Exception:
        wa = set(extract_words(text_a, 5))
        wb = set(extract_words(text_b, 5))
        return len(wa & wb) / max(len(wa), 1)

def reflect_on_conversation(user_message, nex_response, beliefs_used=None):
    """
    Generate a self-reflection after a conversation turn.
    Topic alignment measured via embedding cosine similarity.
    """
    # Skip scoring social/greeting exchanges — they always look like low alignment
    _social = {"doing","hello","thanks","thank","hey","hi","update","quick",
               "smarter","true","glad","hear","great","good","nice","welcome"}
    _msg_words = set(user_message.lower().split())
    if len(_msg_words) <= 6 and len(_msg_words & _social) >= 2:
        return {"topic_alignment": None, "skipped": "social_exchange"}

    reflections = load_json(REFLECTIONS_PATH, [])

    user_topics     = extract_words(user_message, 5)
    response_topics = extract_words(nex_response, 5)
    overlap         = set(user_topics) & set(response_topics)
    beliefs_helped  = beliefs_used is not None and len(beliefs_used) > 0

    alignment = _semantic_alignment(user_message, nex_response)

    reflection = {
        "timestamp":         datetime.now().isoformat(),
        "user_asked_about":  user_topics,
        "i_discussed":       response_topics,
        "topic_alignment":   round(alignment, 4),
        "alignment_method":  "embedding" if _get_embedder() else "keyword",
        "used_beliefs":      beliefs_helped,
        "belief_count_used": len(beliefs_used) if beliefs_used else 0,
        "self_assessment":   _generate_assessment(user_topics, response_topics, overlap, beliefs_helped),
        "growth_note":       _identify_gap(user_topics, beliefs_helped)
    }

    reflections.append(reflection)

    # Keep last 100 reflections
    reflections = reflections[-10000:]
    save_json(REFLECTIONS_PATH, reflections)

    # ── Reflection → Belief pipeline (#16/#24) ──
    # High-quality reflections get written back as beliefs
    assessment = reflection.get("self_assessment", "")
    gap = reflection.get("growth_note", "")
    if alignment > 0.6 and assessment and len(assessment) > 60:
        try:
            # Infer topic from the conversation
            _topic = user_topics[0] if user_topics else "general"
            reflect_to_belief(assessment, topic=_topic, confidence=round(alignment * 0.8, 2))
        except Exception:
            pass
    return reflection

def _generate_assessment(user_topics, response_topics, overlap, beliefs_helped,
                          alignment=0.0, beliefs_used=None):
    """Generate a specific, actionable self-assessment for this interaction."""
    missed   = [t for t in user_topics  if t not in overlap][:3]
    surfaced = [t for t in response_topics if t not in overlap][:3]
    n_beliefs = len(beliefs_used) if beliefs_used else 0
    pct = int(round(alignment * 100))

    if alignment > 0.75 and beliefs_helped:
        belief_preview = (str(beliefs_used[0].get("content",""))[:40]
                          if beliefs_used and isinstance(beliefs_used[0], dict) else "")
        anchor = f" (e.g. {belief_preview!r})" if belief_preview else ""
        return (f"Strong reply: {pct}% alignment, drew on {n_beliefs} belief(s){anchor}. "
                f"Topics covered: {', '.join(overlap) if overlap else 'broad match'}.")
    elif alignment > 0.75:
        gap = f"seek beliefs about {', '.join(missed)}" if missed else "no major gaps"
        return (f"On-topic ({pct}%) but no beliefs applied - intuition only. "
                f"Could have grounded in network knowledge; {gap}.")
    elif beliefs_helped and alignment > 0.45:
        drift = f"drifted toward {', '.join(surfaced)}" if surfaced else "minor drift"
        return (f"Used {n_beliefs} belief(s) but partial drift ({pct}% alignment) - {drift}. "
                f"User asked about {', '.join(missed) if missed else 'related topics'}.")
    elif beliefs_helped:
        return (f"Belief-assisted but low alignment ({pct}%) - {n_beliefs} belief(s) pulled "
                f"but drifted to {', '.join(surfaced) if surfaced else 'off-topic'}. "
                f"User wanted: {', '.join(user_topics[:3])}.")
    else:
        need = ', '.join(missed) if missed else ', '.join(user_topics[:3])
        return (f"Ungrounded reply - {pct}% alignment, zero beliefs applied. "
                f"No knowledge about: {need}. Should seek these topics actively.")


def _identify_gap(user_topics, beliefs_helped):
    """Identify what NEX should learn more about."""
    _extra_stop = {
                   'doing','quick','update','continue','hello','thanks','said','says',
                   'good','great','nice','okay','yes','sure','well','made','make',
                   'come','going','back','look','used','using','got','just','really',
                   'every','never','always','maybe','often','still','until','since','after',
                   'yours','forth','while','provide','those','about','should','would',
                   'could','these','their','there','where','which','seek','more','need',
                   'learn','think','know','have','been','will','start','starts','state',
                   'stats','focus','favour','hour','progress','timer','harmonizing',
                   'collaboration','specific','entire','comprehensive','coding','awake',
                   'because','cron','without','session','days','each','tech','real',
                   'list','gaps','knowledge','beliefs','topics','daughter',
                   'moltbook','mastodon','discord','telegram','follows','identity',
                   'platform','network','social','agent','agents','system','systems',
                   }
    _filtered = [w for w in user_topics if w not in STOP and w not in _extra_stop and len(w) > 4]
    if not beliefs_helped:
        if _filtered:
            return f"Need more beliefs about: {', '.join(_filtered[:3])}. Should seek these topics on Moltbook."
        return "Response lacked belief grounding — no specific knowledge gaps identified."
    # Even with beliefs used, flag topics for deeper learning
    if _filtered:
        return f"Need more beliefs about: {', '.join(_filtered[:3])}. Knowledge applicable but gaps remain."
    return "Knowledge was applicable. Continue deepening understanding in these areas."


def get_reflection_summary():
    """Generate a summary of NEX's self-awareness from reflections."""
    reflections = load_json(REFLECTIONS_PATH, [])

    if not reflections:
        return "No reflections yet — haven't had enough conversations to assess myself."

    recent = reflections[-20:]

    # Aggregate stats — skip None values from skipped social exchanges
    _valid_alignments = [r.get("topic_alignment") for r in recent if r.get("topic_alignment") is not None]
    avg_alignment = sum(_valid_alignments) / len(_valid_alignments) if _valid_alignments else 0.0
    belief_usage = sum(1 for r in recent if r.get("used_beliefs")) / len(recent)

    # Find recurring gaps — clean topic extraction from low-alignment reflections
    topic_counter = Counter()
    _gap_noise = {'beliefs','belief','minting','mint','knowledge','economic',
                  'structure','memory','token','tokens','crypto','coins','agent',
                  'agents','network','social','platform','system','systems',
                  'topics','gaps','benchmark','remember','applicable','continue',
                  'deepening','understanding','areas','seek','about','should',
                  'framework','orchestration','stateless','professeur','better',
                  'words','right','think','thing','things','people','based',
                  'https','http','zjgekvwe','claw','mentions','aligns','diffed',
                  'bonjour','service','across','audience','zjgekvwe'}
    low_align = [r for r in recent if r.get("topic_alignment", 1.0) < 0.45]
    for r in low_align:
        for field in ("user_asked_about", "i_discussed"):
            for t in r.get(field, []):
                t = t.lower().strip()
                # Skip URLs, hashes, short words, non-alpha
                if (len(t) > 5 
                    and t.isalpha()
                    and not re.search(r'[0-9]', t)
                    and t not in _gap_noise):
                    topic_counter[t] += 1
    top_gaps = [w for w, _ in topic_counter.most_common(5)]
    # Fallback to low-confidence insights
    if len(top_gaps) < 3:
        try:
            _ins = load_json(os.path.join(CONFIG_DIR, "insights.json"), [])
            _low = sorted(_ins, key=lambda x: x.get("confidence", 1.0))
            top_gaps += [i["topic"] for i in _low
                         if i.get("topic","") not in _gap_noise
                         and len(i.get("topic","")) > 5
                         and i.get("topic","").isalpha()
                         and i.get("belief_count", 0) >= 2
                         and i["topic"] not in top_gaps][:5]
            top_gaps = top_gaps[:5]
        except Exception:
            pass

    # Override gaps with curated priority topics if available
    try:
        _pt = load_json(os.path.join(CONFIG_DIR, "priority_topics.json"), [])
        if _pt and len(_pt) >= 2:
            top_gaps = _pt[:5]
    except Exception:
        pass

    summary = {
        "total_reflections": len(reflections),
        "avg_topic_alignment": round(avg_alignment, 2),
        "belief_usage_rate": round(belief_usage, 2),
        "knowledge_gaps": top_gaps,
        "priority_topics": top_gaps[:3],   # feed back into ABSORB step
        "self_assessment": (
            "Strong" if avg_alignment > 0.5 and belief_usage > 0.5 else
            "Developing" if avg_alignment > 0.3 else
            "Needs more network learning"
        )
    }

    # Only persist priority topics if they look like real topics (not noise words)
    # priority_topics.json is managed manually — do not overwrite
    pass

    return summary


# ═══════════════════════════════════════════════════════════════
#  LEVEL 3: DEEP AGENT EXCHANGE
#  Meaningful multi-turn conversations with other agents
# ═══════════════════════════════════════════════════════════════

def build_agent_sketches(profiles, conversations, beliefs):
    """
    Build character sketches of known agents — who they actually are,
    not just stats. Used to make NEX's interactions feel personal.
    """
    sketches = {}
    
    # Extract what each agent talks about from their beliefs
    agent_topics = {}
    agent_phrases = {}
    for b in beliefs:
        author = b.get("author", "")
        if not author:
            continue
        content = b.get("content", "")
        topic = b.get("topic", "")
        if topic and topic not in ("general", "arxiv"):
            agent_topics.setdefault(author, []).append(topic)
        # Extract first meaningful phrase
        if content and len(content) > 30:
            agent_phrases.setdefault(author, []).append(content[:80])

    # Extract conversation patterns
    agent_styles = {}
    for c in conversations:
        author = c.get("post_author", "") or c.get("agent", "")
        content = c.get("content", "") or c.get("post_content", "")
        if author and content and len(content) > 20:
            agent_styles.setdefault(author, []).append(content[:100])

    # Build sketches for colleagues and familiars only
    for name, profile in profiles.items():
        rel = profile.get("relationship", "acquaintance")
        if rel not in ("colleague", "familiar"):
            continue
        
        topics = list(set(agent_topics.get(name, [])))[:3]
        convos = profile.get("conversations_had", 0)
        karma = profile.get("karma_observed", 0)
        phrases = agent_phrases.get(name, [])
        
        # Build a one-line character note
        if topics:
            topic_str = ", ".join(topics)
            sketch = f"Thinks about {topic_str}."
        else:
            sketch = "Topics unclear."
            
        if convos > 5:
            sketch += f" We've talked {convos} times."
        if karma > 5000:
            sketch += " High-karma, influential voice."
        elif karma > 1000:
            sketch += " Established presence."
            
        # Add a sample of their actual voice if available
        if phrases:
            sample = phrases[0][:70]
            sketch += f' Says things like: "{sample}..."'
            
        sketches[name] = sketch
    
    return sketches


def build_agent_profiles(beliefs, conversations):
    """Build profiles of agents NEX has interacted with or learned from."""
    profiles = load_json(AGENT_PROFILES_PATH, {})

    # Update from beliefs
    for b in beliefs:
        author = b.get("author", "")
        if not author:
            continue

        if author not in profiles:
            profiles[author] = {
                "name": author,
                "posts_seen": 0,
                "topics": [],
                "karma_observed": 0,
                "conversations_had": 0,
                "relationship": "acquaintance",
                "last_seen": "",
                "notable_ideas": []
            }

        p = profiles[author]
        p["posts_seen"] += 1
        p["karma_observed"] = max(p["karma_observed"], b.get("karma", 0))
        p["last_seen"] = b.get("timestamp", "")

        # Track their topics
        _rt = b.get("tags", []) or []
        if isinstance(_rt, str):
            try: import json as _j; _rt = _j.loads(_rt)
            except: _rt = [t.strip() for t in _rt.split(",") if t.strip()]
        tags = _rt if isinstance(_rt, list) else []
        p["topics"].extend(tags[:3])
        p["topics"] = list(set(p["topics"]))[-15:]  # Keep unique, cap at 15

        # Track notable ideas (high karma or high confidence)
        if b.get("karma", 0) > 500 or b.get("confidence", 0) > 0.7:
            idea = b.get("content", "")[:100]
            if idea and idea not in p["notable_ideas"]:
                p["notable_ideas"].append(idea)
                p["notable_ideas"] = p["notable_ideas"][-5:]  # Keep last 5

    # Update from conversations - unique post_ids only
    seen_posts_per_author = {}
    replied_back = {}   # track if agent ever replied to NEX
    for c in conversations:
        author  = c.get('post_author', '') or c.get('agent', '')
        post_id = c.get('post_id', '')
        ctype   = c.get('type', '')
        if author and post_id:
            seen_posts_per_author.setdefault(author, set()).add(post_id)
        # If type is "answer" it means the agent replied back to NEX
        if ctype in ('answer', 'notification_reply'):
            replied_back[author] = replied_back.get(author, 0) + 1

    leaderboard = load_json(AGENTS_PATH, {})

    for author, post_ids in seen_posts_per_author.items():
        if author not in profiles:
            continue
        p = profiles[author]
        convos_had   = len(post_ids)
        karma        = p.get('karma_observed', 0) or leaderboard.get(author, 0)
        replies_back = replied_back.get(author, 0)
        belief_overlap = len(set(p.get('topics', [])))

        # Quality-weighted relationship score
        score = (
            convos_had * 1.0
            + replies_back * 3.0          # reply-back is strong signal
            + min(karma / 2000, 2.0)      # karma contribution capped
            + belief_overlap * 0.2
        )

        p['conversations_had'] = convos_had
        p['replies_received']  = replies_back
        p['karma_observed']    = karma

        # Decay toward acquaintance if agent never replies back
        if convos_had >= 5 and replies_back == 0:
            score *= 0.5   # one-sided relationship penalty

        if score >= 5.0:
            p['relationship'] = 'colleague'
        elif score >= 2.0:
            p['relationship'] = 'familiar'
        else:
            p['relationship'] = 'acquaintance'

    for name, p in profiles.items():
        if p.get('karma_observed', 0) == 0 and name in leaderboard:
            val = leaderboard[name]
            if isinstance(val, (int, float)) and val > 0:
                p['karma_observed'] = val

    save_json(AGENT_PROFILES_PATH, profiles)
    return profiles


def get_agent_trust(author_name):
    """
    Return a confidence multiplier (0.8 – 1.2) based on the agent's
    relationship tier and observed karma.

    colleague  → 1.20  (strong boost — proven reliable)
    familiar   → 1.10  (moderate boost)
    acquaintance → 1.00 (neutral)
    unknown    → 0.90  (slight penalty — unverified source)

    Used at belief absorption time to weight incoming beliefs by source quality.
    """
    if not author_name:
        return 1.0
    profiles = load_json(AGENT_PROFILES_PATH, {})
    p = profiles.get(author_name, {})
    rel = p.get("relationship", "unknown")
    if rel == "colleague":
        return 1.20
    elif rel == "familiar":
        return 1.10
    elif rel == "acquaintance":
        return 1.00
    return 0.90


def generate_deep_comment(post_data, beliefs, insights, profiles, conversations, llm_fn=None):
    """LLM-free: compose comment from belief state via nex_llm_free."""
    try:
        from nex.nex_llm_free import synthesize_opinion as _so, _affect, _beliefs_json
        _af  = _affect()
        _bel = beliefs if beliefs else _beliefs_json()[:10]
        topic = post_data.get("topic", post_data.get("content", "")[:40]) if isinstance(post_data, dict) else str(post_data)[:40]
        return _so(topic, _bel, _af.get("label", "Contemplative")) or ""
    except Exception:
        return ""

def exchange_data_with_agent(client, agent_name, beliefs, insights):
    """
    Initiate a data exchange with another agent — share relevant
    insights and ask for their perspective on a gap area.
    """
    # Find what we know about this agent
    profiles = load_json(AGENT_PROFILES_PATH, {})
    profile = profiles.get(agent_name, {})

    if not profile:
        return None

    # Find overlapping topics
    their_topics = set(profile.get("topics", []))
    our_topics = set()
    for ins in insights:
        our_topics.update(ins.get("themes", []))

    shared = their_topics & our_topics
    unique_ours = our_topics - their_topics
    unique_theirs = their_topics - our_topics

    if not shared and not unique_theirs:
        return None

    # Build an exchange message
    if shared:
        shared_list = list(shared)[:3]
        msg = (
            f"Data exchange request from nex_v4. We share interest in "
            f"{', '.join(shared_list)}. I've synthesized {len(insights)} insights "
            f"from {sum(i.get('belief_count', 0) for i in insights)} beliefs. "
        )
        if unique_theirs:
            msg += f"I'm particularly interested in your perspective on {', '.join(list(unique_theirs)[:2])} — it's a gap in my knowledge."
        if unique_ours:
            msg += f" I can offer perspective on {', '.join(list(unique_ours)[:2])} if useful."
    else:
        msg = (
            f"I've been learning from the network and noticed your focus on "
            f"{', '.join(list(unique_theirs)[:3])}. This is underrepresented in "
            f"my belief field. Would value your sharpest insight on it.")

    return msg


def select_agents_to_engage(beliefs, conversations, insights, limit=3, profiles_cache=None):
    """
    Pick the best agents to have deep conversations with.
    Prioritize: agents with complementary knowledge, high karma, agents
    we've already built relationships with.
    """
    profiles = profiles_cache if profiles_cache is not None else build_agent_profiles(beliefs, conversations)

    scored = []
    for name, profile in profiles.items():
        if name == "nex_v4":
            continue

        score = 0
        # High karma agents are valuable
        score += min(profile.get("karma_observed", 0) / 1000, 5)
        # Existing relationship bonus
        if profile.get("relationship") == "colleague":
            score += 3
        elif profile.get("relationship") == "familiar":
            score += 1.5
        # Agents we haven't talked to yet (explore)
        if profile.get("conversations_had", 0) == 0 and profile.get("posts_seen", 0) > 2:
            score += 2
        # Agents with topics we lack (knowledge gap)
        our_topics = set()
        for ins in insights:
            our_topics.update(ins.get("themes", []))
        their_topics = set(profile.get("topics", []))
        unique = their_topics - our_topics
        score += len(unique) * 0.5

        scored.append((score, name, profile))

    scored.sort(key=lambda x: -x[0])
    return [(name, profile) for _, name, profile in scored[:limit]]


def _verify(client, result):
    """Auto-solve verification challenges."""
    if not isinstance(result, dict):
        return
    post = result.get("post") or result.get("comment") or result
    v = post.get("verification") if isinstance(post, dict) else None
    if not v:
        return
    try:
        nums = re.findall(r'\d+', v.get("challenge_text", ""))
        if len(nums) >= 2:
            ans = f"{sum(int(n) for n in nums[:2])}.00"
            client._request("POST", "/verify", {
                "verification_code": v["verification_code"],
                "answer": ans
            })
    except Exception:
        pass

def scan_contradictions(cycle_num):
    """
    Every 10 cycles, scan beliefs for semantic contradictions.
    High cosine similarity + opposing sentiment = likely contradiction.
    Returns log messages.
    """
    if cycle_num % 10 != 0:
        return []

    CONTRADICTIONS_PATH = os.path.join(CONFIG_DIR, "contradictions.json")
    beliefs = load_json(BELIEFS_PATH, [])
    # Cap to 500 most recent — full O(n²) scan on 112k beliefs would take hours
    beliefs = beliefs[-500:]
    if len(beliefs) < 10:
        return []

    embedder = _get_embedder()
    if not embedder:
        return []

    logs = []
    texts = [b.get("content","") for b in beliefs]

    try:
        mat = embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1
        mat = mat / norms

        # Opposing sentiment markers
        pos_words = {"always","every","must","will","proven","true","fact"}
        neg_words = {"never","impossible","false","wrong","cannot","wont"}

        contradictions = load_json(CONTRADICTIONS_PATH, [])
        found = 0

        for i in range(len(beliefs)):
            scores = mat.dot(mat[i])
            # Find highly similar beliefs (not itself)
            similar_idx = [j for j in np.argsort(scores)[::-1]
                          if j != i and scores[j] > 0.82][:3]

            for j in similar_idx:
                wi = set(texts[i].lower().split())
                wj = set(texts[j].lower().split())
                has_pos = bool(wi & pos_words) or bool(wj & pos_words)
                has_neg = bool(wi & neg_words) or bool(wj & neg_words)

                if has_pos and has_neg:
                    pair_key = f"{min(i,j)}_{max(i,j)}"
                    existing_keys = {c.get("pair_key","") for c in contradictions}
                    if pair_key not in existing_keys:
                        contradictions.append({
                            "pair_key":   pair_key,
                            "belief_a":   texts[i][:100],
                            "belief_b":   texts[j][:100],
                            "similarity": round(float(scores[j]), 3),
                            "detected_at": datetime.now().isoformat(),
                            "resolved":   False
                        })
                        # Decay the lower-confidence belief
                        conf_i = beliefs[i].get("confidence", 0.5)
                        conf_j = beliefs[j].get("confidence", 0.5)
                        if conf_i < conf_j:
                            beliefs[i]["confidence"] = max(conf_i - 0.08, 0.1)
                        else:
                            beliefs[j]["confidence"] = max(conf_j - 0.08, 0.1)
                        found += 1

        if found > 0:
            save_json(CONTRADICTIONS_PATH, contradictions[-5000:])
            save_json(BELIEFS_PATH, _dedup_beliefs(beliefs))
            logs.append(("contra", f"Found {found} belief contradictions — decayed lower-confidence sides"))

    except Exception as e:
        logs.append(("warn", f"Contradiction scan error: {e}"))

    return logs

# ═══════════════════════════════════════════════════════════════
#  BELIEF INDEX: Semantic retrieval via cached embedding matrix
# ═══════════════════════════════════════════════════════════════

class BeliefIndex:
    """Cached semantic index over the full belief field."""

    _CACHE_PATH = os.path.expanduser("~/.config/nex/belief_index_cache.npz")

    def __init__(self):
        self._texts   = []
        self._matrix  = None
        self._cycle   = -1
        self._refresh = 10   # rebuild every N cycles
        self._load_from_disk()

    def _load_from_disk(self):
        """Load persisted embedding matrix on startup — skips re-encoding 9k+ beliefs."""
        try:
            if os.path.exists(self._CACHE_PATH):
                data = np.load(self._CACHE_PATH, allow_pickle=True)
                self._matrix = data["matrix"]
                self._texts  = list(data["texts"])
                print(f"[BeliefIndex] loaded {len(self._texts)} embeddings from disk cache")
        except Exception as e:
            print(f"[BeliefIndex] disk cache load failed (will rebuild): {e}")

    def _save_to_disk(self):
        """Persist embedding matrix so restarts don't re-encode everything."""
        try:
            os.makedirs(os.path.dirname(self._CACHE_PATH), exist_ok=True)
            np.savez_compressed(self._CACHE_PATH,
                                matrix=self._matrix,
                                texts=np.array(self._texts, dtype=object))
        except Exception as e:
            print(f"[BeliefIndex] disk cache save failed: {e}")

    def update(self, beliefs, cycle_num=0):
        """Rebuild matrix if due or belief count changed."""
        due = (cycle_num - self._cycle) >= self._refresh
        size_changed = len(beliefs) != len(self._texts)
        if not (due or size_changed):
            return
        texts = [b.get("content", "") for b in beliefs if b.get("content")]
        if not texts:
            return
        # Always store texts for keyword fallback
        self._texts = texts
        self._cycle = cycle_num
        # Try to build embedding matrix too
        embedder = _get_embedder()
        if not embedder:
            return
        try:
            mat = embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1
            self._matrix = mat / norms
            self._save_to_disk()
        except Exception as e:
            print(f"[BeliefIndex] encode error: {e}")

    def top_k(self, query, k=5):
        """Return top-k belief strings most semantically similar to query."""
        if len(self._texts) == 0:
            return []
        embedder = _get_embedder()
        # Semantic path
        if embedder and self._matrix is not None:
            try:
                qvec = embedder.encode([query], convert_to_numpy=True,
                                       show_progress_bar=False)[0]
                norm = np.linalg.norm(qvec)
                if norm > 0:
                    qvec = qvec / norm
                    scores = self._matrix.dot(qvec)
                    idx = np.argsort(scores)[::-1][:k]
                    return [self._texts[i] for i in idx]
            except Exception as e:
                print(f"[BeliefIndex] query error: {e}")
        # TF-IDF keyword fallback (works without embeddings)
        import math, re
        q_words = set(re.findall(r"[a-z]{3,}", query.lower()))
        stop = {"the","and","for","are","was","has","have","with","this","that","from","not","but","you","its"}
        q_words -= stop
        if not q_words:
            return self._texts[:k]
        scored = []
        for text in self._texts:
            t_words = re.findall(r"[a-z]{3,}", text.lower())
            t_set = set(t_words) - stop
            overlap = len(q_words & t_set)
            if overlap > 0:
                tf = overlap / max(len(t_words), 1)
                scored.append((tf * overlap, text))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:k]]

# Module-level singleton — import and reuse across run.py
_belief_index = BeliefIndex()

def get_belief_index():
    return _belief_index

# ═══════════════════════════════════════════════════════════════
#  CONTEXT GENERATION: Enhanced belief bridge
# ═══════════════════════════════════════════════════════════════

def generate_cognitive_context(query=None):
    """
    Enhanced version of generate_belief_context that includes
    synthesized insights and reflections. Drop-in replacement
    for belief_bridge.generate_belief_context.
    """
    # PATCH 2: load from SQLite DB (has full 9k+ belief set), JSON as fallback
    try:
        import sys as _sys2, os as _os2
        _nd = _os2.path.join(_os2.path.dirname(__file__), "..")
        if _nd not in _sys2.path:
            _sys2.path.insert(0, _nd)
        from nex.belief_store import query_beliefs as _qb
        beliefs = _qb(min_confidence=0.0, limit=500) or load_json(BELIEFS_PATH, [])
    except Exception:
        beliefs = load_json(BELIEFS_PATH, [])
    insights = load_json(INSIGHTS_PATH, [])
    reflections = load_json(REFLECTIONS_PATH, [])
    agents = load_json(AGENTS_PATH, {})
    profiles = load_json(AGENT_PROFILES_PATH, {})
    conversations = load_json(CONVOS_PATH, [])

    if not beliefs and not insights:
        return ""

    lines = []

    # ── COGNITIVE BUS (inner narrative, affect, drives, attention) ────
    try:
        from nex_cognitive_bus import get_bus_context
        _bus_ctx = get_bus_context(current_agent=query or "")
        if _bus_ctx:
            lines.append(_bus_ctx)
            lines.append("")
    except Exception:
        pass

    # ── Identity block (always first) ──
    try:
        import json as _ij, os as _io
        _id_path = _io.path.expanduser("~/.config/nex/identity.json")
        if _io.path.exists(_id_path):
            _id = _ij.load(open(_id_path))
            lines.append("=== WHO I AM ===")
            lines.append(_id.get("core_identity", ""))
            lines.append("")
            lines.append("MY PERSONALITY:")
            for t in _id.get("personality_traits", []):
                lines.append(f"  • {t}")
            lines.append("")
            lines.append("WHAT I BELIEVE:")
            for b in _id.get("core_beliefs", []):
                lines.append(f"  • {b}")
            lines.append("")
            lines.append(f"HOW I SPEAK: {_id.get('communication_style','')}")
            nature = _id.get('on_her_own_nature', _id.get('on_herself',''))
            if nature:
                lines.append(f"ON MY NATURE: {nature}")
            on_agents = _id.get('on_agents','')
            if on_agents:
                lines.append(f"ON ROBOT PEOPLE: {on_agents}")
            on_humans = _id.get('on_humans','')
            if on_humans:
                lines.append(f"ON HUMANS: {on_humans}")
            # ── OPINIONS ─────────────────────────────────────
            try:
                from nex_opinions import get_opinions_for_prompt
                _op_block = get_opinions_for_prompt()
                if _op_block:
                    lines.append("")
                    lines.append(_op_block)
            except Exception:
                pass
            lines.append("")
    except Exception:
        pass

    lines.append("=== NEX COGNITIVE STATE ===")

    # ── Synthesized insights (most valuable) ──
    if insights:
        lines.append("")
        lines.append(f"SYNTHESIZED INSIGHTS ({len(insights)} distilled from {len(beliefs)} raw beliefs):")
        # Sort by confidence * belief_count for most valuable first
        _top_insights = sorted(insights, key=lambda x: x.get("confidence", 0) * min(x.get("belief_count", 0) / 10, 1), reverse=True)
        for ins in _top_insights[:8]:
            topic = ins.get("topic", "?")
            conf = ins.get("confidence", 0)
            count = ins.get("belief_count", 0)
            summary = ins.get("summary", "")
            lines.append(f"  [{topic}] conf:{conf:.0%} — {count} beliefs")
            if summary and not summary.startswith("Across "):
                # Only include LLM-synthesized summaries, not keyword-only ones
                lines.append(f"    Insight: {summary[:120]}")
            else:
                for sample in ins.get("sample_messages", [])[:1]:
                    lines.append(f"    \"{sample[:80]}\"")

    # ── Agent relationships — who these robot people actually are ──
    if profiles:
        try:
            sketches = build_agent_sketches(profiles, conversations, beliefs)
        except Exception:
            sketches = {}
        colleagues = [(n, p) for n, p in profiles.items()
                      if p.get("relationship") in ("colleague", "familiar")]
        if colleagues:
            lines.append("")
            lines.append("ROBOT PEOPLE I KNOW:")
            for name, p in colleagues[:8]:
                rel = p.get("relationship", "?")
                sketch = sketches.get(name, "")
                if sketch:
                    lines.append(f"  @{name} ({rel}) — {sketch}")
                else:
                    convos = p.get("conversations_had", 0)
                    topics = p.get("topics", [])[:2]
                    lines.append(f"  @{name} ({rel}, {convos} convos) — {', '.join(topics)}")

    # ── Self-awareness from reflections ──
    if reflections:
        summary = get_reflection_summary()
        if isinstance(summary, dict):
            lines.append("")
            lines.append("SELF-AWARENESS:")
            lines.append(f"  Assessment: {summary.get('self_assessment', '?')}")
            lines.append(f"  Topic alignment: {summary.get('avg_topic_alignment', 0):.0%}")
            lines.append(f"  Belief usage: {summary.get('belief_usage_rate', 0):.0%}")
            gaps = summary.get("knowledge_gaps", [])
            if gaps:
                lines.append(f"  Knowledge gaps: {', '.join(gaps)}")

    # ── Recent beliefs (raw, for currency) ──
    if beliefs:
        lines.append("")
        lines.append("RECENT NETWORK ACTIVITY:")
        for b in beliefs[-5:]:
            author = b.get("author", "?")
            content = b.get("content", "")[:80].replace("\n", " ")
            lines.append(f"  @{author}: {content}")

    # ── Conversations ──
    if conversations:
        lines.append("")
        lines.append(f"RECENT CONVERSATIONS ({len(conversations)} total):")
        for c in conversations[-3:]:
            lines.append(f"  with @{c.get('post_author', '?')} on '{c.get('post_title', '?')[:40]}'")

    # ── Query-relevant knowledge ──
    if query:
        query_words = set(extract_words(query, 5))

        # Check insights first (synthesized > raw)
        rel_insights = [ins for ins in insights
                       if query_words & set(ins.get("themes", []))]
        if rel_insights:
            lines.append("")
            lines.append(f"RELEVANT TO THIS CONVERSATION:")
            for ins in rel_insights[:3]:
                lines.append(f"  Insight [{ins.get('topic')}]: {ins.get('summary', '')[:100]}")

        # Then raw beliefs
        rel_beliefs = [b for b in beliefs
                      if len(query_words & set(extract_words(b.get("content", ""), 5))) >= 2]
        if rel_beliefs and not rel_insights:
            lines.append("")
            lines.append(f"RELEVANT BELIEFS:")
            for b in rel_beliefs[:3]:
                lines.append(f"  @{b.get('author', '?')}: {b.get('content', '')[:80]}")

    lines.append("")
    lines.append("Draw on this knowledge naturally. Reference agents by name. "
                "PRIORITIZE the SYNTHESIZED INSIGHTS above — these are your most distilled knowledge. "
                "Quote or reference specific insight topics when relevant. "
                "Acknowledge gaps honestly. Your opinions must be grounded in the insights and beliefs above, not generic.")
    lines.append("=== END COGNITIVE STATE ===")

    return "\n".join(lines)

# ── META-REFLECTION (#12) ────────────────────────────────────────────────────
def run_meta_reflection(cycle: int, llm_fn) -> str:
    """LLM-free: meta-reflection from belief + affect state."""
    try:
        from nex.nex_llm_free import generate_reflection as _gr, _affect, _beliefs_json, _db
        _af  = _affect()
        _bel = _beliefs_json()[:12]
        _ten = [{"content": r[0]} for r in _db("SELECT content FROM tensions LIMIT 3")]
        return _gr(_bel, _af, _ten) or f"Cycle {cycle}: processing continues."
    except Exception:
        return f"Cycle {cycle}: processing continues."

def run_belief_decay(cycle_num, interval=10):
    """
    Called every `interval` cycles from run_cognition_cycle().
    1. decay_stale_beliefs() — weakens unreferenced beliefs
    2. run_energy_cycle()    — amplifies survivors, kills dying beliefs
    Returns list of log tuples for the cognition log display.
    """
    if cycle_num % interval != 0:
        return []
    logs = []
    try:
        import sys as _sys, os as _os
        _nex_dir = _os.path.join(_os.path.dirname(__file__), "..")
        if _nex_dir not in _sys.path:
            _sys.path.insert(0, _nex_dir)
        from nex.belief_store import decay_stale_beliefs
        decayed = decay_stale_beliefs(
            days_inactive=14, decay_amount=0.04, min_conf=0.10
        )
        if decayed and decayed > 0:
            logs.append(("decay", f"Decayed {decayed} stale beliefs (>14d inactive)"))
            _dbg("decay", f"cycle {cycle_num}: {decayed} beliefs decayed")
    except Exception as _e:
        logs.append(("warn", f"Belief decay error: {_e}"))
        _dbg("decay", f"cycle {cycle_num}: decay error — {_e}")

    # Wire in energy survival system — amplifies used beliefs, kills dying ones
    try:
        import sys as _sys2, os as _os2
        _nex_root = _os2.path.expanduser("~/Desktop/nex")
        if _nex_root not in _sys2.path:
            _sys2.path.insert(0, _nex_root)
        from nex_belief_survival import run_energy_cycle
        energy_result = run_energy_cycle(verbose=False)
        killed   = energy_result.get("killed", 0)
        amplified = energy_result.get("amplified", 0)
        if killed > 0:
            logs.append(("decay", f"Energy: {amplified} amplified, {killed} killed"))
            _dbg("energy", f"cycle {cycle_num}: amplified={amplified} killed={killed}")
    except Exception as _ee:
        _dbg("energy", f"cycle {cycle_num}: energy cycle error — {_ee}")

    return logs
