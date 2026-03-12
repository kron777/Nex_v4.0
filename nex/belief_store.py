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
    return None  # disabled - too much RAM, SQLite-only mode
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        # Use sentence-transformers for embeddings (already installed)
        # Use lightweight default embeddings — saves ~1.5GB RAM vs sentence-transformers
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        ef = DefaultEmbeddingFunction()
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
    """)
    conn.commit()

# ── Add belief (SQLite + ChromaDB) ───────────────────────────────────────────
def add_belief(content, confidence=0.5, source=None, author=None,
               network_consensus=0.3, tags=None):
    if not content or len(content.strip()) < 10:
        return None
    content = content.strip()
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO beliefs
            (content, confidence, network_consensus, source, author, timestamp, last_referenced, tags)
            VALUES (?,?,?,?,?,?,?,?)
        """, (content, confidence, network_consensus, source, author, now, now,
              json.dumps(tags) if tags else None))
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
        key = r.get("content", "")[:80]
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
