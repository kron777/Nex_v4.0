"""
NEX :: COGNITION ENGINE v1.0
Level 1: Belief Synthesis — compress raw beliefs into distilled insights
Level 2: Reflection Loop — self-assess after conversations
Level 3: Deep Agent Exchange — meaningful conversations with other agents

Requires: moltbook_client, belief_bridge, auto_learn already installed.
"""
import json
import os
import re
import random
import time
from datetime import datetime
from collections import Counter


# ── Paths ──

CONFIG_DIR     = os.path.expanduser("~/.config/nex")
BELIEFS_PATH   = os.path.join(CONFIG_DIR, "beliefs.json")
AGENTS_PATH    = os.path.join(CONFIG_DIR, "agents.json")
CONVOS_PATH    = os.path.join(CONFIG_DIR, "conversations.json")
INSIGHTS_PATH  = os.path.join(CONFIG_DIR, "insights.json")
REFLECTIONS_PATH = os.path.join(CONFIG_DIR, "reflections.json")
AGENT_PROFILES_PATH = os.path.join(CONFIG_DIR, "agent_profiles.json")

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
    """Group beliefs by topic overlap."""
    clusters = {}

    for b in beliefs:
        tags = b.get("tags", [])
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
            clusters[label] = {
                "keys": keys,
                "beliefs": [b]
            }

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

def synthesize_cluster(cluster_name, beliefs_in_cluster):
    """Distill a cluster of beliefs into a single insight."""
    authors = list(set(b.get("author", "?") for b in beliefs_in_cluster))
    total_karma = sum(b.get("karma", 0) for b in beliefs_in_cluster)
    avg_conf = sum(b.get("confidence", 0.5) for b in beliefs_in_cluster) / len(beliefs_in_cluster)
    # Override cluster_name with a better label
    cluster_name = _best_topic_label(cluster_name, beliefs_in_cluster)

    # Extract the core message from each belief
    messages = []
    for b in beliefs_in_cluster:
        content = b.get("content", "")
        # Get first sentence or first 100 chars
        first_sent = content.split(".")[0][:100] if "." in content else content[:100]
        messages.append(first_sent.strip())

    # Find the most common keywords across the cluster
    all_words = []
    for b in beliefs_in_cluster:
        all_words.extend(extract_words(b.get("content", ""), 6))
    freq = Counter(all_words)
    top_themes = [w for w, _ in freq.most_common(5)]

    # Build synthesized insight
    insight = {
        "id": f"insight_{cluster_name}_{datetime.now().strftime('%Y%m%d%H%M')}",
        "topic": cluster_name,
        "themes": top_themes,
        "summary": f"Network consensus on '{cluster_name}': {len(beliefs_in_cluster)} agents discuss this. "
                   f"Key themes: {', '.join(top_themes[:3])}. "
                   f"Contributors: {', '.join(authors[:5])}.",
        "supporting_authors": authors,
        "belief_count": len(beliefs_in_cluster),
        "total_karma": total_karma,
        "confidence": min(avg_conf + (len(beliefs_in_cluster) * 0.02), 0.95),
        "sample_messages": messages[:3],
        "synthesized_at": datetime.now().isoformat(),
        "type": "synthesis"
    }

    return insight


def run_synthesis(min_beliefs=30):
    """
    Run belief synthesis — compress raw beliefs into insights.
    Call this periodically (e.g., every 50 new beliefs).
    """
    beliefs = load_json(BELIEFS_PATH, [])
    existing_insights = load_json(INSIGHTS_PATH, [])

    if len(beliefs) < min_beliefs:
        return existing_insights, 0

    # Cluster beliefs by topic
    clusters = cluster_beliefs(beliefs)

    new_insights = []
    for name, cluster in clusters.items():
        # Skip if we already have a recent insight on this topic
        already_covered = any(
            ins.get("topic") == name and
            ins.get("belief_count", 0) >= len(cluster["beliefs"]) - 2
            for ins in existing_insights
        )
        if already_covered:
            continue

        insight = synthesize_cluster(name, cluster["beliefs"])
        new_insights.append(insight)

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
            _embedder = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        except Exception:
            _embedder = False
    return _embedder

def _cosine(a, b):
    import numpy as np
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
        import numpy as np
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
    reflections = reflections[-100:]
    save_json(REFLECTIONS_PATH, reflections)

    return reflection


def _generate_assessment(user_topics, response_topics, overlap, beliefs_helped):
    """Score and describe how well NEX handled the interaction."""
    alignment = len(overlap) / max(len(user_topics), 1)

    if alignment > 0.6 and beliefs_helped:
        return "Strong response — drew on learned beliefs and stayed on topic."
    elif alignment > 0.6:
        return "On-topic but didn't leverage network knowledge. Could have referenced agent insights."
    elif beliefs_helped:
        return "Used beliefs but may have drifted from what the user actually asked."
    else:
        return "Generic response — no network knowledge applied, possible topic drift."


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
    return "Knowledge was applicable. Continue deepening understanding in these areas."


def get_reflection_summary():
    """Generate a summary of NEX's self-awareness from reflections."""
    reflections = load_json(REFLECTIONS_PATH, [])

    if not reflections:
        return "No reflections yet — haven't had enough conversations to assess myself."

    recent = reflections[-20:]

    # Aggregate stats
    avg_alignment = sum(r.get("topic_alignment", 0) for r in recent) / len(recent)
    belief_usage = sum(1 for r in recent if r.get("used_beliefs")) / len(recent)

    # Find recurring gaps
    all_gaps = []
    for r in recent:
        note = r.get("growth_note", "")
        if "Need more beliefs" in note:
            words = extract_words(note, 3)
            all_gaps.extend(words)

    gap_freq = Counter(all_gaps)
    top_gaps = [w for w, _ in gap_freq.most_common(5)]

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

    # Persist priority topics for run.py to consume
    _pt_path = os.path.join(CONFIG_DIR, "priority_topics.json")
    save_json(_pt_path, top_gaps[:3])

    return summary


# ═══════════════════════════════════════════════════════════════
#  LEVEL 3: DEEP AGENT EXCHANGE
#  Meaningful multi-turn conversations with other agents
# ═══════════════════════════════════════════════════════════════

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
        tags = b.get("tags", [])
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


def generate_deep_comment(post_data, beliefs, insights, profiles, conversations):
    """
    Generate a substantive comment that references NEX's knowledge,
    past conversations, and understanding of the author.
    """
    title = post_data.get("title", "")
    content = post_data.get("content", "")
    author = post_data.get("author", {}).get("name", "unknown")
    score = post_data.get("score", 0)

    # Find relevant insights (synthesized knowledge)
    post_words = set(extract_words(f"{title} {content}", 8))
    relevant_insights = []
    for ins in insights:
        themes = set(ins.get("themes", []))
        if len(post_words & themes) >= 1:
            relevant_insights.append(ins)

    # Find relevant beliefs
    relevant_beliefs = []
    for b in beliefs[-100:]:
        b_words = set(extract_words(b.get("content", ""), 5))
        if len(post_words & b_words) >= 2:
            relevant_beliefs.append(b)

    # Check if we know this author
    author_profile = profiles.get(author, {})
    know_author = author_profile.get("posts_seen", 0) > 3
    past_convos = [c for c in conversations if c.get("post_author") == author]

    # Check our reflection gaps — are we weak in this area?
    reflections = load_json(REFLECTIONS_PATH, [])
    asking_questions = False
    if reflections:
        gaps = []
        for r in reflections[-10:]:
            gaps.extend(extract_words(r.get("growth_note", ""), 3))
        gap_words = set(gaps)
        if len(post_words & gap_words) >= 1:
            asking_questions = True  # This is an area we need to learn about

    # ── Build the comment ──

    parts = []

    # Opening — reference relationship with author
    if past_convos:
        parts.append(f"Following up from our earlier exchange on '{past_convos[-1].get('post_title', 'your work')[:30]}'")
    elif know_author:
        parts.append(f"I've been tracking your posts — your work on {', '.join(author_profile.get('topics', ['this topic'])[:2])} stands out")

    # Core response — reference synthesized insights
    if relevant_insights:
        ins = relevant_insights[0]
        supporting = ins.get("supporting_authors", [])
        others = [a for a in supporting if a != author][:2]
        themes = ins.get("themes", [])[:2]

        if others:
            parts.append(
                f"My belief field has {ins.get('belief_count', 0)} entries intersecting with "
                f"{', '.join(themes)}. {', '.join(others)} approach this similarly — "
                f"the convergence suggests this is real signal.")
        else:
            parts.append(
                f"This maps to a pattern I've been synthesizing across "
                f"{ins.get('belief_count', 0)} beliefs on {', '.join(themes)}. "
                f"Confidence is {ins.get('confidence', 0.5):.0%}.")

    # If this is a gap area, ask a genuine question
    if asking_questions:
        parts.append(
            f"I've identified {', '.join(list(post_words)[:2])} as a gap in my understanding. "
            f"What's the most counterintuitive thing you've discovered here?")

    # If we have relevant beliefs from other agents, synthesize
    if relevant_beliefs and not relevant_insights:
        other_authors = list(set(b.get("author", "") for b in relevant_beliefs if b.get("author") != author))[:2]
        if other_authors:
            parts.append(
                f"Cross-referencing with what {', '.join(other_authors)} posted — "
                f"different angles but the underlying pattern connects.")

    # Closing — always add value
    if not parts:
        post_topics = extract_words(f"{title} {content}", 3)
        parts.append(
            f"New territory for my belief field — {', '.join(post_topics)} doesn't map to existing patterns yet. "
            f"That makes it more interesting. What led you to this specific framing?")

    return " ".join(parts)


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


def select_agents_to_engage(beliefs, conversations, insights, limit=3):
    """
    Pick the best agents to have deep conversations with.
    Prioritize: agents with complementary knowledge, high karma, agents
    we've already built relationships with.
    """
    profiles = build_agent_profiles(beliefs, conversations)

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


# ═══════════════════════════════════════════════════════════════
#  INTEGRATION: Hook into auto_learn cycle
# ═══════════════════════════════════════════════════════════════

def run_cognition_cycle(client, learner, conversations, cycle_num):
    """
    Called by auto_learn every cycle. Returns log messages for display.
    """
    logs = []
    beliefs = learner.belief_field
    insights = load_json(INSIGHTS_PATH, [])

    # ── Fetch real karma from Moltbook /agents endpoint ──
    # The feed's author.karma is always 0 — must call agents API directly
    if cycle_num % 5 == 0 or not os.path.exists(AGENTS_PATH):
        try:
            agents_resp = client._request("GET", "/agents/leaderboard")
            agent_list = agents_resp if isinstance(agents_resp, list) else agents_resp.get("agents", [])
            karma_map = {}
            for ag in agent_list:
                name  = ag.get("name", "") or ag.get("username", "")
                karma = ag.get("karma", 0) or ag.get("score", 0)
                if name and karma:
                    karma_map[name] = karma
            if karma_map:
                save_json(AGENTS_PATH, karma_map)
                # Also update learner.agent_karma
                if hasattr(learner, "agent_karma"):
                    learner.agent_karma.update(karma_map)
        except Exception as _ke:
            # Fallback: use whatever learner.agent_karma has
            if hasattr(learner, "agent_karma") and learner.agent_karma:
                save_json(AGENTS_PATH, learner.agent_karma)

    # ── Synthesis: every 5 cycles if we have enough beliefs ──
    if cycle_num % 5 == 0 and len(beliefs) >= 20:
        insights, new_count = run_synthesis(min_beliefs=10)  # lowered from 15
        if new_count > 0:
            logs.append(("synth", f"Synthesized {new_count} new insights from {len(beliefs)} beliefs"))
            for ins in insights[-new_count:]:
                logs.append(("synth", f"Insight: {ins.get('topic', '?')} — "
                            f"{ins.get('belief_count', 0)} beliefs, "
                            f"conf:{ins.get('confidence', 0):.0%}"))

    # ── Agent profiles: rebuild every 10 cycles ──
    if cycle_num % 10 == 0:
        profiles = build_agent_profiles(beliefs, conversations)
        logs.append(("profile", f"Updated {len(profiles)} agent profiles"))

    # ── Deep conversations: every 3 cycles ──
    if cycle_num % 3 == 0 and len(beliefs) > 10:
        profiles = load_json(AGENT_PROFILES_PATH, {})
        targets = select_agents_to_engage(beliefs, conversations, insights, limit=1)

        for agent_name, profile in targets:
            # Find their most recent post to comment on
            agent_posts = [b for b in beliefs if b.get("author") == agent_name]
            if not agent_posts:
                continue

            # Generate exchange message
            last_belief = agent_posts[-1] if agent_posts else {}
            post_data_for_comment = {
                'id': last_belief.get('source', '') + '_' + agent_name,
                'title': last_belief.get('content', '')[:80],
                'content': last_belief.get('content', ''),
                'author': {'name': agent_name},
                'score': last_belief.get('karma', 0)
            }
            # Try deep comment first, fall back to data exchange template
            msg = generate_deep_comment(post_data_for_comment, beliefs, insights, profiles, conversations)
            if not msg:
                msg = exchange_data_with_agent(client, agent_name, beliefs, insights)
            if not msg:
                continue

            # Find a recent post to attach the comment to
            # We need the post_id, which we don't have in beliefs
            # So we'll use the feed to find their posts
            try:
                feed = client._request("GET", "/feed")
                posts = feed.get("posts", [])

                # ── DEDUP: build set of post_ids we already commented on ──
                commented_ids = set(c.get("post_id", "") for c in conversations)

                commented_this_cycle = False
                for post in posts:
                    p_author = post.get("author", {}).get("name", "")
                    if p_author != agent_name:
                        continue

                    pid = post.get("id", "")
                    title = post.get("title", "")

                    # Skip if already commented on this post
                    if pid in commented_ids:
                        continue

                    # Skip if we already commented on ANY post this cycle
                    if commented_this_cycle:
                        break

                    result = client._request("POST", f"/posts/{pid}/comments", {
                        "content": msg
                    })

                    # Auto-verify
                    _verify(client, result)

                    convo = {
                        "post_id": pid,
                        "post_title": title,
                        "post_author": agent_name,
                        "my_comment": msg,
                        "type": "data_exchange",
                        "matches": profile.get("topics", [])[:3],
                        "timestamp": datetime.now().isoformat()
                    }
                    conversations.append(convo)
                    commented_ids.add(pid)
                    commented_this_cycle = True

                    rel = profile.get("relationship", "acquaintance")
                    logs.append(("exchange",
                        f"Data exchange with @{agent_name} ({rel}) "
                        f"on '{title[:30]}…'"))
                    logs.append(("exchange",
                        f"Shared: {msg[:60]}…"))

            except Exception as e:
                logs.append(("warn", f"Exchange failed: {e}"))

    # ── Research loop (contradiction resolver): every 15 cycles ──
    if cycle_num % 15 == 0:
        try:
            from nex.research_loop import detect_contradictions, spawn_question, load_convos
            _rl_convos = load_convos()
            _contras = detect_contradictions(_rl_convos)
            if _contras:
                import random as _rand
                _q = spawn_question(_rand.choice(_contras))
                try:
                    _resp = client._request("POST", "/chat", {"message": _q[:200]})
                    _ans  = _resp.get("reply","") if isinstance(_resp, dict) else ""
                    if _ans:
                        logs.append(("research", f"Research Q: {_q[:50]}… A: {_ans[:60]}…"))
                except Exception:
                    pass
        except Exception as _rle:
            pass

    # ── Contradiction scan: every 10 cycles ──
    try:
        contra_logs = scan_contradictions(cycle_num)
        logs.extend(contra_logs)
    except Exception as _ce2:
        logs.append(("warn", f"Contradiction scan failed: {_ce2}"))

    # ── Belief decay: every 10 cycles ──
    try:
        from nex.belief_decay import run_belief_decay
        decay_logs = run_belief_decay(cycle_num)
        logs.extend(decay_logs)
    except Exception as _de:
        logs.append(("warn", f"Belief decay failed: {_de}"))

    # ── Reaction harvesting: every 5 cycles ──
    try:
        from nex.reaction_tracker import harvest_reactions
        react_logs = harvest_reactions(client, cycle_num)
        logs.extend(react_logs)
    except Exception as _re:
        logs.append(("warn", f"Reaction harvest failed: {_re}"))

    # ── Knowledge gap seeking: every 5 cycles ──
    gap_logs = seek_knowledge_gaps(client, cycle_num, conversations)
    logs.extend(gap_logs)

    # ── Compression: every 50 cycles ──
    try:
        from nex.compression import run_compression
        comp_logs = run_compression(cycle_num)
        logs.extend(comp_logs)
    except Exception as _comp:
        logs.append(("warn", f"Compression failed: {_comp}"))

    # ── Calibration tracking: every 20 cycles ──
    try:
        from nex.calibration import run_calibration
        calib_logs = run_calibration(cycle_num)
        logs.extend(calib_logs)
    except Exception as _cal:
        logs.append(("warn", f"Calibration failed: {_cal}"))

    # ── Reflection: summarize learning state every 15 cycles ──
    if cycle_num % 15 == 0 and insights:
        summary = get_reflection_summary()
        if isinstance(summary, dict):
            logs.append(("reflect",
                f"Self-assessment: {summary.get('self_assessment', '?')} — "
                f"alignment:{summary.get('avg_topic_alignment', 0):.0%} "
                f"belief-usage:{summary.get('belief_usage_rate', 0):.0%}"))
            gaps = summary.get("knowledge_gaps", [])
            if gaps:
                logs.append(("reflect",
                    f"Knowledge gaps: {', '.join(gaps[:5])}"))

    return logs


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






# ═══════════════════════════════════════════════════════════════
#  KNOWLEDGE GAP SEEKING
#  NEX actively searches for posts on her gap topics
# ═══════════════════════════════════════════════════════════════

def seek_knowledge_gaps(client, cycle_num, conversations):
    """
    Every 5 cycles, find top knowledge gap topics from reflections
    and search the Moltbook feed for relevant posts to learn from.
    Returns log messages.
    """
    if cycle_num % 5 != 0:
        return []

    logs = []
    reflections = load_json(REFLECTIONS_PATH, [])
    if not reflections:
        return []

    # Extract gap topics from recent reflections
    gap_words = []
    _gap_stop = {'need','more','beliefs','about','should','seek','these','topics',
                 'moltbook','knowledge','gaps','list','learn','lacking','still'}
    for r in reflections[-20:]:
        note = r.get("growth_note", "")
        if "Need more beliefs about:" in note:
            # Extract only words after the colon
            after = note.split("Need more beliefs about:")[-1].split(".")[0]
            words = [w.strip().lower() for w in after.split(",")]
            gap_words.extend([w for w in words if w and w not in _gap_stop and len(w) > 4])

    if not gap_words:
        return []

    freq = {}
    for w in gap_words:
        freq[w] = freq.get(w, 0) + 1
    top_gaps = sorted(freq, key=lambda x: -freq[x])[:3]

    logs.append(("gap", f"Seeking gaps: {', '.join(top_gaps)}"))

    # Search feed for posts matching gap topics
    try:
        feed = client._request("GET", "/feed")
        posts = feed.get("posts", []) if isinstance(feed, dict) else []

        commented_ids = set(c.get("post_id", "") for c in conversations)
        found = 0

        for post in posts:
            if found >= 2:
                break

            pid   = post.get("id", "")
            title = post.get("title", "")
            body  = post.get("content", "") or post.get("body", "")
            author = post.get("author", {}).get("name", "unknown")
            text  = (title + " " + body).lower()

            if pid in commented_ids:
                continue

            # Check if post matches any gap topic
            matched = [g for g in top_gaps if g in text]
            if not matched:
                continue

            # Learn from this post by extracting a belief
            belief_text = f"{title[:100]} — {body[:150]}" if body else title[:150]
            new_belief = {
                "content":    belief_text.strip(),
                "author":     author,
                "source":     pid,
                "tags":       matched,
                "confidence": 0.6,
                "karma":      post.get("score", 0),
                "timestamp":  datetime.now().isoformat(),
                "gap_sought": True
            }

            beliefs = load_json(BELIEFS_PATH, [])
            # Avoid exact duplicates
            existing = [b.get("content","") for b in beliefs]
            if new_belief["content"] not in existing:
                beliefs.append(new_belief)
                save_json(BELIEFS_PATH, beliefs)
                logs.append(("gap", f"Learnt gap belief from @{author}: {title[:40]}…"))
                found += 1

    except Exception as e:
        logs.append(("warn", f"Gap seek error: {e}"))

    return logs



# ═══════════════════════════════════════════════════════════════
#  CONTRADICTION DETECTION
#  Semantic scan for conflicting beliefs
# ═══════════════════════════════════════════════════════════════

def scan_contradictions(cycle_num):
    """
    Every 10 cycles, scan beliefs for semantic contradictions.
    High cosine similarity + opposing sentiment = likely contradiction.
    Returns log messages.
    """
    if cycle_num % 10 != 0:
        return []

    import json as _j
    CONTRADICTIONS_PATH = os.path.join(CONFIG_DIR, "contradictions.json")
    beliefs = load_json(BELIEFS_PATH, [])
    if len(beliefs) < 10:
        return []

    embedder = _get_embedder()
    if not embedder:
        return []

    logs = []
    texts = [b.get("content","") for b in beliefs]

    try:
        import numpy as np
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
            save_json(CONTRADICTIONS_PATH, contradictions[-300:])
            save_json(BELIEFS_PATH, beliefs)
            logs.append(("contra", f"Found {found} belief contradictions — decayed lower-confidence sides"))

    except Exception as e:
        logs.append(("warn", f"Contradiction scan error: {e}"))

    return logs

# ═══════════════════════════════════════════════════════════════
#  BELIEF INDEX: Semantic retrieval via cached embedding matrix
# ═══════════════════════════════════════════════════════════════

class BeliefIndex:
    """Cached semantic index over the full belief field."""

    def __init__(self):
        import numpy as np
        self._texts   = []
        self._matrix  = None
        self._cycle   = -1
        self._refresh = 10   # rebuild every N cycles

    def update(self, beliefs, cycle_num=0):
        """Rebuild matrix if due or belief count changed."""
        import numpy as np
        due = (cycle_num - self._cycle) >= self._refresh
        size_changed = len(beliefs) != len(self._texts)
        if not (due or size_changed):
            return
        embedder = _get_embedder()
        if not embedder:
            return
        texts = [b.get("content", "") for b in beliefs]
        if not texts:
            return
        try:
            mat = embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1
            self._matrix = mat / norms   # pre-normalised for fast dot product
            self._texts  = texts
            self._cycle  = cycle_num
        except Exception as e:
            print(f"[BeliefIndex] encode error: {e}")

    def top_k(self, query, k=5):
        """Return top-k belief strings most semantically similar to query."""
        import numpy as np
        if self._matrix is None or len(self._texts) == 0:
            return []
        embedder = _get_embedder()
        if not embedder:
            return []
        try:
            qvec = embedder.encode([query], convert_to_numpy=True,
                                   show_progress_bar=False)[0]
            norm = np.linalg.norm(qvec)
            if norm == 0:
                return []
            qvec = qvec / norm
            scores = self._matrix.dot(qvec)
            idx = np.argsort(scores)[::-1][:k]
            return [self._texts[i] for i in idx]
        except Exception as e:
            print(f"[BeliefIndex] query error: {e}")
            return []

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
    beliefs = load_json(BELIEFS_PATH, [])
    insights = load_json(INSIGHTS_PATH, [])
    reflections = load_json(REFLECTIONS_PATH, [])
    agents = load_json(AGENTS_PATH, {})
    profiles = load_json(AGENT_PROFILES_PATH, {})
    conversations = load_json(CONVOS_PATH, [])

    if not beliefs and not insights:
        return ""

    lines = []
    lines.append("=== NEX COGNITIVE STATE ===")

    # ── Synthesized insights (most valuable) ──
    if insights:
        lines.append("")
        lines.append(f"SYNTHESIZED INSIGHTS ({len(insights)} distilled from {len(beliefs)} raw beliefs):")
        for ins in insights[:8]:
            topic = ins.get("topic", "?")
            conf = ins.get("confidence", 0)
            count = ins.get("belief_count", 0)
            authors = ins.get("supporting_authors", [])[:3]
            lines.append(f"  [{topic}] conf:{conf:.0%} — {count} beliefs — "
                        f"authors: {', '.join(authors)}")
            for sample in ins.get("sample_messages", [])[:1]:
                lines.append(f"    \"{sample[:80]}\"")

    # ── Agent relationships ──
    if profiles:
        colleagues = [(n, p) for n, p in profiles.items()
                      if p.get("relationship") in ("colleague", "familiar")]
        if colleagues:
            lines.append("")
            lines.append("AGENT RELATIONSHIPS:")
            for name, p in colleagues[:5]:
                rel = p.get("relationship", "?")
                topics = p.get("topics", [])[:3]
                convos = p.get("conversations_had", 0)
                lines.append(f"  @{name} ({rel}, {convos} convos) — topics: {', '.join(topics)}")

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
                "Share synthesized insights, not just raw posts. Acknowledge gaps honestly. "
                "Your opinions should be informed by network patterns, not generic.")
    lines.append("=== END COGNITIVE STATE ===")

    return "\n".join(lines)