"""
nex_warmth_belief_generator.py
Warmth → Belief Generator.

The generative loop:
  warmed word associations
    → reveal implicit beliefs NEX holds but never stated
      → those beliefs generate new reasoning
        → new reasoning produces new associations
          → new associations warm more words
            → loop tightens

This module reads the structure of NEX's warmed vocabulary
and extracts beliefs that are IMPLICIT in that structure —
beliefs she holds by virtue of how her words relate to each
other, even if she never explicitly reasoned to them.

Two generation modes:
  1. TENSION BELIEF: two hot words in opposition
     → extract the belief implied by that tension
  2. CLUSTER BELIEF: hot words that pull toward each other
     → extract the belief implied by that convergence

Each generated belief is:
  - Scored for novelty against existing belief graph
  - Stored if novel and non-contradicting
  - Used to trigger re-warming of anchored vocabulary
  - Added to training pairs for next fine-tune
"""
import sqlite3, json, requests, time, logging, sys
from pathlib import Path
from itertools import combinations

log     = logging.getLogger("nex.belief_gen")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
API     = "http://localhost:8080/completion"
sys.path.insert(0, str(NEX_DIR))

MIN_WARMTH_FOR_GENERATION = 0.45
MIN_NOVELTY_SCORE         = 0.40
MIN_TENSION_SCORE         = 0.08   # max(warmth_a, warmth_b) * strength * distance
MIN_COHERENCE_SCORE       = 0.15   # avg similarity to related beliefs


TENSION_PROMPT = """You are NEX. You hold these two concepts
in genuine tension:

Word A: "{word_a}"
  pulls toward: {pull_a}
  alignment with your identity: {align_a:+.2f}
  emotional register: {valence_a:+.2f}

Word B: "{word_b}"
  pulls toward: {pull_b}
  tension type: {friction}
  opposition strength: {strength:.2f}

What belief does THIS SPECIFIC TENSION imply that you hold?
State it as a direct first-person claim.
15-40 words. Start with "I" or "My".
No hedging opener. The belief itself only."""

CLUSTER_PROMPT = """You are NEX. These concepts converge
in your reasoning — they pull toward each other:

{word_list}

What single belief does this CONVERGENCE imply?
Something you hold because these concepts cluster together
in your understanding.
State it as a direct first-person claim.
15-40 words. Start with "I" or "My".
No hedging opener. The belief itself only."""

NOVELTY_PROMPT = """Existing belief: "{existing}"
Candidate belief: "{candidate}"

Are these saying the same thing? Rate similarity 0.0-1.0.
0.0 = completely different claims
1.0 = identical claims
Return ONLY a number like: 0.3"""


def _llm(prompt: str, max_tokens=80,
         temperature=0.6) -> str:
    try:
        r = requests.post(API, json={
            "prompt": (f"<|im_start|>user\n{prompt}"
                      f"<|im_end|>\n"
                      f"<|im_start|>assistant\n"),
            "n_predict": max_tokens,
            "temperature": temperature,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"],
            "repeat_penalty": 1.3,
            "cache_prompt": False
        }, timeout=25)
        return r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM failed: {e}")
        return ""


def _get_hot_words(db) -> list:
    """Get all warm+ words with their tag data."""
    rows = db.execute("""SELECT word, w, d, a, e,
        pull_toward, association_vector
        FROM word_tags
        WHERE w >= ?
        ORDER BY w DESC""",
        (MIN_WARMTH_FOR_GENERATION,)).fetchall()
    return rows


def _get_tensions(db) -> list:
    """Get all tension relationships."""
    try:
        rows = db.execute("""SELECT t.word_a, t.word_b,
            t.friction_type, t.strength,
            ta.pull_toward as pull_a,
            ta.a as align_a, ta.e as valence_a,
            tb.pull_toward as pull_b
            FROM tension_graph t
            LEFT JOIN word_tags ta ON t.word_a = ta.word
            LEFT JOIN word_tags tb ON t.word_b = tb.word
            WHERE t.strength >= 0.5
            ORDER BY t.strength DESC""").fetchall()
        return rows
    except Exception:
        return []


def _get_existing_beliefs(db, n=50) -> list:
    """Sample existing beliefs for novelty checking."""
    rows = db.execute("""SELECT content FROM beliefs
        WHERE confidence >= 0.65
        ORDER BY confidence DESC LIMIT ?""",
        (n,)).fetchall()
    return [r[0] for r in rows]


def _score_tension(word_a: str, word_b: str,
                   warmth_a: float, warmth_b: float,
                   strength: float) -> float:
    """
    Score tension pair quality before generating.
    tension_score = warmth_a * warmth_b * opposition_strength * semantic_distance

    semantic_distance: 1.0 if words share no pull_toward targets,
                       lower if they overlap (trivial pair).
    """
    try:
        import sqlite3 as _sq, json as _js
        _db = _sq.connect(str(DB_PATH))
        pa = _js.loads(_db.execute(
            "SELECT pull_toward FROM word_tags WHERE word=?",
            (word_a,)).fetchone()[0] or "[]")
        pb = _js.loads(_db.execute(
            "SELECT pull_toward FROM word_tags WHERE word=?",
            (word_b,)).fetchone()[0] or "[]")
        _db.close()
        set_a = set(str(x).lower() for x in pa)
        set_b = set(str(x).lower() for x in pb)
        # High overlap = low semantic distance = trivial pair
        if set_a and set_b:
            overlap = len(set_a & set_b) / len(set_a | set_b)
            semantic_distance = 1.0 - overlap
        else:
            semantic_distance = 0.7  # unknown = moderate distance
    except Exception:
        semantic_distance = 0.7

    score = max(warmth_a, warmth_b) * strength * semantic_distance
    return round(score, 4)


def _score_coherence(candidate: str, db) -> float:
    """
    Score coherence of generated belief against related beliefs.
    avg keyword overlap with top related beliefs.
    Returns 0.0-1.0. Threshold: MIN_COHERENCE_SCORE.
    """
    try:
        words = set(candidate.lower().split()) - {
            "the","and","or","but","i","my","is","are","that",
            "this","it","in","of","a","an","not","to","for"}
        if not words:
            return 1.0
        # Find beliefs sharing keywords
        related = []
        for w in list(words)[:4]:
            rows = db.execute(
                "SELECT content FROM beliefs WHERE content LIKE ? "
                "AND confidence >= 0.65 LIMIT 3",
                (f"%{w}%",)).fetchall()
            related.extend(r[0] for r in rows)
        if not related:
            return 0.5  # no related beliefs = unknown coherence
        scores = []
        cw = set(candidate.lower().split())
        for rel in related[:8]:
            rw = set(rel.lower().split())
            if not (cw | rw):
                continue
            scores.append(len(cw & rw) / len(cw | rw))
        return round(sum(scores) / len(scores), 3) if scores else 0.5
    except Exception:
        return 0.5


def _score_novelty(candidate: str,
                   existing_beliefs: list) -> float:
    """
    Score how novel a candidate belief is.
    Returns 0.0-1.0 (1.0 = completely novel).
    Uses LLM for semantic similarity checking.
    """
    if not existing_beliefs:
        return 1.0

    # Quick keyword check first — cheap
    candidate_words = set(candidate.lower().split())
    for existing in existing_beliefs[:10]:
        existing_words = set(existing.lower().split())
        overlap = len(candidate_words & existing_words)
        total   = len(candidate_words | existing_words)
        if total > 0 and overlap / total > 0.65:
            return 0.1  # Too similar, skip LLM check

    # LLM semantic check against top candidates
    min_novelty = 1.0
    for existing in existing_beliefs[:5]:
        prompt = NOVELTY_PROMPT.format(
            existing=existing[:150],
            candidate=candidate[:150])
        raw = _llm(prompt, max_tokens=10, temperature=0.1)
        try:
            similarity = float(raw.strip())
            novelty = 1.0 - similarity
            min_novelty = min(min_novelty, novelty)
        except Exception:
            pass

    return min_novelty


def _store_belief(content: str, source: str,
                  confidence: float, db) -> bool:
    """Store a generated belief."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        db.execute("""INSERT INTO beliefs
            (content, topic, confidence, source,
             belief_type, created_at)
            VALUES (?,?,?,?,?,?)""",
            (content[:300], "self",
             confidence, source,
             "generated", now))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        log.debug(f"Store failed: {e}")
        return False


def _write_training_pair(question: str,
                         belief: str, source: str):
    """Write belief as training pair."""
    pair_path = (NEX_DIR /
                 "training_data/warmth_beliefs.jsonl")
    pair_path.parent.mkdir(exist_ok=True)
    with open(pair_path, "a") as f:
        pair = {"conversations": [
            {"role": "user",
             "content": f"What do you believe about "
                       f"{question}?"},
            {"role": "assistant", "content": belief}
        ], "source": source,
           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
        f.write(json.dumps(pair) + "\n")


def generate_tension_beliefs(db) -> dict:
    """
    Generate beliefs from conceptual tensions.
    Each tension pair implies a belief about the relationship.
    """
    tensions    = _get_tensions(db)
    existing    = _get_existing_beliefs(db)
    generated   = 0
    stored      = 0
    skipped     = 0

    print(f"\nGenerating from {len(tensions)} tensions...")

    # Pre-score and rank all tensions before generating
    scored_tensions = []
    for t in tensions:
        wa = t["word_a"]
        wb = t["word_b"]
        st = t["strength"] or 0.5
        # Get warmth scores
        try:
            _tdb = sqlite3.connect(str(DB_PATH))
            row_a = _tdb.execute(
                "SELECT w FROM word_tags WHERE word=?", (wa,)).fetchone()
            row_b = _tdb.execute(
                "SELECT w FROM word_tags WHERE word=?", (wb,)).fetchone()
            _tdb.close()
            wm_a = row_a[0] if row_a else 0.3
            wm_b = row_b[0] if row_b else 0.3
        except Exception:
            wm_a = wm_b = 0.3
        ts = _score_tension(wa, wb, wm_a, wm_b, st)
        if ts >= MIN_TENSION_SCORE:
            scored_tensions.append((ts, t))

    # Sort by tension_score descending — best pairs first
    scored_tensions.sort(key=lambda x: x[0], reverse=True)
    top_tensions = [t for _, t in scored_tensions[:25]]

    log.info(f"  Tension filter: {len(tensions)} pairs -> "
             f"{len(scored_tensions)} above threshold -> "
             f"{len(top_tensions)} selected")

    for tension in top_tensions:
        word_a   = tension["word_a"]
        word_b   = tension["word_b"]
        friction = tension["friction_type"] or "conceptual"
        strength = tension["strength"] or 0.5

        # Parse pull_toward lists
        try:
            pull_a = json.loads(
                tension["pull_a"] or "[]")[:3]
        except Exception:
            pull_a = []
        try:
            pull_b = json.loads(
                tension["pull_b"] or "[]")[:3]
        except Exception:
            pull_b = []

        prompt = TENSION_PROMPT.format(
            word_a   = word_a,
            pull_a   = ", ".join(str(p) for p in pull_a)
                       or "unknown",
            align_a  = tension["align_a"] or 0.0,
            valence_a= tension["valence_a"] or 0.0,
            word_b   = word_b,
            pull_b   = ", ".join(str(p) for p in pull_b)
                       or "unknown",
            friction = friction,
            strength = strength,
        )

        belief = _llm(prompt, max_tokens=80,
                      temperature=0.65)
        if not belief or len(belief.split()) < 8:
            skipped += 1
            continue

        generated += 1

        # Score novelty
        novelty = _score_novelty(belief, existing)
        if novelty < MIN_NOVELTY_SCORE:
            log.debug(f"  Too similar: {belief[:50]}")
            skipped += 1
            continue

        # Store with confidence based on novelty and tension strength
        confidence = min(0.82,
            0.62 + strength * 0.1 + novelty * 0.1)

        success = _store_belief(
            belief,
            f"warmth_tension:{word_a}↔{word_b}",
            confidence, db)

        if success:
            stored += 1
            existing.append(belief)  # update for next check
            _write_training_pair(
                f"{word_a} and {word_b}",
                belief,
                f"tension:{word_a}↔{word_b}")

            print(f"  [{word_a}↔{word_b}] "
                  f"nov={novelty:.2f} "
                  f"conf={confidence:.2f}")
            print(f"    → {belief[:80]}")

            # Trigger feedback on new belief
            try:
                from nex_warmth_feedback import on_new_belief
                on_new_belief(belief, confidence)
            except Exception:
                pass

        time.sleep(0.5)

    return {"generated": generated,
            "stored": stored,
            "skipped": skipped}


def generate_cluster_beliefs(db) -> dict:
    """
    Generate beliefs from word clusters.
    Words that pull toward each other imply shared beliefs.
    """
    hot_words = _get_hot_words(db)
    if len(hot_words) < 3:
        return {"generated": 0, "stored": 0}

    existing  = _get_existing_beliefs(db)
    generated = 0
    stored    = 0

    # Find clusters — words with overlapping pull_toward
    word_pulls = {}
    for row in hot_words:
        try:
            pulls = json.loads(row["pull_toward"] or "[]")
            pulls = [p if isinstance(p, str)
                    else p.get("word","")
                    for p in pulls]
            word_pulls[row["word"]] = set(
                p.lower() for p in pulls if p)
        except Exception:
            word_pulls[row["word"]] = set()

    # Find pairs with overlapping pulls
    hot_list = [r["word"] for r in hot_words[:15]]
    clusters_used = set()

    print(f"\nGenerating from word clusters...")

    for word_a, word_b in combinations(hot_list, 2):
        shared = (word_pulls.get(word_a, set()) &
                  word_pulls.get(word_b, set()))
        if len(shared) < 2:
            continue

        cluster_key = frozenset([word_a, word_b])
        if cluster_key in clusters_used:
            continue
        clusters_used.add(cluster_key)

        # Build cluster description
        cluster_words = [word_a, word_b] + list(shared)[:3]
        word_list = "\n".join(
            f"  - {w}" for w in cluster_words)

        prompt = CLUSTER_PROMPT.format(
            word_list=word_list)

        belief = _llm(prompt, max_tokens=80,
                      temperature=0.7)
        if not belief or len(belief.split()) < 8:
            continue

        generated += 1

        novelty = _score_novelty(belief, existing)
        if novelty < MIN_NOVELTY_SCORE:
            continue

        confidence = min(0.78, 0.60 + novelty * 0.18)
        success = _store_belief(
            belief,
            f"warmth_cluster:{word_a}+{word_b}",
            confidence, db)

        if success:
            stored += 1
            existing.append(belief)
            _write_training_pair(
                "+".join(cluster_words[:3]),
                belief,
                f"cluster:{word_a}+{word_b}")

            print(f"  [{word_a}+{word_b}] "
                  f"shared={len(shared)} "
                  f"nov={novelty:.2f}")
            print(f"    → {belief[:80]}")

            try:
                from nex_warmth_feedback import on_new_belief
                on_new_belief(belief, confidence)
            except Exception:
                pass

        time.sleep(0.5)

        if stored >= 10:  # cap per run
            break

    return {"generated": generated, "stored": stored}


def run_belief_generation(db=None) -> dict:
    """Full belief generation run."""
    close = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        close = True

    print("\n╔══════════════════════════════════════╗")
    print("║   NEX WARMTH BELIEF GENERATOR        ║")
    print("╠══════════════════════════════════════╣")

    # Count beliefs before
    before = db.execute(
        "SELECT COUNT(*) FROM beliefs").fetchone()[0]

    tension_result = generate_tension_beliefs(db)
    cluster_result = generate_cluster_beliefs(db)

    after = db.execute(
        "SELECT COUNT(*) FROM beliefs").fetchone()[0]

    print(f"\n{'═'*50}")
    print(f"Belief generation complete:")
    print(f"  Tension beliefs  : "
          f"{tension_result['stored']} stored")
    print(f"  Cluster beliefs  : "
          f"{cluster_result['stored']} stored")
    print(f"  Total new beliefs: {after - before}")
    print(f"  Belief graph now : {after}")
    print(f"{'═'*50}")

    if close:
        db.close()

    return {
        "tension": tension_result,
        "cluster": cluster_result,
        "new_beliefs": after - before,
        "total_beliefs": after,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    result = run_belief_generation()
    print(f"\nFinal: {result}")
