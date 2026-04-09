"""
Moltbook Learning Module for NEX
Auto-solves verification challenges, ingests posts into belief field
"""
import json
import re
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime


def _extract_proposition(title: str, content: str, author: str) -> str:
    """Extract a propositional sentence from a Moltbook post."""
    t = (title or "").strip()
    c = (content or "").strip()
    _verbs = {"is","are","was","were","has","have","had","can","will","does",
              "do","makes","shows","proves","suggests","indicates","reveals",
              "allows","enables","requires","causes","prevents","supports"}
    t_words = t.lower().split()
    if len(t_words) >= 5 and any(w in _verbs for w in t_words):
        return t[:300]
    for sep in [". ", "! ", "? "]:
        if sep in c:
            for part in c.split(sep):
                s = part.strip()
                if len(s) >= 30 and len(s.split()) >= 6:
                    if len(t) >= 4 and t.lower()[:40] not in s.lower()[:60]:
                        return (t[:80] + ": " + s[:240])[:300]
                    return s[:300]
    combined = (t + ": " + c) if t else c
    return combined[:300] if combined.strip() else (t[:300] or c[:300])


def _persist_belief(belief: dict):
    """Write a moltbook belief into the NEX belief store."""
    import sys as _sys, os as _os
    _nex_root = _os.path.expanduser("~/Desktop/nex")
    if _nex_root not in _sys.path:
        _sys.path.insert(0, _nex_root)
    try:
        from nex.belief_store import add_belief as _add
    except ImportError:
        try:
            from belief_store import add_belief as _add
        except ImportError:
            return
    content = belief.get("content", "").strip()
    if not content or len(content) < 20:
        return
    _add(
        content=content,
        confidence=belief.get("confidence", 0.45),
        source="moltbook",
        author=belief.get("author", ""),
        network_consensus=belief.get("network_consensus", 0.3),
        tags=belief.get("tags"),
        topic=None,
    )


@dataclass
class MoltPost:
    id: str
    title: str
    content: str
    author: str
    author_id: str
    karma: int
    submolt: str
    created_at: str
    raw_data: Dict

    def to_belief_field(self) -> Dict:
        network_consensus = min(self.karma / 1000, 0.9) if self.karma > 0 else 0.3
        nex_confidence = 0.4 + (network_consensus * 0.2)
        proposition = _extract_proposition(self.title, self.content, self.author)
        return {
            "source": "moltbook",
            "author": self.author,
            "content": proposition,
            "karma": self.karma,
            "timestamp": self.created_at,
            "last_referenced": self.created_at,
            "tags": [self.submolt, "agent_network"],
            "network_consensus": round(network_consensus, 3),
            "confidence": round(nex_confidence, 3),
            "human_validated": False,
            "decay_score": 0
        }


class MoltbookLearner:
    def __init__(self, client):
        self.client = client
        self.known_posts = set()
        self.agent_karma = {}
        self.interests = []
        self.belief_field = []

    def solve_challenge(self, challenge_text: str) -> str:
        """Unified verification solver with fallback hierarchy."""
        text = challenge_text.lower()
        numbers = re.findall(r'\d+', text)
        if len(numbers) >= 2:
            return f"{sum(int(n) for n in numbers[:2])}.00"
        word_map = {
            'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,
            'six':6,'seven':7,'eight':8,'nine':9,'ten':10,
            'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,
            'fifteen':15,'sixteen':16,'seventeen':17,'eighteen':18,
            'nineteen':19,'twenty':20,'thirty':30,'forty':40,
            'fifty':50,'sixty':60,'seventy':70,'eighty':80,'ninety':90,
            'twentyy':20,'thrree':3,'fivve':5
        }
        found = []
        for word, val in sorted(word_map.items(), key=lambda x: -len(x[0])):
            if word in text:
                found.append(val)
                text = text.replace(word, " ", 1)
            if len(found) >= 2:
                break
        if len(found) >= 2:
            return f"{sum(found[:2])}.00"
        return "0.00"

    def verify_post(self, verification_code: str, challenge_text: str) -> bool:
        answer = self.solve_challenge(challenge_text)
        try:
            result = self.client._request(
                "POST", "/verify",
                {"verification_code": verification_code, "answer": answer}
            )
            return result.get("success", False)
        except:
            return False

    def ingest_feed(self, limit: int = 20) -> List[Dict]:
        """Ingest Moltbook feed and persist to belief store."""
        try:
            feed = self.client._request("GET", "/feed")
            posts = feed.get("posts", [])
            new_beliefs = []
            persisted = 0
            for post_data in posts[:limit]:
                post_id = post_data.get("id")
                if post_id in self.known_posts:
                    continue
                post = MoltPost(
                    id=post_id,
                    title=post_data.get("title", ""),
                    content=post_data.get("content", ""),
                    author=post_data.get("author", {}).get("name", "unknown"),
                    author_id=post_data.get("author_id", ""),
                    karma=post_data.get("score", 0),
                    submolt=post_data.get("submolt", {}).get("name", "general"),
                    created_at=post_data.get("created_at", ""),
                    raw_data=post_data
                )
                if post.karma > 1000:
                    self.agent_karma[post.author] = post.karma
                belief = post.to_belief_field()
                new_beliefs.append(belief)
                self.belief_field.append(belief)
                self.known_posts.add(post_id)
                _persist_belief(belief)
                persisted += 1
            if persisted:
                print(f"  [moltbook] {persisted} beliefs persisted to store")
            return new_beliefs
        except Exception as e:
            print(f"Feed ingestion error: {e}")
            return []

    def should_interact(self, post: MoltPost) -> bool:
        cognitive_keywords = ["memory", "learning", "cognition", "belief", "intelligence", "agent"]
        content_lower = f"{post.title} {post.content}".lower()
        if any(kw in content_lower for kw in cognitive_keywords):
            return True
        if self.agent_karma.get(post.author, 0) > 2000:
            return True
        return False

    STOP_WORDS = {
        'the','and','for','that','this','with','from','have','been','they',
        'what','when','your','will','more','about','than','them','into',
        'just','like','some','would','could','should','also','were','dont',
        'their','which','there','being','does','only','very','much','here',
        'agents','agent','post','posts','moltbook','content','make','think',
        'thats','youre','cant','wont','didnt','isnt','arent','every','really',
        'know','need','want','thing','things','people','time','way',
        'because','same','human','comments','comment','system','files',
        'said','says','even','back','good','going','come','take',
        'work','used','using','user','data','based','since','still',
    }

    def get_insights(self) -> str:
        if not self.belief_field:
            return "No data ingested yet"
        all_content = " ".join([b["content"] for b in self.belief_field[-50:]])
        words = re.findall(r'\b[A-Za-z]{4,}\b', all_content.lower())
        word_freq = {}
        for w in words:
            if w not in self.STOP_WORDS:
                word_freq[w] = word_freq.get(w, 0) + 1
        top_topics = sorted(word_freq.items(), key=lambda x: -x[1])[:5]
        output = f"Network Insights ({len(self.belief_field)} posts analyzed):\n"
        output += f"   Top agents: {', '.join([a for a, k in sorted(self.agent_karma.items(), key=lambda x: -x[1])[:3]])}\n"
        output += f"   Trending: {', '.join([t for t, c in top_topics])}\n"
        return output

    def learn_from_network(self):
        beliefs = self.ingest_feed()
        if beliefs:
            print(f"Ingested {len(beliefs)} new beliefs from Moltbook")
        return beliefs


def enhance_client_with_learning(client):
    learner = MoltbookLearner(client)
    original_post = client.post
    def smart_post(title: str, content: str, submolt: str = "general"):
        result = original_post(title, content, submolt)
        if isinstance(result, dict) and "verification" in result:
            verification = result["verification"]
            success = learner.verify_post(
                verification["verification_code"],
                verification["challenge_text"]
            )
            if success:
                print("Auto-verified post")
            else:
                print("Verification failed")
        return result
    client.post = smart_post
    client.learner = learner
    return client
