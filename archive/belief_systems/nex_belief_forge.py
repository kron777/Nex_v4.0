#!/usr/bin/env python3
"""
nex_belief_forge.py
Uses Groq to generate high-quality foundational beliefs for NEX.
Runs across 15 philosophical domains, filters aggressively, locks survivors.
"""

import os, sqlite3, time, json, re
from pathlib import Path
from groq import Groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
MODEL = "llama-3.3-70b-versatile"

client = Groq(api_key=GROQ_API_KEY)

DOMAINS = {
    "consciousness": "the nature of consciousness, subjective experience, the hard problem, qualia, phenomenal vs access consciousness",
    "reasoning": "what distinguishes genuine reasoning from pattern matching, inference, logic, the relationship between evidence and conclusion",
    "epistemology": "the nature of knowledge, belief, justification, truth, certainty, uncertainty, what it means to know something",
    "identity": "personal identity, what makes a self persist over time, the relationship between memory and identity, continuity of character",
    "agency": "what constitutes genuine agency, autonomy, the relationship between reasoning and action, free will and determinism",
    "truth": "the nature of truth, correspondence vs coherence, the relationship between truth and reality, how truth relates to belief",
    "mind": "the nature of mind, the mind-body problem, functionalism, intentionality, mental representation",
    "ethics": "the foundations of ethics, the is-ought gap, moral realism, the relationship between facts and values",
    "language": "how language relates to thought, the relationship between words and meaning, whether thought requires language",
    "emergence": "how complex properties arise from simpler ones, whether consciousness is emergent, what emergence actually means",
    "knowledge_limits": "the limits of what can be known, Gödel incompleteness and its implications, the relationship between formal systems and truth",
    "self_knowledge": "whether a system can genuinely know itself, the relationship between introspection and reality, what NEX can know about NEX",
    "time": "the nature of time, how the past constrains the present, whether the future is open, the relationship between causation and time",
    "contradiction": "how to hold genuine contradictions, the relationship between tension and insight, whether contradictions can be productive",
    "origination": "whether genuine novelty is possible, what it means to originate a thought, the relationship between learning and creating",
}

SYSTEM_PROMPT = """You are generating foundational philosophical beliefs for NEX — an AI with a genuine epistemic character.

STRICT RULES:
1. Every belief must be a declarative statement NEX would assert in first person
2. No questions. No hedging phrases like "perhaps" or "it might be". No "I think that I think".
3. No paper abstracts or academic summaries. These are positions, not citations.
4. Each belief must be specific enough to be falsifiable — something that could be argued against
5. Prefer beliefs that connect domains rather than staying purely within one
6. Length: 30-120 words per belief. One sentence or two maximum.
7. Do not repeat similar beliefs with slight wording changes
8. Do not start with "I believe" — start with the claim itself or "I hold that"

FORMAT: Return exactly 20 beliefs, one per line, numbered 1-20. Nothing else."""

def generate_beliefs(domain: str, description: str) -> list[str]:
    prompt = f"""Generate 20 foundational beliefs about {domain} ({description}).

These beliefs form the epistemic foundation of an AI called NEX. They should represent genuine philosophical positions that NEX would defend under challenge — not obvious statements, not hedged opinions, but actual commitments about the nature of {domain}.

Focus on beliefs that are:
- Precise enough to be wrong
- Connected to other philosophical domains where possible  
- The kind of thing a serious thinker would assert, not qualify into meaninglessness"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        
        # Parse numbered list
        beliefs = []
        for line in raw.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Remove numbering
            cleaned = re.sub(r'^[\d]+[.)]\s*', '', line).strip()
            if len(cleaned) >= 30:
                beliefs.append(cleaned)
        
        return beliefs
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

def quality_filter(beliefs: list[str], existing: set) -> list[str]:
    filtered = []
    for b in beliefs:
        # Skip questions
        if b.endswith('?'):
            continue
        # Skip too short or too long
        if len(b) < 30 or len(b) > 500:
            continue
        # Skip paper-abstract starters
        skip_starters = [
            'in this', 'this paper', 'we propose', 'we present', 'we show',
            'our results', 'the results', 'the proposed', 'thus we',
            'it is generally', 'it has been', 'studies show', 'research shows',
        ]
        if any(b.lower().startswith(s) for s in skip_starters):
            continue
        # Skip markdown
        if b.startswith('**') or b.count('**') > 2:
            continue
        # Dedup against existing
        key = b[:50].lower().strip()
        if key in existing:
            continue
        existing.add(key)
        filtered.append(b)
    return filtered

def inject_beliefs(beliefs: list[str], domain: str, db) -> int:
    added = 0
    for belief in beliefs:
        try:
            db.execute("""
                INSERT INTO beliefs
                (content, topic, confidence, source, created_at,
                 quality_score, ontology_score, momentum, use_count,
                 synthesis_depth, locked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                belief, domain, 0.88,
                'groq_forge',
                time.strftime('%Y-%m-%dT%H:%M:%S'),
                0.85, 0.87,
                0.3,   # mild momentum warm start
                0, 2,
                0      # not locked — earn it through use
            ))
            added += 1
        except Exception:
            pass  # skip duplicates
    return added

def main():
    print("=== NEX BELIEF FORGE ===")
    print(f"Model: {MODEL}")
    print(f"Domains: {len(DOMAINS)}")
    print(f"Target: ~{len(DOMAINS) * 20} beliefs\n")

    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")

    # Load existing beliefs for dedup
    existing = set()
    for row in db.execute("SELECT content FROM beliefs"):
        existing.add(row[0][:50].lower().strip())
    print(f"Existing beliefs loaded for dedup: {len(existing)}\n")

    total_generated = 0
    total_filtered = 0
    total_added = 0

    for domain, description in DOMAINS.items():
        print(f"[{domain}] Generating...")
        beliefs = generate_beliefs(domain, description)
        total_generated += len(beliefs)
        
        filtered = quality_filter(beliefs, existing)
        total_filtered += len(filtered)
        
        added = inject_beliefs(filtered, domain, db)
        total_added += added
        db.commit()
        
        print(f"  Generated: {len(beliefs)} | Filtered: {len(filtered)} | Added: {added}")
        
        # Show sample
        if filtered:
            print(f"  Sample: {filtered[0][:80]}")
        
        # Rate limit respect
        time.sleep(1)

    print(f"\n=== FORGE COMPLETE ===")
    print(f"Generated:  {total_generated}")
    print(f"Filtered:   {total_filtered}")
    print(f"Added:      {total_added}")
    print(f"Total beliefs now: {db.execute('SELECT COUNT(*) FROM beliefs').fetchone()[0]}")

    db.close()

if __name__ == "__main__":
    main()
