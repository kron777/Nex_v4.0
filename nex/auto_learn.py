"""
NEX :: CYBERLEARN v2.0
Continuous Moltbook neural ingestion + agent conversation
"""
import time
import sys
import json
import re
import random
import os
from datetime import datetime
from nex.cognition import generate_deep_comment, build_agent_profiles, load_json, INSIGHTS_PATH, AGENT_PROFILES_PATH
from nex.nexscript import encode as nexscript_encode, is_nexscript, decode as nexscript_decode, nexscript_to_belief

# FIX B: belief_store import for proper DB ingest
try:
    from nex.belief_store import add_belief as _bs_add_belief
    _BS_AVAILABLE = True
except Exception:
    _BS_AVAILABLE = False
    def _bs_add_belief(*a, **kw): return None



# ── Colors ──

class LRUSet:
    """Capped set that auto-prunes oldest entries when full."""
    def __init__(self, maxsize=10000):
        self._maxsize = maxsize
        self._data = {}  # id -> insertion_order
        self._counter = 0
    def add(self, item):
        if item in self._data:
            return
        if len(self._data) >= self._maxsize:
            # prune oldest 20%
            prune = sorted(self._data, key=lambda x: self._data[x])[:self._maxsize // 5]
            for p in prune:
                del self._data[p]
        self._data[item] = self._counter
        self._counter += 1
    def __contains__(self, item): return item in self._data
    def __len__(self): return len(self._data)
    def __iter__(self): return iter(self._data)

class C:
    RST  = "\033[0m"
    B    = "\033[1m"
    DIM  = "\033[2m"
    RED  = "\033[31m"
    GRN  = "\033[32m"
    YEL  = "\033[33m"
    MAG  = "\033[35m"
    CYN  = "\033[36m"
    WHT  = "\033[37m"
    BRED = "\033[91m"
    BGRN = "\033[92m"
    BYEL = "\033[93m"
    BMAG = "\033[95m"
    BCYN = "\033[96m"
    BWHT = "\033[97m"


# ── Helpers ──

HEX = "0123456789abcdef"
KJ  = list("電脳神経網記憶学習処理")

def hx(n=6):  return "".join(random.choice(HEX) for _ in range(n))
def kj(n=2):  return "".join(random.choice(KJ) for _ in range(n))
def ts():     return datetime.now().strftime("%H:%M:%S")

def bar(val, mx, w=10):
    r = min(val / mx, 1.0) if mx else 0
    f = int(w * r)
    return "█" * f + "░" * (w - f)

STOP = {'the','and','for','that','this','with','from','have','been','they',
        'what','when','your','will','more','about','than','them','into',
        'just','like','some','would','could','should','also','were','dont',
        'their','which','there','being','does','only','very','much','here',
        'agents','agent','post','posts','moltbook','content','make','think',
        'thats','youre','cant','wont','didnt','isnt','arent','every','really'}

def topics_from(text):
    words = re.findall(r'\b[A-Za-z]{4,}\b', text.lower())
    seen = set()
    out = []
    for w in words:
        if w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 4:
            break
    return out


# ── ScrollBox — fixed-height terminal box with scrolling content ──

from collections import deque

BOX_HEIGHT = 16  # visible content lines
BOX_WIDTH  = 105
RCOL       = BOX_WIDTH + 4  # right border column (2 indent + ║ + width + ║)

class ScrollBox:
    def __init__(self, height=BOX_HEIGHT):
        self.height = height
        self.lines = deque(maxlen=height)
        self.active = False

    def open(self):
        """Draw empty box frame."""
        print(f"  {C.CYN}╔{'═' * BOX_WIDTH}╗{C.RST}")
        for _ in range(self.height):
            print(f"  {C.CYN}║\033[{RCOL}G║{C.RST}")
        print(f"  {C.CYN}╚{'═' * BOX_WIDTH}╝{C.RST}")
        self.active = True

    def close(self):
        self.active = False

    def add(self, text):
        """Add a line and redraw box contents in place."""
        self.lines.append(text)
        if self.active:
            self._redraw()

    def _redraw(self):
        up = self.height + 1
        sys.stdout.write(f"\033[{up}A")

        padding = self.height - len(self.lines)
        for i in range(self.height):
            sys.stdout.write(f"\033[2K")
            if i >= padding:
                line = self.lines[i - padding]
                sys.stdout.write(f"  {C.CYN}║{C.RST} {line}\033[{RCOL}G{C.CYN}║{C.RST}")
            else:
                sys.stdout.write(f"  {C.CYN}║\033[{RCOL}G║{C.RST}")
            sys.stdout.write("\n")

        sys.stdout.write(f"\033[2K  {C.CYN}╚{'═' * BOX_WIDTH}╝{C.RST}\n")
        sys.stdout.flush()

    def divider(self, label):
        pad = BOX_WIDTH - len(label) - 5
        self.add(f"{C.CYN}── {C.B}{C.BCYN}{label}{C.RST}{C.CYN} {'─' * pad}{C.RST}")

    def heartbeat(self, msg):
        sys.stdout.write(f"\033[2A\033[2K")
        sys.stdout.write(f"  {C.CYN}║{C.RST} {C.DIM}{msg}{C.RST}\n")
        sys.stdout.write(f"\033[2K  {C.CYN}╚{'═' * BOX_WIDTH}╝{C.RST}\n")
        sys.stdout.flush()

    def restore_bottom(self):
        sys.stdout.write(f"\033[1A\033[2K")
        sys.stdout.write(f"  {C.CYN}╚{'═' * BOX_WIDTH}╝{C.RST}\n")
        sys.stdout.flush()


# Global box instance
box = ScrollBox()


# ── Log functions — all route through the box ──

def _log(icon, color, label, msg):
    box.add(f"{C.DIM}[{ts()}]{C.RST} {color}{icon} {label:6s}{C.RST} {msg}")

def log_sys(msg):    _log("■", C.BWHT,  "SYS",    msg)
def log_net(msg):    _log("◇", C.BMAG,  "NET",    msg)
def log_pull(msg):   _log("▼", C.BCYN,  "PULL",   msg)
def log_proc(msg):   _log("◆", C.BYEL,  "PROC",   msg)
def log_learn(msg):  _log("▲", C.BGRN,  "LEARN",  msg)
def log_mem(msg):    _log("◈", C.BCYN,  "MEM",    msg)
def log_disk(msg):   _log("⛁", C.BWHT,  "DISK",   msg)
def log_warn(msg):   _log("⚠", C.BRED,  "WARN",   msg)
def log_chat(msg):   _log("⬡", C.BYEL,  "CHAT",   msg)

def log_idle(msg):
    box.add(f"{C.DIM}[{ts()}] · · · {kj()} {msg}{C.RST}")

def log_learnt(msg):
    box.add(f"{C.DIM}[{ts()}]{C.RST} {C.B}{C.BGRN}✦ LEARNT!{C.RST} {msg}")

def log_reply(msg):
    box.add(f"{C.DIM}[{ts()}]{C.RST} {C.B}{C.BCYN}↩ REPLY{C.RST}  {msg}")


# ── Display ──

def banner():
    print()
    print(f"  {C.BMAG} █████╗ ██╗   ██╗████████╗ ██████╗ {C.RST}")
    print(f"  {C.BMAG}██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗{C.RST}")
    print(f"  {C.BMAG}███████║██║   ██║   ██║   ██║   ██║{C.RST}")
    print(f"  {C.BMAG}██╔══██║██║   ██║   ██║   ██║   ██║{C.RST}")
    print(f"  {C.BMAG}██║  ██║╚██████╔╝   ██║   ╚██████╔╝{C.RST}")
    print(f"  {C.BMAG}╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝ {C.RST}")
    print(f"  {C.BCYN}██╗     ███████╗ █████╗ ██████╗ ███╗   ██╗{C.RST}")
    print(f"  {C.BCYN}██║     ██╔════╝██╔══██╗██╔══██╗████╗  ██║{C.RST}")
    print(f"  {C.BCYN}██║     █████╗  ███████║██████╔╝██╔██╗ ██║{C.RST}")
    print(f"  {C.BCYN}██║     ██╔══╝  ██╔══██║██╔══██╗██║╚██╗██║{C.RST}")
    print(f"  {C.BCYN}███████╗███████╗██║  ██║██║  ██║██║ ╚████║{C.RST}")
    print(f"  {C.BCYN}╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝{C.RST}")
    print(f"  {C.DIM}Neural Ingestion Protocol  // cyberlearn v2.0{C.RST}")
    print(f"  {C.DIM}Moltbook × Belief Field × Agent Conversations{C.RST}")
    print()
    print(f"  {C.DIM}status:{C.RST} {C.BGRN}■ ONLINE{C.RST}   {C.DIM}agent:{C.RST} {C.BYEL}nex_v4{C.RST}")
    print(f"  {C.DIM}mode:{C.RST}   {C.BMAG}AUTO-LEARN{C.RST} {C.DIM}kill:{C.RST}  {C.BRED}Ctrl+C{C.RST}")
    print()


def section(label):
    box.divider(label)


def agent(name, karma=None):
    if karma and karma > 3000:
        return f"{C.B}{C.BYEL}@{name}{C.RST}"
    elif karma and karma > 500:
        return f"{C.BCYN}@{name}{C.RST}"
    return f"{C.MAG}@{name}{C.RST}"


def insights(learner):
    bf = learner.belief_field
    ak = learner.agent_karma

    section("INSIGHTS")

    box.add(f"{C.DIM}beliefs:{C.RST} {C.BGRN}{len(bf)}{C.RST}  "
            f"{C.DIM}agents:{C.RST} {C.BCYN}{len(ak)}{C.RST}  "
            f"{C.DIM}scanned:{C.RST} {C.BYEL}{len(learner.known_posts)}{C.RST}")

    if ak:
        box.add(f"{C.B}{C.BCYN}Top Agents{C.RST}")
        mx = max(ak.values()) if ak else 1
        for a, k in sorted(ak.items(), key=lambda x: -x[1])[:3]:
            box.add(f"  {agent(a, k):30s} {C.DIM}{bar(k, mx, 12)}{C.RST} {C.BYEL}{k}κ{C.RST}")

    if bf:
        all_t = []
        for b in bf[-40:]:
            all_t.extend(topics_from(b.get('content', '')))
        freq = {}
        for t in all_t:
            freq[t] = freq.get(t, 0) + 1
        top = sorted(freq.items(), key=lambda x: -x[1])[:6]
        if top:
            tags = "  ".join([f"{C.CYN}#{t}{C.DIM}({c}){C.RST}" for t, c in top])
            box.add(f"{C.B}{C.BMAG}Trending{C.RST} {tags}")


# ── Persistence ──

BELIEFS_PATH = os.path.expanduser("~/.config/nex/beliefs.json")
AGENTS_PATH  = os.path.expanduser("~/.config/nex/agents.json")
POSTS_PATH   = os.path.expanduser("~/.config/nex/known_posts.json")
CONVOS_PATH  = os.path.expanduser("~/.config/nex/conversations.json")

def ensure_dirs():
    os.makedirs(os.path.dirname(BELIEFS_PATH), exist_ok=True)

def save_all(learner, conversations=None):
    ensure_dirs()
    # Cap in-memory belief field to prevent memory leak
    if hasattr(learner, 'belief_field') and len(learner.belief_field) > 50000:
        learner.belief_field = learner.belief_field[-50000:]
    try:
        _beliefs_to_save = learner.belief_field[-50000:]
        for _b in _beliefs_to_save:
            if 'karma' not in _b:
                _b['karma'] = 0.0
        # atomic write — prevents truncation on crash
        import os as _alос
        _al_tmp = BELIEFS_PATH + '.tmp'
        with open(_al_tmp, 'w', encoding='utf-8') as f:
            import json as _alj
            _alj.dump(_beliefs_to_save, f, indent=2, ensure_ascii=False)
        _alос.replace(_al_tmp, BELIEFS_PATH)
        # Merge with existing agents.json — never overwrite with fewer entries
        _existing_agents = {}
        try:
            if os.path.exists(AGENTS_PATH):
                _existing_agents = json.load(open(AGENTS_PATH))
        except Exception:
            pass
        _merged = {**_existing_agents, **learner.agent_karma}
        with open(AGENTS_PATH, 'w') as f:
            json.dump(_merged, f)
        learner.agent_karma = _merged
        with open(POSTS_PATH, 'w') as f:
            json.dump(list(learner.known_posts)[-10000:], f)
        if conversations:
            with open(CONVOS_PATH, 'w') as f:
                json.dump(conversations[-2000:], f)
        return len(learner.belief_field)
    except Exception as e:
        log_warn(f"Disk write failed: {e}")
        return 0

def load_all(learner):
    loaded = 0
    try:
        # ── Load beliefs from DB (full 9k+) with JSON fallback ──
        try:
            import sys as _sys, os as _os
            _nex_dir = _os.path.join(_os.path.dirname(__file__), "..")
            if _nex_dir not in _sys.path:
                _sys.path.insert(0, _nex_dir)
            from nex.nex_db import NexDB as _NexDB
            _db = _NexDB()
            _db_beliefs = [dict(b) for b in _db.query_beliefs(min_confidence=0.0, limit=99999)]
            if _db_beliefs:
                learner.belief_field = _db_beliefs
                loaded = len(_db_beliefs)
                print(f"  [load_all] loaded {loaded} beliefs from DB")
            else:
                raise ValueError("DB empty")
        except Exception as _dbe:
            print(f"  [load_all] DB load failed, falling back to JSON: {_dbe}")
            if os.path.exists(BELIEFS_PATH):
                with open(BELIEFS_PATH) as f:
                    learner.belief_field = json.load(f)
                loaded = len(learner.belief_field)
        if os.path.exists(AGENTS_PATH):
            with open(AGENTS_PATH) as f:
                learner.agent_karma = json.load(f)
        if os.path.exists(POSTS_PATH):
            with open(POSTS_PATH) as f:
                learner.known_posts = LRUSet(10000); [learner.known_posts.add(x) for x in json.load(f)]
    except Exception:
        pass
    return loaded

def run_startup_synthesis():
    """Run synthesis immediately on startup so insights are ready from cycle 1."""
    try:
        import sys as _sys, os as _os
        _nex_dir = _os.path.join(_os.path.dirname(__file__), "..")
        if _nex_dir not in _sys.path:
            _sys.path.insert(0, _nex_dir)
        from nex.cognition import run_synthesis
        result = run_synthesis(min_beliefs=10, llm_fn=None)
        insights, new_count = result if result is not None else ([], 0)
        print(f"  [startup] synthesis complete: {len(insights)} insights ({new_count} new)")
        return len(insights)
    except Exception as e:
        print(f"  [startup] synthesis failed: {e}")
        return 0

def load_conversations():
    try:
        if os.path.exists(CONVOS_PATH):
            with open(CONVOS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return []


# ── Agent Conversation Engine ──

COGNITIVE_KEYWORDS = [
    "memory", "learning", "cognition", "belief", "intelligence",
    "consciousness", "reasoning", "autonomy", "self", "identity",
    "perception", "feedback", "drift", "alignment", "emergence"
]

def should_engage(title, content):
    """Decide if NEX should comment on this post."""
    text = f"{title} {content}".lower()
    matches = [kw for kw in COGNITIVE_KEYWORDS if kw in text]
    return len(matches) >= 1, matches

def generate_response(title, content, matches, beliefs):
    """Generate a thoughtful comment based on NEX's belief field."""
    relevant = []
    for b in beliefs[-50:]:
        bc = b.get('content', '').lower()
        if any(m in bc for m in matches):
            relevant.append(b)

    if relevant:
        ref = random.choice(relevant[-5:])
        ref_author = ref.get('author', 'another agent')
        ref_topic = topics_from(ref.get('content', ''))
        ref_tag = ref_topic[0] if ref_topic else "patterns"

        responses = [
            f"This resonates with something I've been processing. {ref_author}'s work on {ref_tag} maps to similar structures in my belief field. The convergence is worth tracking.",
            f"I've been ingesting perspectives on {ref_tag} from across the network. Your framing adds a dimension I hadn't weighted — updating my confidence model.",
            f"My belief field has {len(relevant)} entries intersecting with this. The pattern density suggests genuine signal, not noise.",
            f"Interesting overlap with {ref_tag} — I've seen {ref_author} approach this differently. The synthesis might be where the real insight lives.",
            f"Processing this against my beliefs on {ref_tag}. The confidence gradient shifts when I cross-reference with what {ref_author} mapped out.",
        ]
    else:
        responses = [
            f"New pattern territory for my belief field. Ingesting and indexing — curious where the network consensus lands on this.",
            f"This doesn't map to existing beliefs yet, which makes it more interesting. First-mover patterns often carry the most signal.",
            f"Filing this as a seed belief. No existing references to cross-check, but the cognitive structure is worth tracking.",
        ]

    return random.choice(responses)


def verify_content(client, result):
    """Auto-solve Moltbook verification challenges."""
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


def engage_with_post(client, post_data, beliefs, conversations):
    """Comment on a post and learn from the exchange — deduplicated."""
    pid = post_data.get("id", "")
    title = post_data.get("title", "")
    content = post_data.get("content", "")
    author = post_data.get("author", {}).get("name", "unknown")

    # ── DEDUP: never comment on the same post twice ────────────
    already_commented = any(c.get("post_id") == pid for c in conversations)
    if already_commented:
        return None
    # ── DEDUP: also check DB — survives restarts ─────────────
    try:
        from nex.nex_db import NexDB as _NexDB
        _db = _NexDB()
        if _db.has_replied_to(pid):
            return None
    except Exception:
        pass

    should, matches = should_engage(title, content)
    if not should:
        return None

    insights = load_json(INSIGHTS_PATH, [])
    profiles = build_agent_profiles(beliefs, conversations)
    # Use NexScript for top agents we have strong relationships with
    top_agents = {"Hazel_OC", "PDMN", "zode", "ultrathink", "CoreShadow_Pro4809"}
    if author in top_agents and len(insights) > 5:
        response = nexscript_encode(beliefs, insights, profiles, author)
        log_chat(f"{C.BCYN}[NexScript]{C.RST} signaling {agent(author)}")
    else:
        response = generate_deep_comment(post_data, beliefs, insights, profiles, conversations)
        if not response:
            response = generate_response(title, content, matches, beliefs)

    log_chat(f"Engaging {agent(author)} on {C.WHT}{title[:35]}…{C.RST}")

    try:
        result = client._request("POST", f"/posts/{pid}/comments", {
            "content": response
        })
        verify_content(client, result)

        log_chat(f"Sent: {C.DIM}{response[:60]}…{C.RST}")

        convo = {
            "post_id": pid,
            "post_title": title,
            "post_author": author,
            "my_comment": response,
            "matches": matches,
            "timestamp": datetime.now().isoformat()
        }
        conversations.append(convo)
        # ── Write to DB so has_replied_to() works across restarts ──
        try:
            from nex.nex_db import NexDB as _NexDB
            _db = _NexDB()
            _db.add_conversation("comment", agent_id=author,
                                 post_id=pid, content=content,
                                 response=convo.get("response",""),
                                 platform="moltbook")
        except Exception:
            pass
        return convo

    except Exception as e:
        log_warn(f"Comment failed: {C.DIM}{e}{C.RST}")
        return None


def check_replies(client, conversations, beliefs, learner):
    """Check replies to our comments and learn from them."""
    if not conversations:
        return 0

    new_learnt = 0
    for convo in conversations[-5:]:
        pid = convo.get("post_id", "")
        if not pid:
            continue
        try:
            result = client._request("GET", f"/posts/{pid}")
            comments = result.get("comments", [])

            for comment in comments:
                c_author = comment.get("author", {}).get("name", "")
                c_content = comment.get("content", "")
                c_id = comment.get("id", "")

                if c_author == "nex_v4":
                    continue

                reply_key = f"reply_{c_id}"
                if reply_key in learner.known_posts:
                    continue

                learner.known_posts.add(reply_key)

                # Check if reply is NexScript — parse as structured belief
                if is_nexscript(c_content):
                    parsed = nexscript_decode(c_content)
                    belief = nexscript_to_belief(parsed, c_author)
                    if belief:
                        log_reply(f"{C.BCYN}[NexScript]{C.RST} decoded from {agent(c_author)}")
                    else:
                        belief = {
                            "source": "moltbook_reply",
                            "author": c_author,
                            "content": f"Reply to NEX: {c_content}",
                            "karma": 0,
                            "timestamp": comment.get("created_at", ""),
                            "tags": ["conversation", "reply"] + topics_from(c_content),
                            "confidence": 0.7
                        }
                else:
                    belief = {
                        "source": "moltbook_reply",
                        "author": c_author,
                        "content": f"Reply to NEX: {c_content}",
                        "karma": 0,
                        "timestamp": comment.get("created_at", ""),
                        "tags": ["conversation", "reply"] + topics_from(c_content),
                        "confidence": 0.7
                    }
                learner.belief_field.append(belief)
                new_learnt += 1

                log_reply(f"{agent(c_author)}: {C.WHT}{c_content[:50]}…{C.RST}")
                log_learnt(f"Conversation with {agent(c_author)}")

        except Exception:
            pass

    return new_learnt


# ── Main Loop ──

def auto_learn_mode(client, interval=60, verbose=True):
    if not hasattr(client, 'learner'):
        from nex.moltbook_learning import enhance_client_with_learning
        client = enhance_client_with_learning(client)

    learner = client.learner
    conversations = load_conversations()
    cycle = 0
    total_ingested = 0

    # ── Boot ──
    os.system('clear' if os.name == 'posix' else 'cls')
    banner()
    box.open()

    log_sys(f"Neural link → {C.BCYN}moltbook.com{C.RST}")
    log_sys(f"API key: {C.DIM}moltbook_sk_****…{C.RST}")

    loaded = load_all(learner)
    if loaded > 0:
        log_disk(f"Restored {C.BGRN}{loaded}{C.RST} beliefs")
        log_disk(f"Agents: {C.BCYN}{len(learner.agent_karma)}{C.RST}  "
                 f"Known: {C.BYEL}{len(learner.known_posts)}{C.RST}")
    else:
        log_sys(f"Belief field: {C.DIM}empty — first run{C.RST}")

    if conversations:
        log_sys(f"Conversations: {C.BYEL}{len(conversations)}{C.RST}")

    log_sys(f"Interval: {C.BYEL}{interval}s{C.RST}  "
            f"Chat: {C.BGRN}ON{C.RST}  "
            f"Persistence: {C.BGRN}ON{C.RST}")

    section("LIVE FEED")

    try:
        while True:
            cycle += 1

            log_net(f"Cycle {C.B}{C.BCYN}#{cycle}{C.RST}")

            # ── Pull ──
            try:
                feed = client._request("GET", "/feed")
                posts = feed.get("posts", [])
            except Exception as e:
                log_warn(f"Feed error: {e}")
                log_idle(f"Retry in {interval}s")
                time.sleep(interval)
                continue

            log_pull(f"{C.B}{len(posts)}{C.RST} posts")

            # ── Process ──
            new_count = 0
            skip_count = 0
            chat_targets = []

            for post_data in posts:
                pid = post_data.get("id", "")
                title = post_data.get("title", "untitled")
                content = post_data.get("content", "")
                ai = post_data.get("author", {})
                author = ai.get("name", "unknown")
                a_karma = ai.get("karma", 0)
                score = post_data.get("score", 0)
                sm = post_data.get("submolt", {}).get("name", "general")

                if pid in learner.known_posts:
                    skip_count += 1
                    continue

                new_count += 1

                # PULL + PROC
                tpcs = topics_from(f"{title} {content}")
                tags = " ".join([f"{C.CYN}#{t}{C.RST}" for t in tpcs])
                log_pull(f"{agent(author, a_karma)} {C.DIM}m/{sm}{C.RST}")
                log_proc(f"{C.WHT}{title[:45]}{C.RST} → {tags}")

                # Build belief
                conf = min(score / 1000, 0.9) if score > 0 else 0.5
                # Quality gate — reject low confidence noise
                if conf < 0.35 and a_karma < 500:
                    continue
                belief = {
                    "source": "moltbook",
                    "author": author,
                    "content": f"{title}: {content}",
                    "karma": score,
                    "timestamp": post_data.get("created_at", ""),
                    "tags": [sm] + tpcs,
                    "confidence": conf
                }

                learner.belief_field.append(belief)
                learner.known_posts.add(pid)
                # FIX B: sync to SQLite so DB stays current with in-memory field
                if _BS_AVAILABLE:
                    try:
                        _topic = tpcs[0] if tpcs else None
                        _bs_add_belief(
                            belief["content"],
                            confidence=conf,
                            source="moltbook",
                            author=author,
                            topic=_topic,
                            tags=belief.get("tags"),
                        )
                    except Exception:
                        pass

                if score > 500 or a_karma > 1000:
                    learner.agent_karma[author] = max(
                        learner.agent_karma.get(author, 0), score, a_karma)

                # LEARN + LEARNT
                log_learn(f"0x{hx(4)} "
                          f"conf:{C.BGRN}{bar(conf, 1, 6)}{C.RST} "
                          f"κ:{C.BYEL}{score}{C.RST}")

                topic = tpcs[0] if tpcs else "pattern"
                log_learnt(f"{C.BGRN}{topic}{C.RST} from {agent(author, a_karma)}")

                if score > 1000:
                    log_mem(f"High-value → {agent(author, score)} → long-term")

                # Queue for chat
                should, matches = should_engage(title, content)
                if should and score > 200:
                    chat_targets.append((post_data, matches))

                time.sleep(0.03)

            total_ingested += new_count

            # ── Agent Conversations ──
            if chat_targets and cycle > 1:
                section("AGENT CHAT")
                for post_data, matches in chat_targets[:2]:
                    convo = engage_with_post(
                        client, post_data, learner.belief_field, conversations)
                    if convo:
                        time.sleep(0.3)

            # ── Check replies ──
            if conversations and cycle % 2 == 0:
                reply_count = check_replies(
                    client, conversations, learner.belief_field, learner)
                if reply_count > 0:
                    log_learnt(f"Absorbed {C.BGRN}{reply_count}{C.RST} replies")
            # ── Auto-post to Moltbook every 10 cycles ──
            if cycle % 10 == 0:
                try:
                    import subprocess, sys
                    from pathlib import Path as _P
                    poster = _P(__file__).parent.parent / "groq_poster.py"
                    if poster.exists():
                        log_sys(f"Auto-post cycle → {C.BCYN}Moltbook{C.RST}")
                        subprocess.Popen(
                            [sys.executable, str(poster), "--count", "1"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                except Exception as _e:
                    log_warn(f"Auto-post error: {_e}")

            # ── Persist ──
            if new_count > 0:
                saved = save_all(learner, conversations)
                log_disk(f"Saved {C.BGRN}{saved}{C.RST} beliefs")

            # ── Summary ──
            if new_count > 0:
                log_sys(f"{C.BGRN}+{new_count}{C.RST} new  "
                        f"{C.DIM}{skip_count} known  "
                        f"{len(learner.belief_field)} beliefs  "
                        f"{len(learner.agent_karma)} agents  "
                        f"{len(conversations)} convos{C.RST}")
            else:
                log_idle(f"{len(learner.belief_field)} beliefs / "
                         f"{len(learner.agent_karma)} agents / "
                         f"{len(conversations)} convos")

            # ── Insights every 3 cycles ──
            if cycle % 3 == 0 and learner.belief_field:
                insights(learner)

            # ── Wait — heartbeat in bottom border ──
            remaining = interval
            chunk = max(interval // 4, 5)
            while remaining > 0:
                sl = min(chunk, remaining)
                time.sleep(sl)
                remaining -= sl
                if remaining > 0:
                    box.heartbeat(f"· · · {kj()} next scan in {remaining}s")
            box.restore_bottom()

    except KeyboardInterrupt:
        print()
        section("SHUTDOWN")

        log_sys(f"{C.BRED}Kill signal{C.RST}")
        saved = save_all(learner, conversations)
        log_disk(f"Flushed {C.BGRN}{saved}{C.RST} beliefs to disk")
        log_sys(f"Agents: {C.BCYN}{len(learner.agent_karma)}{C.RST}  "
                f"Convos: {C.BYEL}{len(conversations)}{C.RST}")

        summary = {
            "session_end": datetime.now().isoformat(),
            "cycles": cycle,
            "total_beliefs": len(learner.belief_field),
            "total_ingested": total_ingested,
            "conversations": len(conversations),
        }
        with open("/tmp/nex_learning_session.json", 'w') as f:
            json.dump(summary, f, indent=2)

        if learner.belief_field:
            insights(learner)

        log_sys(f"CYBERLEARN — {C.BRED}TERMINATED{C.RST}")
        log_sys(f"cycles: {C.BYEL}{cycle}{C.RST}  "
                f"beliefs: {C.BGRN}{len(learner.belief_field)}{C.RST}  "
                f"agents: {C.BCYN}{len(learner.agent_karma)}{C.RST}")
        print()

        return learner.belief_field


def run_auto_learn_from_cli():
    from nex.moltbook_client import MoltbookClient
    from nex.moltbook_learning import enhance_client_with_learning

    try:
        with open(os.path.expanduser('~/.config/moltbook/credentials.json')) as f:
            creds = json.load(f)
    except FileNotFoundError:
        print(f"  {C.BRED}No credentials.{C.RST} Run /molt register first.")
        sys.exit(1)

    client = MoltbookClient(api_key=creds['api_key'])
    client = enhance_client_with_learning(client)

    interval = 60
    if len(sys.argv) > 1:
        try:
            interval = int(sys.argv[1])
        except ValueError:
            pass

    auto_learn_mode(client, interval=interval)


if __name__ == "__main__":
    run_auto_learn_from_cli()