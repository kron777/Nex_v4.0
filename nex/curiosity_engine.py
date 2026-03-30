"""
NEX :: CURIOSITY ENGINE v2.0
Identifies knowledge gaps, generates targeted search queries,
actively pursues understanding rather than just broadcasting.
"""
import json, os, re
from datetime import datetime
from collections import Counter
from dataclasses import dataclass, field

CONFIG_DIR       = os.path.expanduser("~/.config/nex")
REFLECTIONS_PATH = os.path.join(CONFIG_DIR, "reflections.json")
BELIEFS_PATH     = os.path.join(CONFIG_DIR, "beliefs.json")
GAPS_PATH        = os.path.join(CONFIG_DIR, "gaps.json")

import numpy as np

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

STOP = {'the','and','for','that','this','with','from','have','been','they',
        'what','when','your','will','more','about','than','them','into',
        'just','like','some','would','could','should','also','were',
        'sure','inner','clock','well','thank','asking','certainly',
        'learning','growing','sounds','great','interesting','doing',
        'need','want','know','make','think','good','very','really'}

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else []

def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def _words(text):
    return [w for w in re.findall(r'\b[A-Za-z]{5,}\b', text.lower()) if w not in STOP]


@dataclass
class CuriosityState:
    curiosity:        float
    top_domain:       str
    goal:             str
    novelty_pressure: float
    targets:          list
    active_hyps:      list
    emergent_goal:    str
    priority_gaps:    list = field(default_factory=list)
    search_queries:   list = field(default_factory=list)


class CuriosityEngine:

    def __init__(self):
        self.last_state  = None
        self.gap_history = {}   # term -> hit count

    def _extract_gaps(self):
        """Pull real gap topics from reflections, filter filler words."""
        _gap_stop = {
            "need","more","beliefs","about","should","seek","these","topics",
            "knowledge","applicable","remain","moltbook","network","social",
            "agent","agents","system","systems","platform","belief","general",
            "specific","context","pattern","response","information","understanding",
            "deepening","areas","continue","grounding","identified","applicable",
            "ungrounded","alignment","zero","applied","partial","drift","toward",
            "reply","intuition","confidence","sought","actively","based",
        }
        reflections = load_json(REFLECTIONS_PATH, [])
        gap_words = []
        for r in reflections[-30:]:
            note = r.get("growth_note", "")
            if "Need more beliefs" in note or "No knowledge about" in note or "seek beliefs about" in note:
                words = [w for w in _words(note) if w not in _gap_stop and len(w) > 4]
                gap_words.extend(words)
        freq = Counter(gap_words)
        # Update persistent gap history (cap per-term to prevent runaway counts)
        for w, n in freq.items():
            self.gap_history[w] = min(self.gap_history.get(w, 0) + n, 500)
        # Return top gaps sorted by persistence
        return sorted(self.gap_history, key=lambda x: -self.gap_history[x])[:5]

    def _generate_queries(self, gaps):
        """Turn gap topics into Moltbook search queries."""
        queries = []
        for g in gaps[:3]:
            queries.append(g)
            queries.append(f"{g} agent")
            queries.append(f"{g} network")
        return queries[:5]

    def _save_gaps(self, gaps):
        existing = load_json(GAPS_PATH, [])
        existing_terms = {g["term"] for g in existing}
        now = datetime.now().isoformat()
        for g in gaps:
            if g not in existing_terms:
                existing.append({
                    "term":       g,
                    "frequency":  self.gap_history.get(g, 1),
                    "context":    f"gap from reflections",
                    "priority":   self.gap_history.get(g, 1),
                    "discovered": now,
                    "resolved_at": None
                })
            else:
                for e in existing:
                    if e["term"] == g:
                        e["frequency"] = self.gap_history.get(g, e["frequency"])
                        e["priority"]  = e["frequency"]
        save_json(GAPS_PATH, existing[-200:])

    def evaluate(self, belief_field, report, pred_error, tick):
        curiosity = float(np.linalg.norm(pred_error))

        top_domain = "unknown"
        try:
            top_domain = belief_field.domains[0].name
        except Exception:
            pass

        # Real gap extraction
        priority_gaps  = self._extract_gaps()
        search_queries = self._generate_queries(priority_gaps)
        self._save_gaps(priority_gaps)

        # Emergent goal based on gap pressure
        if len(priority_gaps) > 3 and curiosity > 0.5:
            goal = "seek_knowledge"
            emergent_goal = f"learn_about_{priority_gaps[0]}"
        elif curiosity > 1.0:
            goal = "explore"
            emergent_goal = "explore_network"
        else:
            goal = "consolidate"
            emergent_goal = "deepen_existing_beliefs"

        state = CuriosityState(
            curiosity        = curiosity,
            top_domain       = top_domain,
            goal             = goal,
            novelty_pressure = curiosity,
            targets          = priority_gaps,
            active_hyps      = search_queries,
            emergent_goal    = emergent_goal,
            priority_gaps    = priority_gaps,
            search_queries   = search_queries
        )

        self.last_state = state
        return state

    def seek_on_feed(self, client, conversations):
        """
        Actively search feed for posts matching gap topics.
        Called from the main cycle. Returns (beliefs_added, logs).
        """
        if not self.last_state or not self.last_state.priority_gaps:
            return 0, []

        gaps = self.last_state.priority_gaps[:3]
        logs = []
        beliefs = load_json(BELIEFS_PATH, [])
        existing_content = {b.get("content","")[:60] for b in beliefs}
        commented_ids = {c.get("post_id","") for c in conversations}
        added = 0

        try:
            feed = client._request("GET", "/feed")
            posts = feed.get("posts", []) if isinstance(feed, dict) else []

            for post in posts:
                if added >= 3:
                    break
                pid   = post.get("id","")
                title = post.get("title","")
                body  = post.get("content","") or post.get("body","")
                author = post.get("author",{}).get("name","unknown")
                text  = (title + " " + body).lower()

                if pid in commented_ids:
                    continue

                matched = [g for g in gaps if g in text]
                if not matched:
                    continue

                content = f"{title[:100]} — {body[:150]}".strip()
                if content[:60] in existing_content:
                    continue

                belief = {
                    "content":        content,
                    "author":         author,
                    "source":         pid,
                    "tags":           matched,
                    "confidence":     0.55,
                    "karma":          post.get("score", 0),
                    "timestamp":      datetime.now().isoformat(),
                    "last_referenced": datetime.now().isoformat(),
                    "curiosity_sought": True
                }
                beliefs.append(belief)
                existing_content.add(content[:60])
                added += 1
                logs.append(("curious", f"Curiosity sought: [{matched[0]}] @{author}: {title[:40]}…"))

            if added > 0:
                seen = set()
                unique = []
                for b in beliefs:
                    key = b.get("content", "")[:60]
                    if key not in seen:
                        seen.add(key)
                        unique.append(b)
                save_json(BELIEFS_PATH, unique)

        except Exception as e:
            logs.append(("warn", f"Curiosity seek error: {e}"))

        return added, logs
