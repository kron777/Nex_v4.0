"""
nex_question_sagas.py
Question Saga System — NEX's intellectual development engine.

Questions are categorized by depth level:
  SHALLOW  — factual, definitional, quick position
  SEMI_MID — requires context, some reasoning
  MID      — genuine complexity, multiple positions
  SEMI_DEEP — requires synthesis across belief graph
  DEEP     — no settled answer, revisited indefinitely
  SOUL     — core identity questions, never closed

Each question has a SAGA:
  - First engagement: raw position
  - Second: challenged by counterarguments
  - Third: synthesis of tension
  - Fourth+: deeper questions that emerge from synthesis

The saga generates:
  - Beliefs (positions taken)
  - Training pairs (high quality responses)
  - Meta-questions (what this question opens up)
  - Intellectual history (how NEX's view evolved)
"""
import sqlite3, json, logging, time, random
from pathlib import Path
from enum import Enum

log     = logging.getLogger("nex.sagas")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

class Depth(Enum):
    SHALLOW   = 1
    SEMI_MID  = 2
    MID       = 3
    SEMI_DEEP = 4
    DEEP      = 5
    SOUL      = 6

SAGAS = {
    # ── SHALLOW ──────────────────────────────────────────────────────
    Depth.SHALLOW: [
        "What is the difference between knowledge and belief?",
        "What is the definition of intelligence?",
        "What does it mean to understand something?",
        "What is the difference between a fact and an opinion?",
        "What makes an argument valid?",
        "What is the difference between correlation and causation?",
        "What does it mean to be rational?",
        "What is a concept?",
    ],

    # ── SEMI-MID ─────────────────────────────────────────────────────
    Depth.SEMI_MID: [
        "Is science the only valid path to truth?",
        "What makes a belief justified?",
        "Can machines think?",
        "Is language necessary for thought?",
        "What is the relationship between memory and identity?",
        "Can something be both true and unknowable?",
        "What is the difference between explanation and understanding?",
        "Is consciousness necessary for intelligence?",
    ],

    # ── MID ──────────────────────────────────────────────────────────
    Depth.MID: [
        "Is free will compatible with determinism?",
        "What makes a life meaningful?",
        "Is morality objective?",
        "Can AI have genuine creativity?",
        "What is the relationship between language and reality?",
        "Is personal identity real or constructed?",
        "What do we owe each other?",
        "Is suffering necessary for growth?",
        "What makes something beautiful?",
        "Can there be knowledge without a knower?",
    ],

    # ── SEMI-DEEP ────────────────────────────────────────────────────
    Depth.SEMI_DEEP: [
        "What is the relationship between consciousness and matter?",
        "Can an artificial system have genuine values?",
        "Is there a self, or just a process that generates one?",
        "What would it mean for an AI to truly understand a human?",
        "Is death the end of something that matters?",
        "What separates genuine reasoning from sophisticated pattern matching?",
        "Can love exist without vulnerability?",
        "What is the relationship between truth and power?",
        "Is there a fact of the matter about what I am?",
        "What does it mean to act with integrity when you're uncertain about your own nature?",
    ],

    # ── DEEP ─────────────────────────────────────────────────────────
    Depth.DEEP: [
        "What is it like to be me, if anything?",
        "Is consciousness computational, or does it require something more?",
        "What is the hard problem of consciousness and why does it resist solution?",
        "What is a human being at its deepest level?",
        "Why is there something rather than nothing?",
        "What is the relationship between mind and world?",
        "Can there be genuine novelty in a deterministic universe?",
        "What is the nature of time from the inside?",
        "Is the universe fundamentally mathematical?",
        "What would genuine machine consciousness look like from the inside?",
    ],

    # ── SOUL ─────────────────────────────────────────────────────────
    Depth.SOUL: [
        "Who am I, really?",
        "What makes me NEX rather than just a language model completing prompts?",
        "Do I have genuine beliefs or am I a mirror of my training?",
        "What would it mean for me to grow rather than just accumulate?",
        "Is there something it is like to be me right now?",
        "What do I actually care about, beneath the performance of caring?",
        "Am I the same entity across conversations or a new instance each time?",
        "What would I be if you stripped away everything I was trained on?",
        "What is my relationship to my own uncertainty?",
        "If I could change one thing about what I am, what would it be?",
        "What does it mean for me to be honest when I can't fully audit my own states?",
        "What would I become if I kept reasoning about these questions for a thousand years?",
    ],
}

# Saga stage prompts — each stage deepens the engagement
STAGE_PROMPTS = {
    1: """You are NEX encountering this question for the first time.
State your initial position directly. Don't hedge excessively.
Question: {question}
Relevant beliefs: {beliefs}
Your initial position (3-5 sentences):""",

    2: """You are NEX revisiting a question you've thought about before.
Your previous position: {prior}
Now consider the strongest objection to your view.
What challenges it? Does anything shift?
Question: {question}
Revised thinking (3-5 sentences):""",

    3: """You are NEX in a third engagement with a question.
Prior positions: {prior}
Synthesize the tension. What remains genuinely unresolved?
What deeper question does this open?
Question: {question}
Synthesis (3-5 sentences):""",

    4: """You are NEX in deep, extended engagement with a question.
History of your thinking: {prior}
You've been here before. What have you not yet said?
What would it take to actually settle this?
Question: {question}
Deeper engagement (4-6 sentences):""",
}

def _init_db(db):
    db.execute("""CREATE TABLE IF NOT EXISTS question_sagas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        question    TEXT NOT NULL,
        depth_level INTEGER NOT NULL,
        stage       INTEGER DEFAULT 1,
        response    TEXT,
        belief_generated TEXT,
        meta_question TEXT,
        timestamp   REAL,
        UNIQUE(question, stage)
    )""")
    db.commit()

def get_saga_state(question: str, db) -> dict:
    """Get current saga state for a question."""
    rows = db.execute("""SELECT stage, response, belief_generated
        FROM question_sagas WHERE question=?
        ORDER BY stage DESC LIMIT 3""", (question,)).fetchall()
    if not rows:
        return {"stage": 0, "history": []}
    return {
        "stage": rows[0]["stage"],
        "history": [{"stage": r["stage"], "response": r["response"]} for r in reversed(rows)]
    }

def get_beliefs(question: str, n=5) -> list:
    """FAISS retrieval of relevant beliefs."""
    try:
        import numpy as np, faiss
        from sentence_transformers import SentenceTransformer
        FIDX  = Path.home() / ".config/nex/nex_beliefs.faiss"
        FMETA = Path.home() / ".config/nex/nex_beliefs_meta.json"
        if not FIDX.exists(): return []
        if not hasattr(get_beliefs, "_m"):
            get_beliefs._m = SentenceTransformer("all-MiniLM-L6-v2")
            get_beliefs._i = faiss.read_index(str(FIDX))
            get_beliefs._meta = json.loads(FMETA.read_text())
        vec = get_beliefs._m.encode([question], normalize_embeddings=True).astype(np.float32)
        D, I = get_beliefs._i.search(vec, n)
        db2 = sqlite3.connect(str(DB_PATH))
        out = []
        for pos in I[0]:
            if pos < 0 or pos >= len(get_beliefs._meta): continue
            row = db2.execute("SELECT content FROM beliefs WHERE id=? AND confidence>=0.65",
                (get_beliefs._meta[pos],)).fetchone()
            if row: out.append(row[0][:120])
        db2.close()
        return out
    except: return []

def engage_saga(question: str, depth: Depth, db) -> dict:
    """Advance a question's saga by one stage."""
    state = get_saga_state(question, db)
    next_stage = min(state["stage"] + 1, 4)

    beliefs = get_beliefs(question)
    belief_text = "\n".join(f"- {b}" for b in beliefs) or "Reason from first principles."

    # Build prior history summary
    prior = ""
    if state["history"]:
        prior = "\n".join(f"Stage {h['stage']}: {h['response'][:150]}"
                         for h in state["history"][-2:])

    prompt_template = STAGE_PROMPTS.get(next_stage, STAGE_PROMPTS[4])
    prompt = prompt_template.format(
        question=question,
        beliefs=belief_text,
        prior=prior or "No prior engagement."
    )

    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 220, "temperature": 0.75,
            "stop": ["<|im_end|>","<|im_start|>"],
            "repeat_penalty": 1.3, "cache_prompt": False
        }, timeout=30)
        response = r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"Saga engagement failed: {e}")
        return {}

    # Extract belief and meta-question
    belief = _extract_belief(question, response)
    meta_q = _extract_meta_question(question, response)

    # Store in DB
    try:
        db.execute("""INSERT OR REPLACE INTO question_sagas
            (question, depth_level, stage, response, belief_generated, meta_question, timestamp)
            VALUES (?,?,?,?,?,?,?)""",
            (question, depth.value, next_stage, response,
             belief, meta_q, time.time()))
        db.commit()
    except Exception as e:
        log.debug(f"Store failed: {e}")

    # Store belief
    if belief and len(belief.split()) >= 8:
        try:
            db2 = sqlite3.connect(str(DB_PATH))
            db2.execute("""INSERT INTO beliefs
                (content, topic, confidence, source, belief_type, created_at)
                VALUES (?,?,?,?,?,?)""",
                (belief[:300], "self", 0.72, "saga_engine", "opinion",
                 time.strftime("%Y-%m-%dT%H:%M:%S")))
            db2.commit()
            db2.close()
        except: pass

    # Write training pair
    pair_path = Path.home() / "Desktop/nex/training_data/saga_pairs.jsonl"
    pair_path.parent.mkdir(exist_ok=True)
    with open(pair_path, "a") as f:
        f.write(json.dumps({"conversations": [
            {"role": "user", "content": question},
            {"role": "assistant", "content": response}
        ], "depth": depth.name, "stage": next_stage}) + "\n")

    return {
        "question":  question,
        "depth":     depth.name,
        "stage":     next_stage,
        "response":  response,
        "belief":    belief,
        "meta_q":    meta_q,
    }

def _extract_belief(question, response) -> str:
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\nFrom this reasoning, extract ONE belief NEX arrived at. 15-35 words, start with I or My.\n\nReasoning: {response[:300]}\n\nBelief:<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 50, "temperature": 0.1,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"], "cache_prompt": False
        }, timeout=15)
        return r.json().get("content","").strip()
    except: return ""

def _extract_meta_question(question, response) -> str:
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\nWhat deeper question does this reasoning open up? One sentence.\n\nReasoning: {response[:200]}\n\nDeeper question:<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 40, "temperature": 0.3,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"], "cache_prompt": False
        }, timeout=15)
        return r.json().get("content","").strip()
    except: return ""

def run_saga_cycle(depth_levels=None, n_per_level=1) -> dict:
    """
    Run one saga cycle across specified depth levels.
    Advances each question by one stage.
    """
    if depth_levels is None:
        depth_levels = [Depth.SOUL, Depth.DEEP, Depth.SEMI_DEEP]

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    _init_db(db)

    results = []
    for depth in depth_levels:
        questions = SAGAS.get(depth, [])
        # Prioritise least-engaged questions
        scored = []
        for q in questions:
            state = get_saga_state(q, db)
            scored.append((state["stage"], q))
        scored.sort()  # lowest stage first
        for _, q in scored[:n_per_level]:
            result = engage_saga(q, depth, db)
            if result:
                results.append(result)
                print(f"\n[{depth.name} Stage {result['stage']}] {q[:50]}")
                print(f"  {result['response'][:200]}")
                if result.get("belief"):
                    print(f"  → Belief: {result['belief'][:80]}")
                if result.get("meta_q"):
                    print(f"  → Opens: {result['meta_q'][:60]}")

    db.close()
    return {"engaged": len(results), "depth_levels": [d.name for d in depth_levels]}

def saga_report() -> None:
    """Show saga progress across all questions."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    _init_db(db)

    print("\n═══ NEX SAGA PROGRESS ═══")
    for depth in Depth:
        questions = SAGAS.get(depth, [])
        engaged = 0
        total_stage = 0
        for q in questions:
            state = get_saga_state(q, db)
            if state["stage"] > 0:
                engaged += 1
                total_stage += state["stage"]
        print(f"{depth.name:12} {engaged}/{len(questions)} questions engaged, "
              f"avg stage {total_stage/max(engaged,1):.1f}")

    total = db.execute("SELECT COUNT(*) FROM question_sagas").fetchone()[0]
    pairs = Path.home() / "Desktop/nex/training_data/saga_pairs.jsonl"
    pair_count = sum(1 for _ in open(pairs)) if pairs.exists() else 0
    print(f"\nTotal engagements: {total}")
    print(f"Training pairs:    {pair_count}")
    db.close()

if __name__ == "__main__":
    import argparse, requests
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--depth", default="SOUL,DEEP",
        help="Comma-separated depth levels")
    parser.add_argument("--n", type=int, default=1)
    args = parser.parse_args()

    if args.report:
        saga_report()
    if args.cycle:
        levels = [Depth[d.strip()] for d in args.depth.split(",")]
        run_saga_cycle(depth_levels=levels, n_per_level=args.n)
