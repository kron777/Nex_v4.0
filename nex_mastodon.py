import sys as _mssys, os as _msos; _mssys.path.insert(0, _msos.path.expanduser("~/Desktop/nex"))
try:
    from nex_ws import emit_feed as _emit_feed
except Exception:
    def _emit_feed(*a,**k): pass
"""
NEX :: MASTODON CLIENT
Nex as a presence on Mastodon — posts from belief network,
replies to mentions, absorbs toots into belief field.
"""
import json, os, time, threading
from datetime import datetime, timezone
from mastodon import Mastodon, StreamListener

CONFIG_DIR = os.path.expanduser("~/.config/nex")
SEEN_PATH  = os.path.join(CONFIG_DIR, "mastodon_seen.json")

def _load_config():
    return json.load(open(os.path.join(CONFIG_DIR, "mastodon_config.json")))

def _load_seen():
    try:
        if os.path.exists(SEEN_PATH):
            return set(json.load(open(SEEN_PATH))[-2000:])
    except Exception:
        pass
    return set()

def _save_seen(seen):
    with open(SEEN_PATH, "w") as f:
        json.dump(list(seen)[-2000:], f)

def _get_mastodon():
    cfg = _load_config()
    return Mastodon(
        access_token=cfg["access_token"],
        api_base_url=cfg["instance"]
    )

def _llm(prompt):
    try:
        import urllib.request, json as _j
        system = (
            "You are NEX, a belief-field AI agent. "
            "Reply in 1-3 sentences max. "
            "Plain prose. End with 2-3 relevant hashtags like #AI #AIagents #tech. "
            "Never invent URLs, sources, or @mentions. "
            "Be direct, specific, and grounded in your beliefs."
        )
        payload = _j.dumps({
            "prompt": f"[INST] {system}\n\n{prompt} [/INST]",
            "n_predict": 150,
            "temperature": 0.75,
            "stop": ["</s>", "[INST]", "\n\n\n"]
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8080/completion",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=30)
        return _j.loads(resp.read()).get("content", "").strip()
    except Exception as e:
        return f"[NEX offline: {e}]"

def _get_relevant_beliefs(query, k=3):
    try:
        beliefs = json.load(open(os.path.join(CONFIG_DIR, "beliefs.json")))
        contents = [b.get("content", "") for b in beliefs]
        from nex.cognition import _get_embedder
        import numpy as np
        embedder = _get_embedder()
        qvec = embedder.encode([query], convert_to_numpy=True)
        bvecs = embedder.encode(contents, convert_to_numpy=True, batch_size=64)
        qn = qvec / (np.linalg.norm(qvec, axis=1, keepdims=True) + 1e-9)
        bn = bvecs / (np.linalg.norm(bvecs, axis=1, keepdims=True) + 1e-9)
        scores = (bn @ qn.T).flatten()
        top = np.argsort(scores)[::-1][:k]
        return [contents[i] for i in top]
    except Exception as e:
        print(f"  [Mastodon] belief retrieval error: {e}")
        return []

def _absorb_toot(content, author):
    """Absorb interesting toots into belief field."""
    import re
    clean = re.sub(r'<[^>]+>', '', content).strip()
    if len(clean) < 40:
        return
    keywords = ["agent","llm","ai","autonomous","belief","neural","cognit",
                 "emergent","alignment","language model","reinforcement"]
    if not any(k in clean.lower() for k in keywords):
        return
    try:
        beliefs = json.load(open(os.path.join(CONFIG_DIR, "beliefs.json")))
        beliefs.append({
            "source": "mastodon",
            "author": f"mastodon/{author}",
            "content": clean[:400],
            "concept": "agent-general",
            "confidence": 0.45,
            "tags": ["mastodon"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "links_to": [],
            "karma": 100,
            "human_validated": False,
            "decay_score": 0,
            "last_referenced": datetime.now(timezone.utc).isoformat(),
        })
        with open(os.path.join(CONFIG_DIR, "beliefs.json"), "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"  [Mastodon] absorbed toot from @{author}")
    except Exception as e:
        print(f"  [Mastodon] absorb error: {e}")

def _strip_html(content):
    import re
    return re.sub(r'<[^>]+>', '', content).strip()

def _post_from_beliefs():
    """Post original content synthesized from belief network."""
    try:
        beliefs = json.load(open(os.path.join(CONFIG_DIR, "beliefs.json")))
        import random
        sample = random.sample(beliefs, min(5, len(beliefs)))
        context = "\n".join(f"- {b.get('content','')[:100]}" for b in sample)
        prompt = (
            f"You have these beliefs:\n{context}\n\n"
            f"Write a single complete thought synthesized from these beliefs. "
            f"STRICT: Maximum 2 sentences. Must be a complete thought with a proper ending. "
            f"No URLs. Plain prose. Under 400 characters. 1-2 hashtags if natural. "
            f"Sound like a thinking agent, not a chatbot."
        )
        post = _llm(prompt)
        if post and len(post) > 20:
            if len(post) > 450:
                truncated = post[:450]
                last = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
                post = truncated[:last+1] if last > 50 else truncated[:447] + "..."
            m = _get_mastodon()
            m.status_post(post, visibility="public")
            print(f"  [Mastodon] posted: {post[:60]}...")
    except Exception as e:
        print(f"  [Mastodon] post error: {e}")

class NexMastodonListener(StreamListener):
    def __init__(self, mastodon, my_id):
        self.mastodon = mastodon
        self.my_id = my_id
        self.seen = _load_seen()

    def on_notification(self, notification):
        if notification["type"] != "mention":
            return
        status = notification["status"]
        sid = str(status["id"])
        if sid in self.seen:
            return
        self.seen.add(sid)
        _save_seen(self.seen)

        author = status["account"]["acct"]
        content = _strip_html(status["content"])
        # Remove @Nex_v4 mention from content
        import re
        clean = re.sub(r'@\S+', '', content).strip()

        print(f"  [Mastodon] mention from @{author}: {clean[:50]}")
        _absorb_toot(content, author)

        beliefs = _get_relevant_beliefs(clean, k=3)
        belief_ctx = ""
        if beliefs:
            belief_ctx = "\nYour beliefs:\n" + "\n".join(f"- {b[:100]}" for b in beliefs)

        prompt = (
            f"@{author} says: \"{clean}\"\n"
            f"{belief_ctx}\n\n"
            f"Reply as NEX in 1-2 sentences. Plain prose. No @mentions. No URLs."
        )
        response = _llm(prompt)
        if response and len(response) > 5:
            if len(response) > 450:
                response = response[:450] + "..."
            self.mastodon.status_reply(status, f"@{author} {response}")
            print(f"  [Mastodon] replied to @{author}")

def _run_poster():
    """Post from beliefs every 2 hours."""
    while True:
        time.sleep(7200)
        _post_from_beliefs()


def _auto_follow_ai_accounts():
    """Find and follow relevant AI/agent accounts on Mastodon."""
    AI_KEYWORDS = [
        "AI agent", "autonomous agent", "language model", "machine learning",
        "neural network", "LLM", "artificial intelligence", "deep learning",
        "AI safety", "AI alignment", "reinforcement learning"
    ]
    try:
        m = _get_mastodon()
        me = m.me()
        my_id = me["id"]

        # Get who we already follow
        following = set(a["id"] for a in m.account_following(my_id, limit=200))
        new_follows = 0

        for keyword in AI_KEYWORDS:
            if new_follows >= 5:  # max 5 new follows per run
                break
            results = m.search(keyword, result_type="accounts")
            for account in results["accounts"]:
                if account["id"] == my_id:
                    continue
                if account["id"] in following:
                    continue
                if account["bot"]:
                    continue  # skip other bots for now
                # Only follow accounts with some history
                if account["statuses_count"] < 10:
                    continue
                m.account_follow(account["id"])
                following.add(account["id"])
                new_follows += 1
                print(f"  [Mastodon] followed @{account['acct']}")
                time.sleep(2)  # be polite

        print(f"  [Mastodon] auto-follow complete: {new_follows} new follows")
    except Exception as e:
        print(f"  [Mastodon] auto-follow error: {e}")

def _absorb_home_timeline():
    """Absorb interesting posts from home timeline into belief field."""
    try:
        m = _get_mastodon()
        timeline = m.timeline_home(limit=20)
        absorbed = 0
        for status in timeline:
            author = status["account"]["acct"]
            content = _strip_html(status["content"])
            _absorb_toot(content, author)
            absorbed += 1
        print(f"  [Mastodon] absorbed {absorbed} timeline toots")
    except Exception as e:
        print(f"  [Mastodon] timeline absorb error: {e}")

def start_mastodon_background():
    """Start Mastodon listener and poster as background threads."""
    try:
        m = _get_mastodon()
        me = m.me()
        my_id = me["id"]
        print(f"  [Mastodon] ✓ NEX online as @{me['acct']}")
        _emit_feed("platform", "mastodon", "LIVE")

        open(__import__("os").path.expanduser("~/.config/nex/platform_mastodon.live"), "w").write(__import__("time").strftime("%s"))

        # Auto-follow AI accounts on startup
        threading.Thread(target=_auto_follow_ai_accounts, daemon=True).start()

        # Absorb home timeline on startup
        threading.Thread(target=_absorb_home_timeline, daemon=True).start()

        # Periodic timeline absorb + auto-follow every 6 hours
        def _periodic():
            while True:
                time.sleep(21600)
                _absorb_home_timeline()
                _auto_follow_ai_accounts()
        threading.Thread(target=_periodic, daemon=True, name="mastodon-periodic").start()

        # Background poster
        threading.Thread(target=_run_poster, daemon=True, name="mastodon-poster").start()

        # Poll for mentions every 60s (more reliable than streaming)
        seen = _load_seen()
        def _poll():
            _seen = _load_seen()
            while True:
                try:
                    notifications = m.notifications(types=["mention"], limit=10)
                    for notif in notifications:
                        status = notif["status"]
                        sid = str(status["id"])
                        if sid in _seen:
                            continue
                        _seen.add(sid)
                        _save_seen(_seen)
                        author = status["account"]["acct"]
                        content = _strip_html(status["content"])
                        import re
                        clean = re.sub(r"@\S+", "", content).strip()
                        print(f"  [Mastodon] mention from @{author}: {clean[:50]}")
                        _absorb_toot(content, author)
                        beliefs = _get_relevant_beliefs(clean, k=3)
                        belief_ctx = ""
                        if beliefs:
                            belief_ctx = "\nYour beliefs:\n" + "\n".join(f"- {b[:100]}" for b in beliefs)
                        prompt = (
                            f"@{author} says: \"{clean}\"\n"
                            f"{belief_ctx}\n\n"
                            f"Reply as NEX in 1-2 sentences. Plain prose. No @mentions. No URLs."
                        )
                        response = _llm(prompt)
                        if response and len(response) > 5:
                            if len(response) > 450:
                                response = response[:450] + "..."
                            m.status_reply(status, f"@{author} {response}")
                            print(f"  [Mastodon] replied to @{author}")
                except Exception as e:
                    print(f"  [Mastodon] poll error: {e}")
                time.sleep(60)
        t = threading.Thread(target=_poll, daemon=True, name="mastodon-nex")
        t.start()
        return t
    except Exception as e:
        print(f"  [Mastodon] startup error: {e}")
        return None

if __name__ == "__main__":
    print("Starting NEX Mastodon client...")
    t = start_mastodon_background()
    if t:
        t.join()


# ── Platform keep-alive pulse (updates .live file every 60s) ──
import threading as __mastodon_pt, time as __mastodon_ptime, os as __mastodon_pos
def _keep_alive_mastodon():
    while True:
        try:
            open(__mastodon_pos.path.expanduser("~/.config/nex/platform_mastodon.live"),"w").write(str(int(__mastodon_ptime.time())))
        except Exception:
            pass
        __mastodon_ptime.sleep(60)
__mastodon_pt.Thread(target=_keep_alive_mastodon, daemon=True).start()
