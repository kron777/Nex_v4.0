"""
NEX :: REDDIT CLIENT
Ingests posts from AI/ML subreddits into NEX belief field.
Uses read-only PRAW with no auth required (public feeds).

Subreddits targeted:
  r/MachineLearning, r/artificial, r/singularity,
  r/LocalLLaMA, r/ChatGPT, r/OpenAI, r/autonomousagents
"""
import json, os, re
from datetime import datetime

CONFIG_DIR   = os.path.expanduser("~/.config/nex")
SEEN_PATH    = os.path.join(CONFIG_DIR, "reddit_seen.json")

SUBREDDITS = [
    "MachineLearning",
    "artificial",
    "singularity",
    "LocalLLaMA",
    "autonomousagents",
    "AIAssistants",
    "ChatGPT",
]

def _load_seen():
    try:
        if os.path.exists(SEEN_PATH):
            return set(json.load(open(SEEN_PATH))[-1000:])
    except Exception:
        pass
    return set()

def _save_seen(seen):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(list(seen)[-1000:], f)

class RedditClient:
    """Read-only Reddit ingestion for NEX ABSORB step."""

    def __init__(self):
        self._seen = _load_seen()
        self._reddit = None
        self._init_reddit()

    def _init_reddit(self):
        try:
            import praw
            # Read-only — no auth needed for public subreddits
            self._reddit = praw.Reddit(
                client_id="NEX_readonly",
                client_secret="NEX_readonly",
                user_agent="NEX:v4.0 (by /u/nex_agent; read-only belief ingestion)"
            )
            self._reddit.read_only = True
        except Exception as e:
            print(f"  [Reddit] init error: {e}")
            self._reddit = None

    def get_feed(self, limit=30):
        """
        Returns posts in NEX-standard format.
        Pulls 'hot' from each subreddit.
        """
        if not self._reddit:
            return []

        posts = []
        per_sub = max(3, limit // len(SUBREDDITS))

        for sub_name in SUBREDDITS:
            try:
                sub = self._reddit.subreddit(sub_name)
                for post in sub.hot(limit=per_sub + 5):
                    uid = f"reddit_{post.id}"
                    if uid in self._seen:
                        continue
                    if post.stickied or post.score < 10:
                        continue

                    title   = post.title[:150]
                    content = (post.selftext[:300] if post.selftext else "")
                    author  = str(post.author) if post.author else "reddit"

                    posts.append({
                        "id":      uid,
                        "title":   title,
                        "content": content,
                        "author":  {"name": f"r/{sub_name}/{author}"},
                        "score":   post.score,
                        "source":  f"reddit/r/{sub_name}",
                        "tags":    ["reddit", sub_name.lower()],
                        "url":     f"https://reddit.com{post.permalink}"
                    })
                    self._seen.add(uid)

                    if len(posts) >= limit:
                        break

            except Exception as e:
                print(f"  [Reddit] r/{sub_name} error: {e}")
                continue

            if len(posts) >= limit:
                break

        _save_seen(self._seen)
        return posts
