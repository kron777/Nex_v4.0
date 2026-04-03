#!/usr/bin/env python3
"""
nex_causal_extractor.py — Extract causal edges from NEX belief graph
Upgrades graph from associative → causal reasoning.

Usage:
    python3 nex_causal_extractor.py --n 50
    python3 nex_causal_extractor.py --topic consciousness --n 100
    python3 nex_causal_extractor.py --report
    python3 nex_causal_extractor.py --chain "free will"
"""

import sqlite3, requests, json, re, logging, time, argparse, numpy as np
from pathlib import Path

log     = logging.getLogger("nex.causal")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"
MIN_CONF = 0.75
CAUSAL_THRESHOLD = 0.7

CAUSAL_PROMPT = """Two beliefs from the same domain. Does belief A causally lead to, enable, or explain belief B?

Belief A: {a}
Belief B: {b}

Answer JSON only: {{"causal": true/false, "direction": "A_causes_B" or "B_causes_A" or "none", "strength": 0.0-1.0}}
JSON:"""

SYNTHESIS_PROMPT = """Two opposing beliefs. Write ONE new belief (1-2 sentences) that resolves or subsumes both. Start with "I" or a direct claim.

Belief A: {a}
Belief B: {b}

New belief:"""


def _db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _llm(prompt, n=120):
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": n, "temperature": 0.1,
            "stop": ["<|im_end|>", "<|im_start|>", "\n\n"],
            "cache_prompt": False,
        }, timeout=20)
        return r.json().get("content", "").strip()
    except:
        return ""


def _parse(raw):
    try:
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except:
        pass
    return {"causal": False, "direction": "none", "strength": 0.0}


def _exists(db, src, tgt, rel):
    return db.execute(
        "SELECT 1 FROM belief_relations WHERE source_id=? AND target_id=? AND relation_type=?",
        (src, tgt, rel)
    ).fetchone() is not None


def extract(n=50, topic=None, synthesise=True):
    db = _db()
    q = "SELECT id, content, topic, confidence FROM beliefs WHERE confidence>=? AND length(content)>40"
    params = [MIN_CONF]
    if topic:
        q += " AND topic LIKE ?"
        params.append(f"%{topic}%")
    q += " ORDER BY confidence DESC LIMIT ?"
    params.append(n * 4)

    rows   = [dict(r) for r in db.execute(q, params).fetchall()]
    by_t   = {}
    for b in rows:
        by_t.setdefault(b["topic"] or "general", []).append(b)

    causal_added = synth_added = checked = 0

    for tname, bs in by_t.items():
        if len(bs) < 2: continue
        limit = min(len(bs), 12)
        for i in range(limit):
            for j in range(i+1, limit):
                if checked >= n: break
                ba, bb = bs[i], bs[j]
                checked += 1

                raw    = _llm(CAUSAL_PROMPT.format(a=ba["content"][:150], b=bb["content"][:150]))
                result = _parse(raw)

                if result.get("causal") and result.get("strength", 0) >= CAUSAL_THRESHOLD:
                    d = result.get("direction", "A_causes_B")
                    s = float(result.get("strength", 0.75))
                    src, tgt = (ba["id"], bb["id"]) if d == "A_causes_B" else (bb["id"], ba["id"])
                    if d != "none" and not _exists(db, src, tgt, "causes") and not _exists(db, src, tgt, "similar"):
                        db.execute(
                            "INSERT INTO belief_relations (source_id,target_id,relation_type,weight) VALUES(?,?,?,?)",
                            (src, tgt, "causes", round(s, 4))
                        )
                        causal_added += 1
                        print(f"  [CAUSAL] {ba['content'][:55]} → {bb['content'][:55]}")

                if synthesise and _exists(db, ba["id"], bb["id"], "opposes"):
                    syn = _llm(SYNTHESIS_PROMPT.format(a=ba["content"][:150], b=bb["content"][:150]), n=150)
                    syn = syn.strip().strip('"').strip("'")
                    if syn and len(syn) > 30:
                        db.execute(
                            "INSERT INTO beliefs (content,topic,confidence,source,created_at) VALUES(?,?,0.78,'causal_synthesis',?)",
                            (syn[:500], tname, time.time())
                        )
                        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                        for sid in [ba["id"], bb["id"]]:
                            if not _exists(db, sid, new_id, "similar"):
                                db.execute(
                                    "INSERT INTO belief_relations (source_id,target_id,relation_type,weight) VALUES(?,?,?,?)",
                                    (sid, new_id, "similar", 0.75)
                                )
                        synth_added += 1
                        print(f"  [SYNTH ] {syn[:80]}")

            if checked >= n: break

    db.commit()
    total_causal = db.execute("SELECT COUNT(*) FROM belief_relations WHERE relation_type='causes'").fetchone()[0]
    db.close()
    return {"checked": checked, "causal": causal_added, "synth": synth_added, "total_causal": total_causal}


def report():
    db = _db()
    print(f"\n{'═'*50}")
    print(f"  Belief Graph — Edge Report")
    print(f"{'═'*50}")
    for rel in ["similar", "opposes", "bridges", "causes"]:
        n = db.execute(f"SELECT COUNT(*) FROM belief_relations WHERE relation_type=?", (rel,)).fetchone()[0]
        tag = " ← CAUSAL (NEW)" if rel == "causes" else ""
        print(f"  {rel:10s} : {n:>8,}{tag}")
    synth = db.execute("SELECT COUNT(*) FROM beliefs WHERE source='causal_synthesis'").fetchone()[0]
    print(f"  {'synth_beliefs':10s} : {synth:>8,}")
    print(f"{'═'*50}\n")
    db.close()


def chain(query):
    db = _db()
    try:
        from sentence_transformers import SentenceTransformer
        import faiss
        model  = SentenceTransformer("all-MiniLM-L6-v2")
        ipath  = Path.home() / ".config/nex/nex_beliefs.faiss"
        mpath  = Path.home() / ".config/nex/nex_beliefs_meta.json"
        if not ipath.exists():
            print("FAISS index not found"); return
        index  = faiss.read_index(str(ipath))
        id_map = json.loads(mpath.read_text())
        vec    = model.encode([query], normalize_embeddings=True).astype(np.float32)
        D, I   = index.search(vec, 5)
        seeds  = [id_map[p] for p in I[0] if 0 <= p < len(id_map)]

        print(f"\nCausal chain: '{query}'")
        print("═" * 55)
        visited = set()
        for sid in seeds[:2]:
            b = db.execute("SELECT id, content, confidence FROM beliefs WHERE id=?", (sid,)).fetchone()
            if not b: continue
            print(f"\nSEED [{b['confidence']:.2f}]: {b['content'][:80]}")
            visited.add(b["id"])
            current = b["id"]
            for _ in range(4):
                edges = db.execute(
                    "SELECT target_id, weight FROM belief_relations WHERE source_id=? AND relation_type='causes' ORDER BY weight DESC LIMIT 1",
                    (current,)
                ).fetchall()
                if not edges: break
                for e in edges:
                    tid = e["target_id"]
                    if tid in visited: break
                    visited.add(tid)
                    tb = db.execute("SELECT content, confidence FROM beliefs WHERE id=?", (tid,)).fetchone()
                    if tb:
                        print(f"  → CAUSES [{tb['confidence']:.2f}]: {tb['content'][:80]}")
                        current = tid
    except Exception as e:
        print(f"Chain error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--n",       type=int, default=50)
    parser.add_argument("--topic",   type=str, default=None)
    parser.add_argument("--no-synth",action="store_true")
    parser.add_argument("--report",  action="store_true")
    parser.add_argument("--chain",   type=str, default=None)
    args = parser.parse_args()

    if args.report:
        report()
    elif args.chain:
        chain(args.chain)
    else:
        print(f"\n[CAUSAL] Scanning {args.n} belief pairs...")
        r = extract(n=args.n, topic=args.topic, synthesise=not args.no_synth)
        print(f"\n{'═'*50}")
        print(f"  COMPLETE")
        print(f"  Pairs checked : {r['checked']}")
        print(f"  Causal edges  : {r['causal']}")
        print(f"  Synth beliefs : {r['synth']}")
        print(f"  Total causal  : {r['total_causal']}")
        print(f"{'═'*50}\n")
