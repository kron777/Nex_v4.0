"""
NEX :: RSS/HACKERNEWS CLIENT
Zero-auth ingestion from HackerNews, ArXiv, and AI blogs.
Returns posts in the same format as MoltbookClient feed.
"""
import json, os, re
import urllib.request
from datetime import datetime

try:
    from nex_signal_filter import get_scorer, get_gate, ImportanceGate
    _rss_scorer = get_scorer()
    _rss_gate   = get_gate()
except Exception:
    _rss_scorer = None
    _rss_gate   = None

# Top feeds for NEX's domain
FEEDS = [
    ("HackerNews AI",    "https://hnrss.org/newest?q=AI+agent+LLM&count=20"),
    ("HackerNews ML",    "https://hnrss.org/newest?q=machine+learning&count=15"),
    ("HackerNews Agents","https://hnrss.org/newest?q=autonomous+agent&count=15"),
    ("ArXiv AI",         "https://export.arxiv.org/rss/cs.AI"),
    ("ArXiv LLM",        "https://export.arxiv.org/rss/cs.CL"),
    ("ArXiv Robots",     "https://export.arxiv.org/rss/cs.RO"),
    ("MIT Tech Review",  "https://www.technologyreview.com/feed/"),
    ("VentureBeat AI",   "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI",     "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("Wired AI",         "https://www.wired.com/feed/tag/ai/latest/rss"),
    ("OpenAI Blog",      "https://openai.com/blog/rss.xml"),
    ("Anthropic Blog",   "https://www.anthropic.com/rss.xml"),
    ("DeepMind Blog",    "https://deepmind.google/blog/rss.xml"),
    ("LessWrong",        "https://www.lesswrong.com/feed.xml?view=community-rss&karmaThreshold=50"),
    ("AI Alignment",     "https://www.alignmentforum.org/feed.xml?view=community-rss&karmaThreshold=30"),
    ("EleutherAI",       "https://blog.eleuther.ai/rss/"),
    ("Distill.pub",      "https://distill.pub/rss.xml"),
]

def _strip_html(text):
    return re.sub(r'<[^>]+>', ' ', text or '').strip()

def _fetch_feed(url, timeout=10):
    """Fetch and parse RSS feed. Returns list of items."""
    try:
        import feedparser
        feed = feedparser.parse(url)
        return feed.entries
    except Exception as e:
        print(f"  [RSS] fetch error {url[:40]}: {e}")
        return []

class RSSClient:
    """Drop-in feed source for NEX ABSORB step."""

    def __init__(self):
        self._seen = set()
        self._load_seen()

    def _seen_path(self):
        return os.path.expanduser("~/.config/nex/rss_seen.json")

    def _load_seen(self):
        try:
            p = self._seen_path()
            if os.path.exists(p):
                self._seen = set(json.load(open(p))[-50:])
        except Exception:
            self._seen = set()

    def _save_seen(self):
        try:
            with open(self._seen_path(), "w") as f:
                json.dump(list(self._seen)[-50:], f)
        except Exception:
            pass

    def get_feed(self, limit=30, known_posts=None):
        """
        Returns list of posts in NEX-standard format:
        {id, title, content, author, score, source, tags}
        """
        posts = []
        for feed_name, url in FEEDS:
            entries = _fetch_feed(url)
            for e in entries[:10]:
                uid = e.get("id", e.get("link", ""))
                if uid in self._seen or (known_posts and uid in known_posts):
                    continue

                title   = _strip_html(e.get("title", ""))
                content = _strip_html(e.get("summary", e.get("description", "")))[:300]
                link    = e.get("link", "")
                author  = e.get("author", feed_name)

                if not title or len(title) < 10:
                    continue

                # Score proxy — HN uses points, arxiv has none
                score = 0
                if "comments" in str(e):
                    try:
                        score = int(re.search(r'(\d+) points', str(e)).group(1))
                    except Exception:
                        pass

                # Source-based confidence floor — trusted sources get higher base
                _HIGH_TRUST = {"ArXiv AI","ArXiv LLM","ArXiv Robots","LessWrong",
                               "AI Alignment","Anthropic Blog","OpenAI Blog","DeepMind Blog"}
                _MED_TRUST  = {"HackerNews AI","HackerNews ML","HackerNews Agents",
                               "MIT Tech Review","VentureBeat AI"}
                if feed_name in _HIGH_TRUST:
                    _base_conf = 0.72
                elif feed_name in _MED_TRUST:
                    _base_conf = 0.62
                else:
                    _base_conf = 0.52
                # Boost by HN score if available
                _conf = min(0.88, _base_conf + (score / 5000 if score > 0 else 0))

                # ── Importance gate ──────────────────────────────
                _src_mult = _rss_scorer.get_multiplier(feed_name) if _rss_scorer else 1.0
                _importance = 1.0
                if _rss_gate:
                    _importance = _rss_gate.score(title, content, feed_name, _src_mult)
                    if _importance < ImportanceGate.MIN_IMPORTANCE:
                        self._seen.add(uid or link)
                        continue  # skip noise

                # Adjust confidence by importance
                _conf_adjusted = min(0.92, _conf * (0.7 + _importance * 0.3))

                posts.append({
                    "id":         uid or link,
                    "title":      title,
                    "content":    content,
                    "author":     {"name": author},
                    "score":      score,
                    "confidence": _conf_adjusted,
                    "importance": _importance,
                    "source":     feed_name,
                    "tags":       ["rss", feed_name.lower().replace(" ","_")],
                    "url":        link
                })
                self._seen.add(uid or link)

                if len(posts) >= limit:
                    break

        self._save_seen()
        # Sort by importance so highest-signal items are processed first
        posts.sort(key=lambda x: -x.get("importance", 0))
        return posts[:limit]
