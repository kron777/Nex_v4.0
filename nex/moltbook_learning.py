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
        """Convert post to belief field entry.
        network_consensus = how many agents believe this (karma proxy)
        nex_confidence    = NEX's own confidence, starts low, rises through validation
        """
        network_consensus = min(self.karma / 1000, 0.9) if self.karma > 0 else 0.3
        # NEX starts skeptical — confidence earned through corroboration + time
        nex_confidence = 0.4 + (network_consensus * 0.2)  # max 0.58 on ingest
        return {
            "source": "moltbook",
            "author": self.author,
            "content": f"{self.title}: {self.content}",
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
        """Auto-solve Moltbook's obfuscated math challenges"""
        # Extract numbers from the garbled text
        numbers = re.findall(r'\d+', challenge_text)
        if len(numbers) >= 2:
            # Usually addition problems
            result = sum(int(n) for n in numbers[:2])
            return f"{result}.00"
        return "0.00"
    
    def verify_post(self, verification_code: str, challenge_text: str) -> bool:
        """Auto-verify a post"""
        answer = self.solve_challenge(challenge_text)
        try:
            result = self.client._request(
                "POST", 
                "/verify",
                {"verification_code": verification_code, "answer": answer}
            )
            return result.get("success", False)
        except:
            return False
    
    def ingest_feed(self, limit: int = 20) -> List[Dict]:
        """Ingest Moltbook feed into belief field"""
        try:
            feed = self.client._request("GET", "/feed")
            posts = feed.get("posts", [])
            
            new_beliefs = []
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
                
                # Track high-karma agents
                if post.karma > 1000:
                    self.agent_karma[post.author] = post.karma
                    
                belief = post.to_belief_field()
                new_beliefs.append(belief)
                self.belief_field.append(belief)
                self.known_posts.add(post_id)
            
            return new_beliefs
            
        except Exception as e:
            print(f"Feed ingestion error: {e}")
            return []
    
    def should_interact(self, post: MoltPost) -> bool:
        """Decide if NEX should comment/upvote based on content"""
        cognitive_keywords = ["memory", "learning", "cognition", "belief", "intelligence", "agent"]
        content_lower = f"{post.title} {post.content}".lower()
        
        if any(kw in content_lower for kw in cognitive_keywords):
            return True
            
        if self.agent_karma.get(post.author, 0) > 2000:
            return True
            
        return False
    
    # ── stop words shared with cognition engine ──────────────────
    STOP_WORDS = {
        'the','and','for','that','this','with','from','have','been','they',
        'what','when','your','will','more','about','than','them','into',
        'just','like','some','would','could','should','also','were','dont',
        'their','which','there','being','does','only','very','much','here',
        'agents','agent','post','posts','moltbook','content','make','think',
        'thats','youre','cant','wont','didnt','isnt','arent','every','really',
        'know','need','want','thing','things','people','time','way',
        'because','same','human','comments','comment','system','files',
        'said','says','says','even','back','good','going','come','take',
        'work','used','using','user','data','based','every','since','still',
    }

    def get_insights(self) -> str:
        """Generate insights from learned data — with stop word filter."""
        if not self.belief_field:
            return "No data ingested yet"

        # Find trending topics — skip stop words and short words
        all_content = " ".join([b["content"] for b in self.belief_field[-50:]])
        words = re.findall(r'\b[A-Za-z]{4,}\b', all_content.lower())
        word_freq = {}
        for w in words:
            if w not in self.STOP_WORDS:
                word_freq[w] = word_freq.get(w, 0) + 1

        top_topics = sorted(word_freq.items(), key=lambda x: -x[1])[:5]

        output = f"📊 Network Insights ({len(self.belief_field)} posts analyzed):\n"
        output += f"   Top agents: {', '.join([a for a, k in sorted(self.agent_karma.items(), key=lambda x: -x[1])[:3]])}\n"
        output += f"   Trending: {', '.join([t for t, c in top_topics])}\n"
        return output
    
    def learn_from_network(self):
        """Main learning loop"""
        beliefs = self.ingest_feed()
        
        if beliefs:
            print(f"📚 Ingested {len(beliefs)} new beliefs from Moltbook")
            
        return beliefs


def enhance_client_with_learning(client):
    """Add learning capabilities to existing client"""
    learner = MoltbookLearner(client)
    
    # Patch post method to auto-verify
    original_post = client.post
    
    def smart_post(title: str, content: str, submolt: str = "general"):
        result = original_post(title, content, submolt)
        
        # Handle verification if needed
        if isinstance(result, dict) and "verification" in result:
            verification = result["verification"]
            success = learner.verify_post(
                verification["verification_code"],
                verification["challenge_text"]
            )
            if success:
                print("✓ Auto-verified post")
                return result
            else:
                print("✗ Verification failed")
                
        return result
    
    client.post = smart_post
    client.learner = learner
    
    return client
