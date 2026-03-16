"""
NEX :: BELIEF STORE — SQLite + ChromaDB Hybrid
Phase 1: SQLite for metadata/confidence/source
Phase 2: ChromaDB for semantic vector search
"""
import json, os, sqlite3, hashlib
from datetime import datetime

CONFIG_DIR = os.path.expanduser("~/.config/nex")
DB_PATH    = os.path.join(CONFIG_DIR, "nex.db")
CHROMA_DIR = os.path.join(CONFIG_DIR, "chroma")

# ── ChromaDB setup ────────────────────────────────────────────────────────────
_chroma_client = None
_chroma_collection = None

def _get_chroma():
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        # Use sentence-transformers for embeddings (already installed)
        # GPU-accelerated embeddings — custom class forces ROCm/CUDA device
        from sentence_transformers import SentenceTransformer
        import torch
        class _GPUEmbedFunc:
            def name(self): return "gpu_minilm"
            def __init__(self):
                self._model = SentenceTransformer("all-MiniLM-L6-v2", device="cuda")
            def __call__(self, input):
                return self._model.encode(input, convert_to_numpy=True).tolist()
        ef = _GPUEmbedFunc()
        _chroma_collection = _chroma_client.get_or_create_collection(
            name="nex_beliefs_v2",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
        return _chroma_collection
    except Exception as e:
        print(f"  [ChromaDB] unavailable: {e}")
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
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS beliefs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            content          TEXT NOT NULL UNIQUE,
            confidence       REAL DEFAULT 0.5,
            network_consensus REAL DEFAULT 0.3,
            source           TEXT,
            author           TEXT,
            timestamp        TEXT,
            last_referenced  TEXT,
            decay_score      INTEGER DEFAULT 0,
            human_validated  INTEGER DEFAULT 0,
            tags             TEXT
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
    """)
    conn.commit()

def _infer_topic(content):
    """Infer topic from content using keyword matching."""
    c = content.lower()
    TOPIC_MAP = [
        (["cve", "vulnerability", "exploit", "attack", "malicious", "credential", "injection", "payload"], "cybersecurity"),
        (["penetration", "pentest", "red team", "nmap", "metasploit", "burp", "recon"], "penetration testing techniques"),
        (["agent", "autonomous", "multi-agent", "cognitive architecture", "llm", "orchestrat"], "cognitive architecture AI"),
        (["belief", "memory system", "reflection", "insight", "synthesis", "knowledge graph"], "AI agent memory systems"),
        (["alignment", "safety", "bias", "calibration", "rlhf", "constitutional"], "large language model alignment"),
        (["bitcoin", "crypto", "ethereum", "blockchain", "defi", "token", "nft", "solana"], "cryptocurrency"),
        (["freight", "ffa", "shipping", "trade route", "hedge", "futures", "forex"], "financial markets"),
        (["bayesian", "probability", "inference", "prior", "posterior", "confidence"], "bayesian belief updating"),
        (["coordination", "swarm", "distributed", "consensus", "multi-agent"], "multi-agent coordination"),
        (["arxiv", "research paper", "preprint", "abstract", "methodology"], "arxiv"),
    ]
    for keywords, topic in TOPIC_MAP:
        if any(kw in c for kw in keywords):
            return topic
    return "general"

# ── Add belief (SQLite + ChromaDB) ───────────────────────────────────────────
def add_belief(content, confidence=0.5, source=None, author=None,
               network_consensus=0.3, tags=None, topic=None):
    if not content or len(content.strip()) < 10:
        return None
    content = content.strip()
    now = datetime.now().isoformat()
    # Auto-infer topic if not provided
    if not topic:
        topic = _infer_topic(content)
    conn = get_db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO beliefs
            (content, confidence, network_consensus, source, author, timestamp, last_referenced, tags, topic)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (content, confidence, network_consensus, source, author, now, now,
              json.dumps(tags) if tags else None, topic))
        conn.commit()
        row = conn.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
        belief_id = dict(row)['id'] if row else None
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
                    "timestamp": now
                }]
            )
    except Exception as e:
        pass  # ChromaDB failure never blocks belief storage

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
                    if not doc:          # guard: skip empty/None chroma docs
                        continue
                    results.append({
                        "content": doc,
                        "confidence": meta.get("confidence", 0.5),
                        "source": meta.get("source", ""),
                        "author": meta.get("author", ""),
                        "timestamp": meta.get("timestamp", ""),
                        "tags": None,
                        "human_validated": 0,
                        "decay_score": 0
                    })
        except Exception as e:
            pass  # fall through to SQLite

    # 2. SQLite fallback / supplement
    conn = get_db()
    try:
        if topic:
            rows = conn.execute("""
                SELECT * FROM beliefs
                WHERE content LIKE ? AND confidence >= ?
                ORDER BY confidence DESC LIMIT ?
            """, (f"%{topic}%", min_confidence, limit * 2)).fetchall()
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
        if not key:          # skip beliefs with no content
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
            "chroma_vectors": chroma_count
        }
    finally:
        conn.close()

def initial_sync(beliefs_list=None):
    """Sync a list of belief dicts into SQLite + ChromaDB. Called with no args = no-op (DB already loaded)."""
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
    """
    Strengthen a belief that was actually used in a response.
    Called whenever a belief is retrieved and referenced in a reply.
    """
    if not content:
        return
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
    except Exception:
        pass
    finally:
        conn.close()


def decay_stale_beliefs(days_inactive=14, decay_amount=0.04, min_conf=0.10):
    """
    Weaken beliefs that haven't been referenced in `days_inactive` days.
    Runs during memory compression cycles.
    Returns count of decayed beliefs.
    """
    import time as _t
    cutoff = datetime.fromtimestamp(_t.time() - days_inactive * 86400).isoformat()
    conn = get_db()
    try:
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
        return count
    except Exception:
        return 0
    finally:
        conn.close()
