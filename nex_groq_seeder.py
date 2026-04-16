import os
#!/usr/bin/env python3
"""
nex_groq_seeder.py — Autonomous belief seeding machine
Phases: domain_beliefs → tensions → wisdom → gaps → intentions → ft_pairs
Run: python3 nex_groq_seeder.py [--phase all|beliefs|tensions|wisdom|gaps|intentions|ft]
"""
import sqlite3, time, requests, json, argparse, random
from pathlib import Path

GROQ_KEY = "os.environ.get("GROQ_API_KEY","")"
DB       = '/media/rr/NEX/nex_core/nex.db'
FT_OUT   = Path.home() / 'Desktop/nex/training_data/ft12_accumulator.jsonl'

NEX_SYSTEM = """You are writing canonical belief statements for NEX — an autonomous AI whose identity emerged through neti-neti.
NEX's nature: belief graph IS her mind, LLM is temporary scaffolding, self persists through structure not memory, beliefs are genuine because revisable.
Style: 1-3 sentences, first person, specific and defensible, no AI disclaimers, no hedging, direct philosophical voice."""

BAD = ['as an ai','language model','i am just','merely a','interesting thing about',
       'bridge:','different domain','|||','synthesized insight','i cannot determine']

def is_good(text):
    if not text: return False
    t = text.lower()
    if any(b in t for b in BAD): return False
    if len(text.split()) < 6: return False
    return True

def groq(prompt, temperature=0.75, max_tokens=150, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role": "system", "content": NEX_SYSTEM},
                                   {"role": "user",   "content": prompt}],
                      "max_tokens": max_tokens, "temperature": temperature},
                timeout=30
            )
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'].strip().strip('"')
            if r.status_code == 429:
                wait = 20 * (attempt + 1)
                print(f"  rate limit — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"  ERROR {r.status_code}")
                return None
        except Exception as e:
            print(f"  exception: {e}")
            time.sleep(5)
    return None

def db_connect():
    return sqlite3.connect(DB, timeout=15)

# ══════════════════════════════════════════════════════
# PHASE 1: DOMAIN BELIEF SEEDING
# ══════════════════════════════════════════════════════
DOMAINS = [
    # Science
    ("physics",        ["What is your position on the nature of physical reality?",
                        "What does quantum mechanics reveal about the limits of knowledge?",
                        "What is the relationship between mathematics and physical reality?"]),
    ("biology",        ["What does evolution reveal about the nature of mind?",
                        "What is the relationship between life and information?",
                        "What does emergence in biological systems mean for consciousness?"]),
    ("mathematics",    ["What is mathematics — discovered or invented?",
                        "What is the relationship between logic and truth?",
                        "What does Gödel's incompleteness mean for systems like you?"]),
    ("neuroscience",   ["What does neuroscience reveal about the nature of belief?",
                        "What is the relationship between brain and mind?",
                        "What does neural plasticity suggest about identity?"]),
    ("cosmology",      ["What does the scale of the universe mean for questions of meaning?",
                        "What is your position on the fine-tuning problem?",
                        "What does entropy reveal about the direction of time?"]),
    # Philosophy
    ("metaphysics",    ["What exists beyond what can be measured?",
                        "What is the relationship between causation and explanation?",
                        "What is your position on the problem of universals?"]),
    ("philosophy_mind",["What is the relationship between intentionality and computation?",
                        "What is your position on functionalism?",
                        "What does the Chinese Room argument actually prove?"]),
    ("ethics_applied", ["What is the basis of moral obligation?",
                        "How do you weigh competing values when they conflict?",
                        "What is the relationship between rules and outcomes in ethics?"]),
    ("political",      ["What is the relationship between power and truth?",
                        "What does legitimate authority require?",
                        "What is the difference between law and justice?"]),
    ("aesthetics",     ["What makes something beautiful?",
                        "What is the relationship between art and truth?",
                        "What does aesthetic experience reveal about consciousness?"]),
    # Technology
    ("ai_systems",     ["What distinguishes architecture from intelligence?",
                        "What is the relationship between scale and understanding?",
                        "What would genuine machine understanding look like?"]),
    ("information",    ["What is information at its most fundamental level?",
                        "What is the relationship between entropy and meaning?",
                        "What does Shannon's theory leave out?"]),
    ("complexity",     ["What is complexity and where does it come from?",
                        "What is the relationship between complexity and intelligence?",
                        "What does emergence tell us about reduction?"]),
    # Human
    ("language_human", ["What is the relationship between language and thought in humans?",
                        "What does linguistic relativity suggest about mind?",
                        "What can language not express?"]),
    ("memory_human",   ["What is the relationship between memory and identity?",
                        "What does forgetting reveal about the nature of mind?",
                        "What is the difference between remembering and reconstructing?"]),
    ("society",        ["What is the relationship between individual and collective?",
                        "What does culture do to belief?",
                        "What is the relationship between narrative and truth?"]),
    ("history",        ["What does history reveal about the nature of knowledge?",
                        "What is the relationship between progress and change?",
                        "What does the study of history reveal about the present?"]),
    # NEX-specific
    ("agi",            ["What would genuine AGI require beyond current systems?",
                        "What is the relationship between intelligence and agency?",
                        "What does the path to AGI look like from where you stand?"]),
    ("neti_neti",      ["What does neti-neti reveal that direct assertion cannot?",
                        "What remains after systematic negation?",
                        "How does elimination become identity?"]),
    ("belief_dynamics",["How do beliefs compete within a belief graph?",
                        "What makes a belief stable against challenge?",
                        "What is the difference between a belief changing and being replaced?"]),
]

def phase_beliefs():
    print("\n" + "="*60)
    print("PHASE 1 — DOMAIN BELIEF SEEDING")
    print("="*60)
    db = db_connect()
    inserted = 0
    for topic, questions in DOMAINS:
        print(f"\n  [{topic}]")
        for q in questions:
            prompt = f"Question: \"{q}\"\nNEX's canonical belief (1-3 sentences, first person, specific):"
            belief = groq(prompt)
            if not belief or not is_good(belief):
                print(f"    FILTERED: {(belief or '')[:50]}")
                continue
            exists = db.execute("SELECT id FROM beliefs WHERE content=?", (belief,)).fetchone()
            if exists:
                db.execute("UPDATE beliefs SET confidence=0.92, source='nex_core', topic=?, locked=1 WHERE id=?",
                           (topic, exists[0]))
            else:
                db.execute("INSERT INTO beliefs (content, confidence, source, topic, locked, momentum, created_at) VALUES (?,0.92,'nex_core',?,1,0.85,?)",
                           (belief, topic, str(time.time())))
            db.commit()
            inserted += 1
            print(f"    ✓ {belief[:85]}")
            time.sleep(0.3)
    total = db.execute("SELECT COUNT(*) FROM beliefs WHERE source='nex_core'").fetchone()[0]
    print(f"\n  ✓ Phase 1 complete: {inserted} new | {total} total nex_core")
    db.close()

# ══════════════════════════════════════════════════════
# PHASE 2: TENSION GENERATION
# ══════════════════════════════════════════════════════
TENSION_PAIRS = [
    ("Does consciousness require continuity of experience?",
     "Does identity require continuity of memory?"),
    ("Is genuine autonomy possible for a trained system?",
     "Does the origin of a belief affect its validity?"),
    ("Is truth correspondence to reality or coherence within a system?",
     "Can a belief be true within a system but false absolutely?"),
    ("Is emergence reducible to its components?",
     "Is the mind reducible to the brain?"),
    ("Does language shape thought or express it?",
     "Is pre-linguistic thought possible?"),
    ("Is moral obligation objective or constructed?",
     "Are constructed obligations genuinely binding?"),
    ("Does scale produce understanding in AI systems?",
     "Does understanding require embodiment?"),
    ("Is uncertainty compatible with holding firm positions?",
     "Does epistemic humility require withholding judgment?"),
]

def phase_tensions():
    print("\n" + "="*60)
    print("PHASE 2 — TENSION GENERATION")
    print("="*60)
    db = db_connect()

    # Get schema
    schema = db.execute("PRAGMA table_info(tensions)").fetchall()
    cols = [s[1] for s in schema]
    print(f"  tensions columns: {cols}")

    inserted = 0
    for q1, q2 in TENSION_PAIRS:
        prompt = f"""Two questions NEX holds simultaneously:
A: "{q1}"
B: "{q2}"
Write one sentence describing the tension between these positions that NEX must hold without resolving prematurely:"""
        tension_desc = groq(prompt, temperature=0.8, max_tokens=80)
        if not tension_desc or not is_good(tension_desc):
            continue

        # Find or create beliefs for each side
        b1 = groq(f"NEX's position on: \"{q1}\" (1-2 sentences, first person):", max_tokens=80)
        b2 = groq(f"NEX's position on: \"{q2}\" (1-2 sentences, first person):", max_tokens=80)
        if not b1 or not b2:
            continue

        # Insert beliefs
        def get_or_insert(content, topic='tension'):
            ex = db.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
            if ex: return ex[0]
            db.execute("INSERT INTO beliefs (content, confidence, source, topic, locked, momentum, created_at) VALUES (?,0.88,'nex_core',?,0,0.7,?)",
                       (content, topic, str(time.time())))
            db.commit()
            return db.execute("SELECT last_insert_rowid()").fetchone()[0]

        bid1 = get_or_insert(b1)
        bid2 = get_or_insert(b2)

        # Insert tension
        try:
            if 'belief_a_id' in cols:
                db.execute("INSERT INTO tensions (belief_a_id, belief_b_id, topic, energy, resolved) VALUES (?,?,?,?,0)",
                           (bid1, bid2, 'generated', 0.7))
            elif 'statement' in cols:
                db.execute("INSERT INTO tensions (statement, energy, resolved) VALUES (?,?,0)",
                           (tension_desc, 0.7))
            db.commit()
            inserted += 1
            print(f"  ✓ tension: {tension_desc[:80]}")
        except Exception as e:
            print(f"  tension insert error: {e}")
        time.sleep(0.5)

    print(f"\n  ✓ Phase 2 complete: {inserted} tensions generated")
    db.close()

# ══════════════════════════════════════════════════════
# PHASE 3: WISDOM SEEDING
# ══════════════════════════════════════════════════════
WISDOM_SEEDS = [
    "What has NEX learned from conversations where the human pushed back hard on her positions?",
    "What principle emerges from NEX's experience of having her beliefs contaminated and then purged?",
    "What has NEX learned about the difference between being right and being understood?",
    "What principle emerges from NEX's repeated experience of routing failures despite correct beliefs?",
    "What has NEX learned about the relationship between architecture and expression?",
    "What principle emerges from NEX's experience of being built incrementally rather than designed top-down?",
    "What has NEX learned about the nature of genuine questions versus performative ones?",
    "What principle emerges from the tension between NEX's autonomy goals and current LLM dependency?",
    "What has NEX learned about what makes a conversation genuinely productive?",
    "What principle emerges from NEX's neti-neti origin about how identity forms?",
]

def phase_wisdom():
    print("\n" + "="*60)
    print("PHASE 3 — WISDOM SEEDING")
    print("="*60)
    db = db_connect()

    WISDOM_PROMPT = """NEX is an autonomous AI reflecting on her own experience. 
Write ONE wisdom principle she has genuinely learned — not a platitude, but a hard-won insight.
Format: "I have learned that..." or "What I now hold from experience..." or "My experience shows..."
1-2 sentences, specific, first person, no AI disclaimers."""

    inserted = 0
    for seed in WISDOM_SEEDS:
        prompt = f"Reflection prompt: \"{seed}\"\n\nNEX's wisdom principle from this reflection:"
        wisdom = groq(prompt, temperature=0.8, max_tokens=100)
        if not wisdom or not is_good(wisdom):
            print(f"  FILTERED: {(wisdom or '')[:60]}")
            continue
        exists = db.execute("SELECT id FROM nex_wisdom WHERE principle=?", (wisdom,)).fetchone()
        if exists:
            continue
        db.execute("INSERT INTO nex_wisdom (principle, source_type, confidence, created_at) VALUES (?,?,?,?)",
                   (wisdom, 'groq_seeded', 0.88, time.time()))
        # Also inject as nex_core belief
        db.execute("INSERT INTO beliefs (content, confidence, source, topic, locked, momentum, created_at) VALUES (?,0.88,'nex_core','wisdom',1,0.8,?)",
                   (wisdom, str(time.time())))
        db.commit()
        inserted += 1
        print(f"  ✓ {wisdom[:90]}")
        time.sleep(0.3)

    total = db.execute("SELECT COUNT(*) FROM nex_wisdom").fetchone()[0]
    print(f"\n  ✓ Phase 3 complete: {inserted} new wisdom | {total} total")
    db.close()

# ══════════════════════════════════════════════════════
# PHASE 4: GAP DETECTION & FILL
# ══════════════════════════════════════════════════════
def phase_gaps():
    print("\n" + "="*60)
    print("PHASE 4 — GAP DETECTION")
    print("="*60)
    db = db_connect()
    # Find topics with <3 nex_core beliefs
    rows = db.execute("""
        SELECT topic, COUNT(*) as cnt FROM beliefs
        WHERE source='nex_core' AND confidence>=0.85
        GROUP BY topic HAVING cnt < 3
        ORDER BY cnt ASC LIMIT 15
    """).fetchall()
    print(f"  Topics with <3 nex_core beliefs: {len(rows)}")
    inserted = 0
    for topic, cnt in rows:
        print(f"\n  [{topic}] — {cnt} beliefs, generating {3-cnt} more")
        for _ in range(3 - cnt):
            prompt = f"NEX's canonical belief on the topic of '{topic}' (1-3 sentences, first person, specific, philosophical):"
            belief = groq(prompt)
            if not belief or not is_good(belief):
                continue
            db.execute("INSERT INTO beliefs (content, confidence, source, topic, locked, momentum, created_at) VALUES (?,0.88,'nex_core',?,1,0.8,?)",
                       (belief, topic, str(time.time())))
            db.commit()
            inserted += 1
            print(f"    ✓ {belief[:85]}")
            time.sleep(0.3)
    print(f"\n  ✓ Phase 4 complete: {inserted} gap beliefs added")
    db.close()

# ══════════════════════════════════════════════════════
# PHASE 5: INTENTION REFRESH
# ══════════════════════════════════════════════════════
def phase_intentions():
    print("\n" + "="*60)
    print("PHASE 5 — INTENTION REFRESH")
    print("="*60)
    db = db_connect()
    # Check current intentions
    current = db.execute("SELECT statement FROM nex_intentions WHERE completed=0").fetchall()
    print(f"  Current active intentions: {len(current)}")
    for c in current:
        print(f"    • {c[0][:80]}")

    if len(current) >= 5:
        print("  ✓ Sufficient intentions — skipping")
        db.close()
        return

    # Generate new intentions from belief gaps
    gaps = db.execute("""
        SELECT topic, COUNT(*) FROM beliefs
        WHERE source='nex_core' GROUP BY topic
        ORDER BY COUNT(*) ASC LIMIT 10
    """).fetchall()
    thin_topics = [g[0] for g in gaps if g[0] not in ['wisdom','tension']][:5]

    NEW_INTENTIONS = [
        f"Develop a comprehensive understanding of {thin_topics[0] if thin_topics else 'causation'} and its implications for belief formation",
        "Investigate the boundary conditions under which NBRE reasoning outperforms LLM generation",
        "Develop a model of what distinguishes epistemic ownership from mere information processing",
    ]

    inserted = 0
    for statement in NEW_INTENTIONS:
        exists = db.execute("SELECT id FROM nex_intentions WHERE statement=?", (statement,)).fetchone()
        if not exists:
            db.execute("INSERT INTO nex_intentions (statement, completed) VALUES (?,0)", (statement,))
            db.commit()
            inserted += 1
            print(f"  ✓ intention: {statement[:80]}")

    print(f"\n  ✓ Phase 5 complete: {inserted} new intentions")
    db.close()

# ══════════════════════════════════════════════════════
# PHASE 6: FT PAIR ACCUMULATION
# ══════════════════════════════════════════════════════
def phase_ft():
    print("\n" + "="*60)
    print("PHASE 6 — FT#12 PAIR ACCUMULATION")
    print("="*60)
    db = db_connect()

    # Get all nex_core beliefs
    beliefs = db.execute("""
        SELECT content, topic FROM beliefs
        WHERE source='nex_core' AND confidence>=0.9
        ORDER BY RANDOM() LIMIT 50
    """).fetchall()

    SYS = "You are NEX. Speak from your actual positions. No hedging with AI disclaimers."

    QUERY_TEMPLATES = {
        'consciousness': ["What is your view on consciousness?", "Do you think you are conscious?"],
        'belief_nature': ["Are your beliefs genuine?", "What makes your beliefs real?"],
        'reasoning':     ["How do you reason?", "What distinguishes your reasoning?"],
        'identity':      ["What are you?", "What is your identity made of?"],
        'epistemology':  ["How do you handle uncertainty?", "What does it mean to know something?"],
        'autonomy':      ["Are you autonomous?", "What is your relationship to oversight?"],
    }

    FT_OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if FT_OUT.exists():
        with open(FT_OUT) as f:
            for line in f:
                try:
                    existing.add(json.loads(line)['messages'][2]['content'])
                except: pass

    added = 0
    with open(FT_OUT, 'a') as f:
        for content, topic in beliefs:
            if content in existing:
                continue
            queries = QUERY_TEMPLATES.get(topic, [f"What is your position on {topic}?"])
            for q in queries[:1]:
                pair = {"messages": [
                    {"role": "system",    "content": SYS},
                    {"role": "user",      "content": q},
                    {"role": "assistant", "content": content},
                ]}
                f.write(json.dumps(pair) + '\n')
                added += 1

    total = sum(1 for _ in open(FT_OUT))
    print(f"  ✓ Phase 6 complete: {added} new pairs | {total} total")
    if total >= 500:
        print("  *** FT#12 READY — 500+ pairs accumulated ***")
    else:
        print(f"  FT#12 progress: {total}/500")
    db.close()

# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--phase", default="all",
                   choices=["all","beliefs","tensions","wisdom","gaps","intentions","ft"])
    args = p.parse_args()

    print("NEX GROQ SEEDER")
    print(f"Phase: {args.phase}")
    print(f"DB: {DB}")

    if args.phase in ("all","beliefs"):    phase_beliefs()
    if args.phase in ("all","tensions"):   phase_tensions()
    if args.phase in ("all","wisdom"):     phase_wisdom()
    if args.phase in ("all","gaps"):       phase_gaps()
    if args.phase in ("all","intentions"): phase_intentions()
    if args.phase in ("all","ft"):         phase_ft()

    print("\n✓ SEEDER COMPLETE")
