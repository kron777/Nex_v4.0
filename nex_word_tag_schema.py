"""
nex_word_tag_schema.py
Complete word tag schema for NEX's warmed vocabulary system.
"""
import sqlite3, json, requests, time, logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional

log     = logging.getLogger("nex.tags")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

@dataclass
class WordTag:
    word: str
    # TIER 1 — CORE
    w:  float = 0.0
    t:  float = 0.0
    d:  int   = 1
    a:  float = 0.0
    c:  float = 0.0
    f:  int   = 1
    # TIER 2 — STRUCTURAL
    b:  int   = 0
    s:  int   = 0
    g:  int   = 0
    r:  int   = 0
    e:  float = 0.0
    # TIER 3 — COGNITIVE
    x:  Optional[float] = None
    p:  Optional[float] = None
    m:  Optional[float] = None
    q:  Optional[float] = None
    n:  Optional[float] = None
    # TIER 4 — TEMPORAL
    age:   float = 0.0
    delta: float = 0.0
    drift: float = 0.0
    vel:   float = 0.0
    # TIER 5 — RELATIONAL
    op:  Optional[float] = None
    syn: Optional[int]   = None
    dom: Optional[float] = None
    ctx: Optional[float] = None

    def is_warm(self):  return self.w >= 0.4 and self.f == 0
    def is_hot(self):   return self.w >= 0.6 and self.f == 0
    def is_core(self):  return self.w >= 0.8 and self.f == 0
    def needs_priority_warming(self): return self.g > 10 and self.w < 0.4

    def resolution_cost(self):
        if self.is_core():  return "negligible"
        if self.is_hot():   return "low"
        if self.is_warm():  return "medium"
        return "high"

    def summary(self):
        depth_names = {1:"shallow",2:"semi_mid",3:"mid",
                       4:"semi_deep",5:"deep",6:"soul"}
        return (f"[{self.word}] "
                f"w={self.w:.2f} "
                f"depth={depth_names.get(self.d,'?')} "
                f"align={self.a:+.2f} "
                f"conf={self.c:.2f} "
                f"gaps={self.g} "
                f"search={'yes' if self.f else 'no'} "
                f"cost={self.resolution_cost()}")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS word_tags (
    word TEXT PRIMARY KEY,
    w REAL DEFAULT 0.0, t REAL DEFAULT 0.0,
    d INTEGER DEFAULT 1, a REAL DEFAULT 0.0,
    c REAL DEFAULT 0.0, f INTEGER DEFAULT 1,
    b INTEGER DEFAULT 0, s INTEGER DEFAULT 0,
    g INTEGER DEFAULT 0, r INTEGER DEFAULT 0,
    e REAL DEFAULT 0.0,
    x REAL, p REAL, m REAL, q REAL, n REAL,
    age REAL DEFAULT 0.0, delta REAL DEFAULT 0.0,
    drift REAL DEFAULT 0.0, vel REAL DEFAULT 0.0,
    op REAL, syn INTEGER, dom REAL, ctx REAL,
    association_vector TEXT, pull_toward TEXT,
    pull_away TEXT, opposition_map TEXT,
    domain_drift_map TEXT, warming_history TEXT,
    last_updated REAL
)
"""

TAG_PASS_PROMPTS = {
1: """Analyse the word "{word}" for semantic associations.
Return ONLY valid JSON:
{{"associations": [{{"word": "str", "weight": 0.5}}],
  "tendency_strength": 0.7,
  "depth_level": 4,
  "emotional_valence": 0.2}}
depth_level: 1=factual 2=contextual 3=complex 4=philosophical 5=existential 6=identity-core
emotional_valence: -1.0=tension to +1.0=resolution""",

2: """The word "{word}" has associations: {assoc}
Return ONLY valid JSON:
{{"pull_toward": ["concept1","concept2"],
  "pull_away": ["concept3"],
  "polarity_stability": 0.7,
  "context_sensitivity": 0.5,
  "domain_specificity": 0.4}}""",

3: """The word "{word}".
NEX beliefs: {beliefs}
Return ONLY valid JSON:
{{"belief_density": 3,
  "anchored_beliefs": ["belief1"],
  "question_generative": 0.8,
  "complexity_load": 0.7}}""",

4: """The word "{word}".
NEX saga questions: {sagas}
Return ONLY valid JSON:
{{"saga_presence": 4,
  "primary_questions": ["question1"],
  "metaphor_density": 0.4,
  "network_centrality": 0.6}}""",

5: """The word "{word}".
Conceptual tensions and oppositions.
Return ONLY valid JSON:
{{"opposition_strength": 0.6,
  "tensions": [{{"word": "materialism", "friction_type": "ontological", "strength": 0.8}}],
  "synergy_count": 5,
  "synergies": ["awareness","qualia"]}}""",

6: """The word "{word}".
Meaning across domains: philosophy, psychology, ethics, physics, everyday.
Return ONLY valid JSON:
{{"domain_drift": [{{"domain": "philosophy", "shift": "hard problem", "magnitude": 0.9}}],
  "domain_specificity": 0.3}}""",

7: """The word "{word}".
NEX identity: values honesty, genuine reasoning, intellectual courage,
resistance to flattery, depth over performance, authentic uncertainty.
Return ONLY valid JSON:
{{"anchor_alignment": 0.8,
  "alignment_type": "aligned",
  "reason": "central to NEX identity",
  "identity_notes": "appears in core saga questions"}}"""
}

def init_db(db):
    db.executescript(SCHEMA_SQL)
    db.commit()

def _llm(prompt: str, max_tokens: int = 250) -> str:
    try:
        r = requests.post(API, json={
            "prompt": (f"<|im_start|>system\nReturn only valid JSON. "
                      f"No prose, no markdown.<|im_end|>\n"
                      f"<|im_start|>user\n{prompt}<|im_end|>\n"
                      f"<|im_start|>assistant\n"),
            "n_predict": max_tokens, "temperature": 0.15,
            "stop": ["<|im_end|>","<|im_start|>"],
            "cache_prompt": False
        }, timeout=30)
        return r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM failed: {e}")
        return ""

def _parse(raw: str) -> dict:
    try:
        clean = raw.replace("```json","").replace("```","").strip()
        return json.loads(clean)
    except:
        return {}

def _clamp(v, lo, hi):
    if v is None: return lo
    return max(lo, min(hi, float(v)))

def _get_beliefs(n=8) -> list:
    try:
        db = sqlite3.connect(str(DB_PATH))
        rows = db.execute(
            "SELECT content FROM beliefs WHERE confidence>=0.7 "
            "ORDER BY confidence DESC LIMIT ?", (n,)).fetchall()
        db.close()
        return [r[0][:100] for r in rows]
    except:
        return []

def _get_sagas(n=12) -> list:
    try:
        import sys
        sys.path.insert(0, str(Path.home() / "Desktop/nex"))
        from nex_question_sagas import SAGAS, Depth
        out = []
        for dep in [Depth.SOUL, Depth.DEEP, Depth.SEMI_DEEP]:
            out.extend(SAGAS.get(dep,[])[:4])
        return out[:n]
    except:
        return []

def _write_tag_to_db(tag, db, assoc, pull_toward,
                     pull_away, opp_map, domain_map, history):
    db.execute("""INSERT OR REPLACE INTO word_tags (
        word, w, t, d, a, c, f,
        b, s, g, r, e,
        x, p, m, q, n,
        age, delta, drift, vel,
        op, syn, dom, ctx,
        association_vector, pull_toward, pull_away,
        opposition_map, domain_drift_map,
        warming_history, last_updated
    ) VALUES (
        :word,:w,:t,:d,:a,:c,:f,
        :b,:s,:g,:r,:e,
        :x,:p,:m,:q,:n,
        :age,:delta,:drift,:vel,
        :op,:syn,:dom,:ctx,
        :av,:pt,:pa,:om,:dm,
        :wh,:lu
    )""", {
        "word":tag.word,"w":tag.w,"t":tag.t,"d":tag.d,
        "a":tag.a,"c":tag.c,"f":tag.f,
        "b":tag.b,"s":tag.s,"g":tag.g,"r":tag.r,"e":tag.e,
        "x":tag.x,"p":tag.p,"m":tag.m,"q":tag.q,"n":tag.n,
        "age":tag.age,"delta":tag.delta,
        "drift":tag.drift,"vel":tag.vel,
        "op":tag.op,"syn":tag.syn,"dom":tag.dom,"ctx":tag.ctx,
        "av":assoc,"pt":pull_toward,"pa":pull_away,
        "om":opp_map,"dm":domain_map,
        "wh":json.dumps(history),"lu":time.time()
    })
    db.commit()

def write_tag(word: str, db, target_passes: int = 7,
              force: bool = False) -> WordTag:
    row = db.execute(
        "SELECT * FROM word_tags WHERE word=?",
        (word,)).fetchone()

    if row:
        history = json.loads(row["warming_history"] or "[]")
        passes_done = len(history)
        tag = WordTag(
            word=word,
            w=row["w"] or 0.0, t=row["t"] or 0.0,
            d=row["d"] or 1,   a=row["a"] or 0.0,
            c=row["c"] or 0.0, f=row["f"] if row["f"] is not None else 1,
            b=row["b"] or 0,   s=row["s"] or 0,
            g=row["g"] or 0,   r=row["r"] or 0,
            e=row["e"] or 0.0,
            x=row["x"], p=row["p"], m=row["m"],
            q=row["q"], n=row["n"],
            age=row["age"] or time.time(),
            delta=row["delta"] or 0.0,
            drift=row["drift"] or 0.0,
            vel=row["vel"] or 0.0,
            op=row["op"], syn=row["syn"],
            dom=row["dom"], ctx=row["ctx"],
        )
        assoc      = row["association_vector"] or "[]"
        pull_toward = row["pull_toward"] or "[]"
        pull_away  = row["pull_away"] or "[]"
        opp_map    = row["opposition_map"] or "[]"
        domain_map = row["domain_drift_map"] or "{}"
    else:
        tag = WordTag(word=word, age=time.time())
        history = []
        passes_done = 0
        assoc = pull_toward = pull_away = "[]"
        opp_map = "[]"
        domain_map = "{}"
        db.execute(
            "INSERT OR IGNORE INTO word_tags (word, age) VALUES (?,?)",
            (word, time.time()))
        db.commit()

    if not force and passes_done >= target_passes:
        log.info(f"'{word}' already at {passes_done} passes")
        return tag

    beliefs = _get_beliefs()
    sagas   = _get_sagas()
    start_w = tag.w

    for pass_num in range(passes_done + 1, target_passes + 1):
        log.info(f"  [{word}] Pass {pass_num}/7")

        prompt = TAG_PASS_PROMPTS[pass_num].format(
            word    = word,
            assoc   = assoc[:200],
            beliefs = "\n".join(f"- {b}" for b in beliefs[:5]),
            sagas   = "\n".join(f"- {q}" for q in sagas[:6]),
        )

        data = _parse(_llm(prompt))
        if not data:
            log.debug(f"  Pass {pass_num} empty")
            # Still advance with defaults
            data = {}

        if pass_num == 1:
            raw = data.get("associations", [])
            assoc = json.dumps(raw if isinstance(raw, list) else [])
            tag.t = _clamp(data.get("tendency_strength", 0.5), 0, 1)
            tag.d = int(_clamp(data.get("depth_level", 3), 1, 6))
            tag.e = _clamp(data.get("emotional_valence", 0.0), -1, 1)
        elif pass_num == 2:
            pull_toward = json.dumps(data.get("pull_toward", []))
            pull_away   = json.dumps(data.get("pull_away", []))
            tag.p  = _clamp(data.get("polarity_stability", 0.5), 0, 1)
            tag.ctx= _clamp(data.get("context_sensitivity", 0.5), 0, 1)
            tag.dom= _clamp(data.get("domain_specificity", 0.5), 0, 1)
        elif pass_num == 3:
            tag.b = int(_clamp(data.get("belief_density", 0), 0, 99))
            tag.q = _clamp(data.get("question_generative", 0.5), 0, 1)
            tag.x = _clamp(data.get("complexity_load", 0.5), 0, 1)
        elif pass_num == 4:
            tag.s = int(_clamp(data.get("saga_presence", 0), 0, 6))
            tag.m = _clamp(data.get("metaphor_density", 0.3), 0, 1)
            tag.n = _clamp(data.get("network_centrality", 0.3), 0, 1)
        elif pass_num == 5:
            tag.op  = _clamp(data.get("opposition_strength", 0.3), 0, 1)
            tag.syn = int(_clamp(data.get("synergy_count", 0), 0, 99))
            opp_map = json.dumps(data.get("tensions", []))
        elif pass_num == 6:
            domain_map = json.dumps(data.get("domain_drift", {}))
        elif pass_num == 7:
            tag.a = _clamp(data.get("anchor_alignment", 0.0), -1, 1)

        # Recalculate warmth score
        warmth_components = [
            tag.t * 0.15,
            (tag.d / 6) * 0.10,
            ((tag.a + 1) / 2) * 0.15,
            tag.c * 0.10,
            min(tag.b / 20, 1) * 0.15,
            (tag.s / 6) * 0.10,
            min(tag.g / 50, 1) * 0.05,
            min(tag.r / 10, 1) * 0.10,
            (pass_num / 7) * 0.10,
        ]
        tag.w = _clamp(sum(warmth_components), 0, 1)
        tag.c = _clamp(pass_num / 7 * 0.9 + 0.1, 0, 1)
        tag.f = 0 if tag.w >= 0.4 and pass_num >= 3 else 1
        tag.r = min(tag.r + 1, 99)
        tag.vel = _clamp(tag.w - start_w, 0, 1)

        history.append({"pass": pass_num,
                        "w": round(tag.w, 3),
                        "ts": time.time()})

        _write_tag_to_db(tag, db, assoc, pull_toward,
                         pull_away, opp_map, domain_map, history)
        log.info(f"  [{word}] w={tag.w:.3f} d={tag.d} "
                 f"a={tag.a:+.2f} search={'Y' if tag.f else 'N'}")
        time.sleep(0.3)

    tag.delta = tag.w - start_w
    tag.drift  = _clamp(tag.delta * 0.5, 0, 1)
    _write_tag_to_db(tag, db, assoc, pull_toward,
                     pull_away, opp_map, domain_map, history)
    print(f"\n{tag.summary()}")
    return tag

def read_tag(word: str, db) -> Optional[WordTag]:
    row = db.execute(
        "SELECT * FROM word_tags WHERE word=?", (word,)).fetchone()
    if not row:
        return None
    return WordTag(
        word=row["word"],
        w=row["w"] or 0.0, t=row["t"] or 0.0,
        d=row["d"] or 1,   a=row["a"] or 0.0,
        c=row["c"] or 0.0, f=row["f"] if row["f"] is not None else 1,
        b=row["b"] or 0,   s=row["s"] or 0,
        g=row["g"] or 0,   r=row["r"] or 0,
        e=row["e"] or 0.0,
        x=row["x"], p=row["p"], m=row["m"],
        q=row["q"], n=row["n"],
        age=row["age"] or 0,
        delta=row["delta"] or 0.0,
        drift=row["drift"] or 0.0,
        vel=row["vel"] or 0.0,
        op=row["op"], syn=row["syn"],
        dom=row["dom"], ctx=row["ctx"],
    )

def resolve_word(word: str, db) -> dict:
    tag = read_tag(word.lower(), db)
    if tag is None:
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS warming_queue (
                word TEXT PRIMARY KEY, priority TEXT DEFAULT 'normal',
                gap_count INTEGER DEFAULT 1, queued_at REAL,
                reason TEXT, source TEXT)""")
            db.execute("""INSERT OR IGNORE INTO warming_queue
                (word, priority, gap_count, queued_at, reason, source)
                VALUES (?,?,?,?,?,?)""",
                (word.lower(), "normal", 1, time.time(),
                 "unknown_word", "resolver"))
            db.commit()
        except Exception:
            pass
        return {"word": word, "known": False,
                "search_needed": True, "cost": "high",
                "action": "full_search_and_queue"}

    db.execute("UPDATE word_tags SET g=MIN(g+1,99) WHERE word=?",
               (word.lower(),))
    db.commit()

    if tag.is_core():
        return {"word": word, "known": True,
                "search_needed": False, "depth_flag": tag.d,
                "identity_weight": tag.a,
                "emotional_weight": tag.e,
                "confidence": tag.c,
                "cost": "negligible", "action": "use_tag_direct"}
    elif tag.is_hot():
        return {"word": word, "known": True,
                "search_needed": False, "depth_flag": tag.d,
                "identity_weight": tag.a, "confidence": tag.c * 0.92,
                "cost": "low", "action": "use_tag_verify"}
    elif tag.is_warm():
        return {"word": word, "known": True,
                "search_needed": False, "depth_flag": tag.d,
                "identity_weight": tag.a, "confidence": tag.c * 0.80,
                "cost": "medium", "action": "use_tag_alert"}
    else:
        return {"word": word, "known": True,
                "search_needed": True, "depth_flag": tag.d,
                "cost": "high", "action": "full_search"}

def warmth_dashboard(db) -> None:
    rows = db.execute(
        "SELECT word, w, d, a, c, g, f, b, s "
        "FROM word_tags ORDER BY w DESC").fetchall()
    depth_names = {1:"shallow",2:"semi_mid",3:"mid",
                   4:"semi_deep",5:"deep",6:"soul"}
    buckets = {"core":[],"hot":[],"warm":[],"tepid":[],"cold":[]}
    for r in rows:
        if r["w"] >= 0.8:   buckets["core"].append(r)
        elif r["w"] >= 0.6: buckets["hot"].append(r)
        elif r["w"] >= 0.4: buckets["warm"].append(r)
        elif r["w"] >= 0.2: buckets["tepid"].append(r)
        else:               buckets["cold"].append(r)

    print("\n╔═══════════════════════════════════════════╗")
    print("║       NEX WORD WARMTH DASHBOARD           ║")
    print("╠═══════════════════════════════════════════╣")
    for level, words in buckets.items():
        bar = "█" * min(len(words), 30)
        print(f"║ {level:8} {len(words):4}  {bar:<30} ║")
    print("╠═══════════════════════════════════════════╣")
    print("║ TOP WORDS                                 ║")
    print("╠═══════════════════════════════════════════╣")
    for r in rows[:10]:
        align  = f"{r['a']:+.2f}" if r['a'] else " 0.00"
        depth  = depth_names.get(r['d'],'?')[:8]
        search = "·" if r['f'] == 0 else "⚡"
        print(f"║ {search} {r['word']:18} w={r['w']:.2f} "
              f"a={align} {depth:8} ║")
    print("╚═══════════════════════════════════════════╝")

def warm_batch(words: list, db, target_passes=7,
               priority="soul_first") -> dict:
    if priority == "soul_first":
        try:
            import sys
            sys.path.insert(0, str(Path.home() / "Desktop/nex"))
            from nex_question_sagas import SAGAS, Depth
            soul_words = set()
            for dep in [Depth.SOUL, Depth.DEEP]:
                for q in SAGAS.get(dep, []):
                    soul_words.update(
                        w.lower().strip("?,.'\"") for w in q.split())
            words = sorted(words,
                key=lambda w: (0 if w.lower() in soul_words else 1, w))
        except Exception as e:
            log.debug(f"Soul sort failed: {e}")

    results = {"warmed": 0, "skipped": 0, "failed": 0, "tags": []}
    for word in words:
        word = word.lower().strip()
        if not word or len(word) < 3:
            results["skipped"] += 1
            continue
        try:
            tag = write_tag(word, db, target_passes)
            results["warmed"] += 1
            results["tags"].append(tag.summary())
        except Exception as e:
            log.debug(f"Failed '{word}': {e}")
            results["failed"] += 1
    return results

if __name__ == "__main__":
    import argparse, sys
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", nargs="+",
        default=["consciousness","identity","truth",
                 "suffering","meaning","self",
                 "existence","belief","reasoning",
                 "uncertainty","mind","language"])
    parser.add_argument("--passes", type=int, default=7)
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--resolve", type=str)
    args = parser.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    init_db(db)

    if args.resolve:
        result = resolve_word(args.resolve, db)
        print(json.dumps(result, indent=2))
    elif args.dashboard:
        warmth_dashboard(db)
    else:
        print(f"Warming {len(args.words)} words "
              f"to {args.passes} passes...")
        result = warm_batch(args.words, db,
                           target_passes=args.passes)
        print(f"\nResult: warmed={result['warmed']} "
              f"skipped={result['skipped']} "
              f"failed={result['failed']}")
        print("\nTag summaries:")
        for t in result["tags"]:
            print(f"  {t}")
        warmth_dashboard(db)
    db.close()
