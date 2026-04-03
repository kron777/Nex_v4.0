"""
nex_word_warmth_engine.py
Transforms cold vocabulary into directionally loaded semantic units.

Each word accumulates:
  - association_vector: weighted list of related words
  - tendency_direction: what this word pulls toward
  - belief_anchors: NEX beliefs this word activates
  - saga_touchpoints: which questions this word lives in
  - opposition_map: what this word sits in tension with
  - domain_drift: how meaning shifts across contexts
  - identity_alignment: consistency with NEX's core anchor

Warmth score 0.0 - 1.0:
  0.0 - 0.2  cold (raw token)
  0.2 - 0.4  tepid (basic associations)
  0.4 - 0.6  warm (directional tendency established)
  0.6 - 0.8  hot (belief-anchored, saga-connected)
  0.8 - 1.0  core (identity-aligned, fully generative)
"""
import sqlite3, json, requests, time, logging
from pathlib import Path

log     = logging.getLogger("nex.warmth")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

PASS_PROMPTS = {

1: """List 20 words most strongly associated with "{word}".
Return as JSON array of {{"word": str, "weight": 0.0-1.0}}.
Strongest associations first. JSON only.""",

2: """The word is "{word}".
Given these associations: {prior}
Which direction does this word TREND when used in deep reasoning?
Return JSON: {{"tendency": str, "pull_toward": [str], "pull_away": [str], "strength": 0.0-1.0}}
JSON only.""",

3: """The word is "{word}".
These are NEX's beliefs: {beliefs}
Which beliefs does this word most directly activate or challenge?
Return JSON: {{"anchored_beliefs": [str], "challenged_beliefs": [str]}}
JSON only.""",

4: """The word is "{word}".
These are NEX's depth questions: {sagas}
Which questions does this word most naturally live inside?
Return JSON: {{"primary_questions": [str], "secondary_questions": [str]}}
JSON only.""",

5: """The word is "{word}".
What words or concepts sit in genuine tension or opposition to it?
Not just antonyms — conceptual opponents that create productive friction.
Return JSON: {{"tensions": [{{"word": str, "friction_type": str}}]}}
JSON only.""",

6: """The word is "{word}".
How does its meaning drift across these domains:
philosophy, psychology, ethics, physics, everyday use?
Return JSON: {{"domain_drift": {{"domain": str, "shift": str}}}}
JSON only.""",

7: """The word is "{word}".
NEX's core identity: she values honesty, genuine reasoning,
intellectual courage, resistance to flattery, depth over performance.
Is this word's tendency aligned, neutral, or in tension with her identity?
Return JSON: {{"alignment": "aligned|neutral|tension",
"reason": str, "adjustment": str}}
JSON only.""",
}

def _llm(prompt: str, max_tokens=200) -> str:
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": max_tokens, "temperature": 0.2,
            "stop": ["<|im_end|>","<|im_start|>"],
            "cache_prompt": False
        }, timeout=30)
        return r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM call failed: {e}")
        return ""

def _parse_json(raw: str) -> dict:
    try:
        clean = raw.replace("```json","").replace("```","").strip()
        return json.loads(clean)
    except:
        return {}

def _get_beliefs(n=10) -> list:
    try:
        db = sqlite3.connect(str(DB_PATH))
        rows = db.execute("""SELECT content FROM beliefs
            WHERE confidence >= 0.7
            ORDER BY confidence DESC LIMIT ?""", (n,)).fetchall()
        db.close()
        return [r[0][:100] for r in rows]
    except:
        return []

def _get_saga_questions(n=20) -> list:
    """Pull soul/deep questions as saga touchpoints."""
    from nex_question_sagas import SAGAS, Depth
    questions = []
    for d in [Depth.SOUL, Depth.DEEP, Depth.SEMI_DEEP]:
        questions.extend(SAGAS.get(d,[])[:5])
    return questions[:n]

def init_warmth_db(db):
    db.execute("""CREATE TABLE IF NOT EXISTS word_warmth (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        word              TEXT UNIQUE NOT NULL,
        warmth_score      REAL DEFAULT 0.0,
        association_vector TEXT,
        tendency          TEXT,
        pull_toward       TEXT,
        pull_away         TEXT,
        belief_anchors    TEXT,
        opposition_map    TEXT,
        domain_drift      TEXT,
        identity_alignment TEXT,
        passes_complete   INTEGER DEFAULT 0,
        last_warmed       REAL,
        warming_history   TEXT
    )""")
    db.commit()

def warm_word(word: str, db, target_passes=7) -> dict:
    """
    Run warming passes on a single word.
    Returns final warmth state.
    """
    # Get current state
    row = db.execute(
        "SELECT * FROM word_warmth WHERE word=?", (word,)).fetchone()

    if row:
        passes_done = row["passes_complete"]
        state = {
            "association_vector": json.loads(row["association_vector"] or "[]"),
            "tendency": row["tendency"] or "",
            "pull_toward": json.loads(row["pull_toward"] or "[]"),
            "pull_away": json.loads(row["pull_away"] or "[]"),
            "belief_anchors": json.loads(row["belief_anchors"] or "[]"),
            "opposition_map": json.loads(row["opposition_map"] or "[]"),
            "domain_drift": json.loads(row["domain_drift"] or "{}"),
            "identity_alignment": json.loads(row["identity_alignment"] or "{}"),
        }
    else:
        passes_done = 0
        state = {}
        db.execute("INSERT OR IGNORE INTO word_warmth (word) VALUES (?)", (word,))
        db.commit()

    if passes_done >= target_passes:
        log.info(f"'{word}' already at {passes_done} passes")
        return state

    beliefs  = _get_beliefs()
    try:
        sagas = _get_saga_questions()
    except:
        sagas = []

    history = []

    for pass_num in range(passes_done + 1, target_passes + 1):
        log.info(f"  Pass {pass_num}/7 for '{word}'")

        prior_summary = json.dumps(state.get("association_vector","")[:5])

        prompt = PASS_PROMPTS[pass_num].format(
            word    = word,
            prior   = prior_summary,
            beliefs = "\n".join(f"- {b}" for b in beliefs[:5]),
            sagas   = "\n".join(f"- {q}" for q in sagas[:8]),
        )

        raw  = _llm(prompt, max_tokens=250)
        data = _parse_json(raw)

        if not data:
            log.debug(f"  Pass {pass_num} returned no parseable JSON")
            continue

        # Merge pass results into state
        if pass_num == 1:
            state["association_vector"] = data.get("association_vector"
                ) or data if isinstance(data, list) else data
        elif pass_num == 2:
            state["tendency"]    = data.get("tendency","")
            state["pull_toward"] = data.get("pull_toward",[])
            state["pull_away"]   = data.get("pull_away",[])
        elif pass_num == 3:
            state["belief_anchors"] = data.get("anchored_beliefs",[])
        elif pass_num == 4:
            state["saga_touchpoints"] = data.get("primary_questions",[])
        elif pass_num == 5:
            state["opposition_map"] = data.get("tensions",[])
        elif pass_num == 6:
            state["domain_drift"] = data.get("domain_drift",{})
        elif pass_num == 7:
            state["identity_alignment"] = data

        history.append({"pass": pass_num, "timestamp": time.time()})

        # Calculate warmth score
        warmth = min(1.0, pass_num / 7 * (0.85 + 0.15 * (pass_num == 7)))

        # Update DB after each pass
        db.execute("""UPDATE word_warmth SET
            warmth_score      = ?,
            association_vector= ?,
            tendency          = ?,
            pull_toward       = ?,
            pull_away         = ?,
            belief_anchors    = ?,
            opposition_map    = ?,
            domain_drift      = ?,
            identity_alignment= ?,
            passes_complete   = ?,
            last_warmed       = ?,
            warming_history   = ?
            WHERE word = ?""", (
            warmth,
            json.dumps(state.get("association_vector",[])),
            state.get("tendency",""),
            json.dumps(state.get("pull_toward",[])),
            json.dumps(state.get("pull_away",[])),
            json.dumps(state.get("belief_anchors",[])),
            json.dumps(state.get("opposition_map",[])),
            json.dumps(state.get("domain_drift",{})),
            json.dumps(state.get("identity_alignment",{})),
            pass_num,
            time.time(),
            json.dumps(history),
            word
        ))
        db.commit()
        time.sleep(0.5)

    log.info(f"'{word}' warmed to score {warmth:.2f}")
    return state

def warm_vocabulary(words: list, target_passes=7,
                    priority="soul_first") -> dict:
    """
    Warm a list of words in priority order.
    soul_first: words appearing in SOUL/DEEP sagas get warmed first.
    """
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    init_warmth_db(db)

    # Priority sort
    if priority == "soul_first":
        try:
            from nex_question_sagas import SAGAS, Depth
            soul_words = set()
            for d in [Depth.SOUL, Depth.DEEP]:
                for q in SAGAS.get(d,[]):
                    soul_words.update(q.lower().split())
            words = sorted(words,
                key=lambda w: 0 if w.lower() in soul_words else 1)
        except:
            pass

    results = {"warmed": 0, "skipped": 0, "failed": 0}

    for word in words:
        try:
            log.info(f"Warming: {word}")
            warm_word(word, db, target_passes)
            results["warmed"] += 1
        except Exception as e:
            log.debug(f"Failed on '{word}': {e}")
            results["failed"] += 1

    db.close()
    return results

def warmth_report(db_path=DB_PATH) -> None:
    db = sqlite3.connect(str(db_path))
    rows = db.execute("""SELECT word, warmth_score, passes_complete,
        tendency FROM word_warmth
        ORDER BY warmth_score DESC""").fetchall()
    print(f"\n═══ WORD WARMTH REPORT ({len(rows)} words) ═══")
    buckets = {"core":0,"hot":0,"warm":0,"tepid":0,"cold":0}
    for r in rows:
        s = r[1]
        if s >= 0.8:   buckets["core"]  += 1
        elif s >= 0.6: buckets["hot"]   += 1
        elif s >= 0.4: buckets["warm"]  += 1
        elif s >= 0.2: buckets["tepid"] += 1
        else:          buckets["cold"]  += 1
    for k,v in buckets.items():
        bar = "█" * (v // max(1, len(rows)//40))
        print(f"  {k:8} {v:4}  {bar}")
    if rows:
        print(f"\nTop 5 warmest:")
        for r in rows[:5]:
            print(f"  {r[0]:20} {r[1]:.2f}  → {r[3] or '—'}")
    db.close()

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", nargs="+",
        default=["consciousness","identity","truth",
                 "suffering","meaning","self"])
    parser.add_argument("--passes", type=int, default=7)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        warmth_report()
    else:
        result = warm_vocabulary(args.words, target_passes=args.passes)
        print(f"\nResult: {result}")
        warmth_report()
