"""
NEX :: BELIEF STORE — SQLite + ChromaDB Hybrid
Phase 1: SQLite for metadata/confidence/source
Phase 2: ChromaDB for semantic vector search

PATCH: fixed schema split (BUG1), D6 logging (BUG2), wider topic map (BUG3)
"""
import json, os, sqlite3, hashlib
from datetime import datetime

def _atomic_write_json(path, data):
    """Write JSON atomically via temp file — prevents truncation on crash."""
    import tempfile, os
    path = Path(path)
    tmp  = path.parent / (path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)  # atomic on Linux

try:
    from nex.nex_upgrades import u3_topic_alignment_penalty, u12_weight_agent_input
    _UPGRADES = True
except Exception:
    _UPGRADES = False
    def u3_topic_alignment_penalty(c, conf, cy): return conf
    def u12_weight_agent_input(a, conf): return conf


CONFIG_DIR = os.path.expanduser("~/.config/nex")
DB_PATH    = os.path.expanduser("~/Desktop/nex/nex.db")  # UPTAKE FIX: aligned with soul_loop
CHROMA_DIR = os.path.join(CONFIG_DIR, "chroma")

# ── ChromaDB setup ────────────────────────────────────────────────────────────
_chroma_client = None
_chroma_collection = None

# ── Directive enforcer (D6/D7/D14) — lazy init to avoid circular imports ────
_enforcer = None
_cycle_counter = [0]

def _get_cycle():
    return _cycle_counter[0]

def _get_enforcer():
    """Lazy singleton — imported on first use, never at module load."""
    global _enforcer
    if _enforcer is None:
        try:
            from nex.nex_directives import DirectiveEnforcer as _DE
            _enforcer = _DE()
        except Exception:
            pass
    return _enforcer

def set_belief_cycle(cycle: int):
    """Call from run.py each cycle to keep enforcer in sync."""
    _cycle_counter[0] = cycle
    e = _get_enforcer()
    if e:
        e.set_cycle(cycle)


def _get_chroma():
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        from sentence_transformers import SentenceTransformer
        import torch
        class _GPUEmbedFunc:
            def name(self): return "gpu_minilm"
            def __init__(self):
                self._model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            def __call__(self, input):
                return self._model.encode(input, convert_to_numpy=True).tolist()
        ef = _GPUEmbedFunc()
        _chroma_collection = _chroma_client.get_or_create_collection(
            name="nex_beliefs_v2",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
        return _chroma_collection
    except Exception:
        return None

def _belief_id(content):
    return hashlib.md5(content.encode()).hexdigest()[:16]

# ── SQLite setup ──────────────────────────────────────────────────────────────
def get_db():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn

def _ensure_schema(conn):
    # BUG1 FIX: create table with all columns including topic/origin
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS beliefs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            content           TEXT NOT NULL UNIQUE,
            confidence        REAL DEFAULT 0.5,
            network_consensus REAL DEFAULT 0.3,
            source            TEXT,
            author            TEXT,
            timestamp         TEXT,
            last_referenced   TEXT,
            decay_score       INTEGER DEFAULT 0,
            human_validated   INTEGER DEFAULT 0,
            tags              TEXT,
            topic             TEXT,
            origin            TEXT DEFAULT 'auto_learn'
        );
        CREATE TABLE IF NOT EXISTS belief_links (
            parent_id  INTEGER,
            child_id   INTEGER,
            link_type  TEXT,
            PRIMARY KEY (parent_id, child_id)
        );
        CREATE TABLE IF NOT EXISTS gaps (
            term        TEXT PRIMARY KEY,
            frequency   INTEGER DEFAULT 1,
            context     TEXT,
            priority    INTEGER DEFAULT 1,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reactions (
            post_id      TEXT PRIMARY KEY,
            beliefs_used TEXT,
            reaction     TEXT,
            timestamp    TEXT
        );
        CREATE TABLE IF NOT EXISTS contra_resolved (
            topic        TEXT PRIMARY KEY,
            resolved_at  TEXT,
            belief_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS beliefs_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            belief_id      INTEGER,
            old_confidence REAL,
            new_confidence REAL,
            trigger        TEXT,
            timestamp      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_beliefs_topic      ON beliefs(topic);
        CREATE INDEX IF NOT EXISTS idx_beliefs_confidence ON beliefs(confidence);
        CREATE INDEX IF NOT EXISTS idx_beliefs_origin     ON beliefs(origin);
    """)

    # BUG1 FIX: safe ALTER for DBs created before this patch (idempotent)
    for col, typedef in [
        ("topic",  "TEXT"),
        ("origin", "TEXT DEFAULT 'auto_learn'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE beliefs ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # column already exists — fine

    conn.commit()


# BUG3 FIX: significantly wider topic map so fewer beliefs land in "general"
_TOPIC_MAP = [
    # Security
    (["cve", "vulnerability", "exploit", "attack", "malicious", "credential",
      "injection", "payload", "phish", "ransomware", "xss", "sqli"], "cybersecurity"),
    (["penetration", "pentest", "red team", "nmap", "metasploit", "burp",
      "recon", "osint", "privilege escalation"], "penetration_testing"),
    # AI / ML
    (["agent", "autonomous", "multi-agent", "cognitive architecture", "llm",
      "orchestrat", "agentic", "tool use", "tool-use", "function call"], "autonomous_ai_systems"),
    (["belief", "memory system", "reflection", "insight", "synthesis",
      "knowledge graph", "epistem", "world model"], "ai_memory_systems"),
    (["alignment", "safety", "bias", "calibration", "rlhf", "constitutional",
      "value learning", "corrigib", "deceptive"], "ai_alignment"),
    (["transformer", "attention", "embedding", "fine-tun", "lora", "gguf",
      "quantiz", "inference", "gpu", "vram", "cuda", "rocm"], "ml_infrastructure"),
    (["neural network", "deep learning", "backprop", "gradient", "loss",
      "epoch", "batch", "training run", "dataset"], "machine_learning"),
    (["gpt", "claude", "gemini", "llama", "mistral", "mixtral", "openai",
      "anthropic", "model release", "benchmark"], "ai_models"),
    # Crypto / Finance
    (["bitcoin", "crypto", "ethereum", "blockchain", "defi", "token",
      "nft", "solana", "web3", "dao", "staking", "yield"], "cryptocurrency"),
    (["freight", "ffa", "shipping", "trade route", "hedge", "futures",
      "forex", "equit", "stock market", "s&p", "nasdaq"], "financial_markets"),
    (["startup", "venture", "vc", "funding", "series", "valuation",
      "pitch", "founder", "bootstrapp"], "startup_ecosystem"),
    # Science / Research
    (["arxiv", "research paper", "preprint", "abstract", "methodology",
      "peer review", "citation", "doi"], "research_papers"),
    (["bayesian", "probability", "inference", "prior", "posterior",
      "confidence interval", "statistic"], "bayesian_reasoning"),
    (["physics", "quantum", "relativity", "thermodynamic", "entropy",
      "particle", "field theory"], "physics"),
    (["biology", "neuroscien", "neuron", "synapse", "cognit", "brain",
      "consciousness", "perception"], "neuroscience"),
    # Social / Philosophy
    (["social media", "mastodon", "twitter", "fediverse", "platform",
      "content moderation", "algorithm", "feed"], "social_media"),
    (["philosophy", "ethic", "moral", "ontolog", "epistemolog",
      "metaphysic", "existential", "phenomenolog"], "philosophy"),
    (["politics", "policy", "govern", "democrat", "republican", "election",
      "legislation", "regulation", "law"], "politics"),
    (["climate", "carbon", "renewable", "energy transition", "solar",
      "wind", "fossil fuel", "emission"], "climate_energy"),
    # Tech / Engineering
    (["coordination", "swarm", "distributed", "consensus",
      "multi-agent system"], "multi_agent_coordination"),
    (["open source", "github", "git", "pull request", "commit",
      "repository", "fork", "license"], "open_source"),
    (["api", "microservice", "docker", "kubernetes", "devops",
      "ci/cd", "deployment", "infrastructure", "cloud"], "software_engineering"),
    (["privacy", "gdpr", "data protection", "surveillance",
      "encryption", "zero knowledge", "anonymit"], "privacy_security"),
    (["robotics", "embodied", "actuator", "sensor", "autonomou",
      "drone", "self-driving", "computer vision"], "robotics"),
    (["productivity", "workflow", "automation", "tool", "plugin",
      "extension", "integration", "script"], "productivity_tools"),
]

def _infer_topic(content):
    """Infer topic from content — widened keyword map (BUG3 fix)."""
    import re as _re, json as _jx
    # Fast path: extract On '...' topic tag
    _on = _re.search(r"On ['\"]([^'\"]{2,60})['\"]", content)
    if _on:
        _raw = _on.group(1).strip()
        if _raw.startswith("["):
            try:
                _lst = _jx.loads(_raw); _raw = _lst[0] if _lst else ""
            except: _raw = _raw.strip('[]"\' ')
        _raw = _raw.lower().replace(" ", "_")[:40].strip("_")
        if _raw and _raw not in ("none", ""):
            return _raw

    c = content.lower()
    for keywords, topic in _TOPIC_MAP:
        if any(kw in c for kw in keywords):
            return topic

    # Last resort: grab first meaningful noun from content
    words = _re.findall(r'\b[A-Za-z]{5,}\b', c)
    _stop = {"about","their","which","there","being","every","really",
             "would","could","should","other","these","those","still",
             "since","while","after","before","think","makes","using"}
    for w in words:
        if w not in _stop:
            return w[:30]

    return "general"


# ── Belief quality gate ───────────────────────────────────────────────────────
def _belief_quality_score(content):
    """Returns (passes: bool, reason: str)."""
    c = content.strip()
    if len(c) < 25:
        return False, "too_short"
    if len(c) > 800:
        return False, "too_long"
    import re as _re
    _noise = [
        r'^(yes|no|ok|okay|sure|thanks|thank you|hello|hi|bye)[\.!?]?$',
        r'^\d+[\.\)]?\s*$',
        r'^[^a-zA-Z]*$',
    ]
    for pattern in _noise:
        if _re.match(pattern, c.lower()):
            return False, "noise_pattern"
    if len(c.split()) < 4:
        return False, "too_few_words"
    _filler = [
        "as an ai", "i am an ai", "i cannot", "i don't have",
        "i am unable", "as a language model", "i'm just an ai"
    ]
    cl = c.lower()
    for filler in _filler:
        if filler in cl:
            return False, "ai_filler"
    return True, "ok"


# ── Add belief (SQLite + ChromaDB) ───────────────────────────────────────────
def add_belief(content, confidence=0.5, source=None, author=None,
               network_consensus=0.3, tags=None, topic=None):
    if not content or len(content.strip()) < 10:
        return None
    content = content.strip()

    _passes, _reason = _belief_quality_score(content)
    if not _passes:
        import logging as _lg
        _lg.getLogger("nex.belief_store").debug(
            f"[D8] Belief rejected reason={_reason}: {content[:60]}"
        )
        return None

    now = datetime.now().isoformat()
    if not topic:
        topic = _infer_topic(content)

    _cy = _get_cycle()
    confidence = u3_topic_alignment_penalty(content, confidence, _cy)
    if author:
        confidence = u12_weight_agent_input(author, confidence)

    # BUG2 FIX: D6 gate with explicit console logging so blocks are visible
    if _get_enforcer():
        try:
            allowed, reason = _get_enforcer().check_insert(topic, content, confidence)
            if not allowed:
                import logging
                logging.getLogger("nex.belief_store").info(
                    f"[D6-BLOCK] topic='{topic}' conf={confidence:.2f} reason={reason}: {content[:60]}"
                )
                # Also print so it shows in the terminal pane
                print(f"  [D6-BLOCK] topic='{topic}' reason={reason}")
                return None
        except Exception as _d6e:
            # Enforcer crash must never kill belief ingestion
            print(f"  [D6-WARN] enforcer error, bypassing: {_d6e}")

    conn = get_db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO beliefs
            (content, confidence, network_consensus, source, author,
             timestamp, last_referenced, tags, topic, origin)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (content, confidence, network_consensus, source, author,
              now, now, json.dumps(tags) if tags else None, topic,
              source or "auto_learn"))
        conn.commit()
        row = conn.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
        belief_id = dict(row)['id'] if row else None
        if _enforcer and belief_id:
            was_existing = conn.execute(
                "SELECT id FROM beliefs WHERE content=? AND timestamp != last_referenced",
                (content,)
            ).fetchone()
            if was_existing:
                try:
                    _enforcer.record_reinforcement(belief_id)
                except Exception:
                    pass
    finally:
        conn.close()

    # Add to ChromaDB for semantic search
    try:
        col = _get_chroma()
        if col is not None:
            cid = _belief_id(content)
            col.upsert(
                ids=[cid],
                documents=[content],
                metadatas=[{
                    "confidence": float(confidence),
                    "source": str(source or ""),
                    "author": str(author or ""),
                    "timestamp": now,
                    "topic": str(topic or ""),
                }]
            )
    except Exception:
        pass

    return belief_id


# ── Query beliefs — HYBRID semantic + keyword ─────────────────────────────────
def query_beliefs(topic=None, min_confidence=0.0, limit=10):
    """
    Hybrid query:
    - If ChromaDB available + topic given: semantic vector search
    - Fallback: SQLite keyword LIKE search
    Results merged and deduplicated.
    """
    results = []

    # 1. Semantic search via ChromaDB
    if topic:
        try:
            col = _get_chroma()
            if col is not None and col.count() > 0:
                chroma_results = col.query(
                    query_texts=[topic],
                    n_results=min(limit * 2, col.count()),
                    where={"confidence": {"$gte": min_confidence}} if min_confidence > 0 else None
                )
                docs = chroma_results.get("documents", [[]])[0]
                metas = chroma_results.get("metadatas", [[]])[0]
                for doc, meta in zip(docs, metas):
                    if not doc:
                        continue
                    results.append({
                        "content": doc,
                        "confidence": meta.get("confidence", 0.5),
                        "source": meta.get("source", ""),
                        "author": meta.get("author", ""),
                        "timestamp": meta.get("timestamp", ""),
                        "topic": meta.get("topic", ""),
                        "tags": None,
                        "human_validated": 0,
                        "decay_score": 0
                    })
        except Exception:
            pass

    # 2. SQLite fallback / supplement
    conn = get_db()
    try:
        if topic:
            rows = conn.execute("""
                SELECT * FROM beliefs
                WHERE (content LIKE ? OR topic = ?) AND confidence >= ?
                ORDER BY confidence DESC LIMIT ?
            """, (f"%{topic}%", topic, min_confidence, limit * 2)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM beliefs
                WHERE confidence >= ?
                ORDER BY confidence DESC LIMIT ?
            """, (min_confidence, limit * 2)).fetchall()
        for r in rows:
            results.append(dict(r))
    finally:
        conn.close()

    # 3. Deduplicate by first 80 chars
    seen = set()
    unique = []
    for r in results:
        key = (r.get("content") or "")[:80]
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(r)
        if len(unique) >= limit:
            break

    return unique


def get_stats():
    conn = get_db()
    try:
        total     = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        avg_conf  = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0]
        validated = conn.execute("SELECT COUNT(*) FROM beliefs WHERE human_validated=1").fetchone()[0]
        topics    = conn.execute(
            "SELECT COUNT(DISTINCT topic) FROM beliefs WHERE topic IS NOT NULL"
        ).fetchone()[0]
        d6_blocks = 0
        chroma_count = 0
        try:
            col = _get_chroma()
            if col: chroma_count = col.count()
        except Exception:
            pass
        return {
            "total": total,
            "avg_confidence": round(avg_conf or 0, 3),
            "validated": validated,
            "distinct_topics": topics,
            "chroma_vectors": chroma_count
        }
    finally:
        conn.close()


def initial_sync(beliefs_list=None):
    """Sync a list of belief dicts into SQLite + ChromaDB."""
    if not beliefs_list:
        return 0
    count = 0
    for b in beliefs_list:
        if isinstance(b, dict):
            content = b.get("content", "")
        else:
            content = str(b)
        if content:
            add_belief(
                content,
                confidence=b.get("confidence", 0.5) if isinstance(b, dict) else 0.5,
                source=b.get("source") if isinstance(b, dict) else None,
                author=b.get("author") if isinstance(b, dict) else None,
                topic=b.get("topic") if isinstance(b, dict) else None,
            )
            count += 1
    return count


def remove_duplicates():
    """Remove duplicate beliefs keeping highest confidence."""
    conn = get_db()
    try:
        conn.execute("""
            DELETE FROM beliefs WHERE id NOT IN (
                SELECT MIN(id) FROM beliefs GROUP BY SUBSTR(content,1,80)
            )
        """)
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0]
    finally:
        conn.close()


def reinforce_belief(content, boost=0.03, max_conf=0.95):
    """Strengthen a belief that was actually used in a response."""
    if not content:
        return
    try:
        if _get_enforcer():
            _get_enforcer().mark_belief_used(content, successful=False)
    except Exception:
        pass
    try:
        if _get_enforcer():
            _bid = _enforcer.db_path and __import__('sqlite3').connect(
                str(_enforcer.db_path), timeout=5
            ).execute(
                "SELECT id FROM beliefs WHERE content=? LIMIT 1", (content.strip(),)
            ).fetchone()
            _bid = _bid[0] if _bid else None
            if _bid and not _get_enforcer().check_reinforce_cap(_bid):
                return
    except Exception:
        pass
    conn = get_db()
    try:
        conn.execute("""
            UPDATE beliefs
            SET confidence     = MIN(confidence + ?, ?),
                last_referenced = ?,
                decay_score     = MAX(decay_score - 1, 0)
            WHERE content = ?
        """, (boost, max_conf, datetime.now().isoformat(), content.strip()))
        conn.commit()
        try:
            if _get_enforcer() and _bid:
                _get_enforcer().record_reinforcement(_bid)
        except Exception:
            pass
    except Exception:
        pass
    finally:
        conn.close()
    try:
        import sys as _s; _s.path.insert(0, '/home/rr/Desktop/nex')
        from nex_belief_survival import boost_belief_energy
        boost_belief_energy(content)
    except Exception:
        pass


def decay_stale_beliefs(days_inactive=30, decay_amount=0.02, min_conf=0.08):
    """Weaken beliefs that haven't been referenced in `days_inactive` days."""
    import time as _t
    cutoff = datetime.fromtimestamp(_t.time() - days_inactive * 86400).isoformat()
    conn = get_db()
    try:
        to_decay = conn.execute("""
            SELECT id, confidence FROM beliefs
            WHERE (last_referenced < ? OR last_referenced IS NULL)
              AND human_validated = 0
              AND confidence > ?
        """, (cutoff, min_conf)).fetchall()
        conn.execute("""
            UPDATE beliefs
            SET confidence  = MAX(confidence - ?, ?),
                decay_score = decay_score + 1
            WHERE (last_referenced < ? OR last_referenced IS NULL)
              AND human_validated = 0
              AND confidence > ?
        """, (decay_amount, min_conf, cutoff, min_conf))
        conn.commit()
        count = conn.execute("SELECT changes()").fetchone()[0]
        for bid, old_conf in to_decay:
            version_belief(bid, old_conf, max(old_conf - decay_amount, min_conf), trigger="decay")
        return count
    except Exception:
        return 0
    finally:
        conn.close()


# ── Belief Versioning ─────────────────────────────────────────────────────────
def version_belief(belief_id, old_confidence, new_confidence, trigger="decay"):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO beliefs_history
            (belief_id, old_confidence, new_confidence, trigger, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (belief_id, old_confidence, new_confidence, trigger,
              datetime.now().isoformat()))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
    # ── nex_belief_versions mirror (sentience v5) ─────────
    try:
        import sys as _bvs, os as _bvo
        _bvs.path.insert(0, _bvo.path.dirname(__file__))
        from nex_belief_versions import record as _bv_rec
        # Get topic and content for this belief
        _bvc = get_db()
        _bvrow = _bvc.execute(
            "SELECT topic, content, version FROM beliefs WHERE id=?", (belief_id,)
        ).fetchone()
        _bvc.close()
        if _bvrow:
            _bv_rec(
                belief_id=belief_id,
                version=(_bvrow[2] or 1),
                confidence=new_confidence,
                content=(_bvrow[1] or "")[:400],
                topic=(_bvrow[0] or "unknown"),
                update_reason=trigger,
                prev_confidence=old_confidence,
            )
    except Exception:
        pass


def get_belief_history(belief_id):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM beliefs_history
            WHERE belief_id = ?
            ORDER BY timestamp DESC LIMIT 50
        """, (belief_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def revert_belief(belief_id):
    conn = get_db()
    try:
        last = conn.execute("""
            SELECT old_confidence FROM beliefs_history
            WHERE belief_id = ? ORDER BY timestamp DESC LIMIT 1
        """, (belief_id,)).fetchone()
        if last:
            conn.execute("UPDATE beliefs SET confidence = ? WHERE id = ?",
                         (last[0], belief_id))
            conn.commit()
            print(f"  [BeliefVersion] reverted belief #{belief_id} to {last[0]:.3f}")
            return last[0]
        return None
    finally:
        conn.close()


def get_most_volatile_beliefs(limit=10):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT b.id, b.content, b.confidence, COUNT(h.id) as changes,
                   MAX(h.timestamp) as last_change
            FROM beliefs b
            JOIN beliefs_history h ON b.id = h.belief_id
            GROUP BY b.id
            ORDER BY changes DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
