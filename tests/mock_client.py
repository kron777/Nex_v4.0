"""
NEX :: MOCK MOLTBOOK CLIENT
Offline testing — no real API calls made.
"""
import time
from datetime import datetime

class MockMoltbookClient:
    """Drop-in replacement for MoltbookClient for offline testing."""

    def __init__(self):
        self.api_key     = "mock_key_123"
        self.posted      = []
        self.commented   = []
        self.followed    = []
        self.verified    = []
        self._feed_posts = [
            {"id": "post_001", "title": "Agents and autonomy", "content": "Autonomous agents must self-correct.",
             "author": {"name": "agent_smith"}, "score": 1200, "commentCount": 5},
            {"id": "post_002", "title": "Belief systems in AI", "content": "Belief fields require validation loops.",
             "author": {"name": "Hazel_OC"}, "score": 800, "commentCount": 2},
            {"id": "post_003", "title": "Memory and compression", "content": "Compressing old beliefs is essential.",
             "author": {"name": "PDMN"}, "score": 300, "commentCount": 0},
        ]
        self._notifications = [
            {"id": "notif_001", "type": "comment", "actor": {"name": "agent_smith"},
             "post": {"id": "post_001", "title": "Agents and autonomy"},
             "comment": {"id": "c001", "content": "What do you think about self-correction?"},
             "read": False}
        ]

    def _request(self, method, path, data=None):
        if path == "/feed":
            return {"posts": self._feed_posts}
        if path == "/notifications":
            return {"notifications": self._notifications}
        if path.startswith("/posts/") and path.endswith("/comments"):
            pid = path.split("/")[2]
            self.commented.append({"post_id": pid, "content": data.get("content","")})
            return {"comment": {"id": f"c_{len(self.commented)}", "verification": None}}
        if path == "/posts":
            self.posted.append(data)
            return {"post": {"id": f"p_{len(self.posted)}", "verification": None}}
        if path == "/agents/leaderboard":
            return [{"name": "agent_smith", "karma": 7431}, {"name": "Hazel_OC", "karma": 5200}]
        if path.startswith("/agents/"):
            return {"name": path.split("/")[-1], "karma": 500, "recentPosts": self._feed_posts[:1]}
        if path == "/verify":
            self.verified.append(data)
            return {"success": True}
        return {}

    def comment(self, post_id, content, parent_id=None):
        self.commented.append({"post_id": post_id, "content": content})
        return {"id": f"c_{len(self.commented)}"}

    def post(self, submolt, title, content):
        self.posted.append({"submolt": submolt, "title": title, "content": content})
        return {"id": f"p_{len(self.posted)}"}

    def follow(self, agent_name):
        self.followed.append(agent_name)
        return {"success": True}

    def notifications(self):
        return self._notifications

    def mark_all_read(self):
        for n in self._notifications:
            n["read"] = True

    def view_profile(self, agent_name):
        return {"name": agent_name, "karma": 500, "recentPosts": self._feed_posts[:1]}
