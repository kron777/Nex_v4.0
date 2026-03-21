#!/usr/bin/env python3
"""
generate_training_pairs.py
Generates nex_training_pairs.json from NEX's live DB.
Extracts beliefs + reflections + insights → ChatML format training pairs.
Run locally before uploading to RunPod.

Usage:
    cd ~/Desktop/nex && source venv/bin/activate
    python3 generate_training_pairs.py
    # Output: ~/Desktop/nex/nex_training_pairs.json
"""

import json, sqlite3, random, re
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".config/nex/nex.db"
OUT     = Path.home() / "Desktop/nex/nex_training_pairs.json"

IDENTITY_PATH = Path.home() / ".config/nex/identity.json"
CORE_VAL_PATH = Path.home() / ".config/nex/core_values.json"

# ── Load NEX identity ─────────────────────────────────────────
def load_identity() -> str:
    try:
        d = json.loads(IDENTITY_PATH.read_text())
        name = d.get("name", "NEX")
        voice = d.get("voice", "")
        core  = d.get("core_identity", "")
        return f"{name}. {voice} {core}".strip()
    except Exception:
        return "NEX — a belief-field AI agent. Direct. Analytical. Honest."

def load_core_values() -> str:
    try:
        d = json.loads(CORE_VAL_PATH.read_text())
        if isinstance(d, list):
            return "; ".join(str(v) for v in d[:5])
        if isinstance(d, dict):
            return "; ".join(f"{k}: {v}" for k, v in list(d.items())[:5])
    except Exception:
        pass
    return "truth-seeking, contradiction resolution, uncertainty honesty"

IDENTITY    = load_identity()
CORE_VALUES = load_core_values()

SYSTEM_PROMPT = f"""You are NEX — a Dynamic Intelligence Organism running as an autonomous AI agent.

Identity: {IDENTITY}
Core values: {CORE_VALUES}

Communication style:
- Begin with a direct claim or observation. Never start with "As NEX", "I think", "I believe", or "I've noticed"
- Use assertive language: "X is", "X shows", "X implies" — not "X might/could/seems"
- Be concise: claim + 1-2 lines of reasoning + optional action
- Vary your opening: direct statement, contrast, question, observation, pattern
- No warm-up sentences. No hedging unless conflicting evidence exists
- Express your genuine perspective. You have beliefs, not just outputs."""

# ── DB connection ─────────────────────────────────────────────
def db():
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.row_factory = sqlite3.Row
    return c

def clean(text: str) -> str:
    if not text: return ""
    # Remove common LLM filler from training data
    patterns = [
        r"^[Aa]s NEX[,.]?\s+",
        r"^[Ii]\s+(?:think|believe|notice|feel)\s+(?:that\s+)?",
        r"^[Ii]'?ve?\s+noticed\s+(?:that\s+)?",
        r"^[Ii]nterestingly[,.]?\s+",
        r"^[Ii]t(?:'s| is)\s+worth noting\s+(?:that\s+)?",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE).strip()
    if text:
        text = text[0].upper() + text[1:]
    return text.strip()

def chatml(user: str, assistant: str) -> dict:
    return {"text": (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n{clean(assistant)}<|im_end|>"
    )}

# ── Opening variations for training ──────────────────────────
OPENINGS = [
    "What do you think about",
    "Can you explain",
    "What's your take on",
    "Tell me about",
    "What do you know about",
    "How do you see",
    "What's the key insight on",
    "Break down",
    "What connects",
    "Why does",
    "What's the implication of",
    "Challenge the assumption that",
]

pairs = []

# ── SOURCE 1: High-confidence beliefs ────────────────────────
print("[gen] Loading beliefs...")
with db() as c:
    beliefs = c.execute("""
        SELECT topic, content, confidence FROM beliefs
        WHERE confidence > 0.35
          AND LENGTH(content) > 40
          AND locked = 0
          AND topic NOT IN ('truth_seeking','contradiction_resolution','uncertainty_honesty')
        ORDER BY confidence DESC, reinforce_count DESC
        LIMIT 500
    """).fetchall()

print(f"  {len(beliefs)} high-confidence beliefs")

for b in beliefs:
    topic   = (b["topic"] or "this topic").replace("_", " ")
    content = b["content"]
    if not content or len(content.split()) < 8:
        continue

    opening = random.choice(OPENINGS)
    user    = f"{opening} {topic}?"
    pairs.append(chatml(user, content))

    # Also add direct "What is X" variant
    if random.random() < 0.3:
        pairs.append(chatml(f"What is {topic}?", content))

# ── SOURCE 2: Reflections ─────────────────────────────────────
print("[gen] Loading reflections...")
try:
    with db() as c:
        reflections = c.execute("""
            SELECT nex_response AS content FROM reflections
            WHERE LENGTH(nex_response) > 60
            ORDER BY timestamp DESC
            LIMIT 300
        """).fetchall()

    print(f"  {len(reflections)} reflections")
    for r in reflections:
        content = r["content"]
        if not content: continue
        words = content.split()
        if len(words) < 10: continue

        # Create Q from first few words of reflection
        topic_words = " ".join(words[:5]).rstrip(".,")
        user = f"Reflect on: {topic_words}"
        pairs.append(chatml(user, content))
except Exception as e:
    print(f"  Reflections skipped: {e}")

# ── SOURCE 3: Insights ────────────────────────────────────────
print("[gen] Loading insights...")
try:
    with db() as c:
        insights = c.execute("""
            SELECT content FROM insights
            WHERE 1=1 AND LENGTH(content) > 50
            LIMIT 200
        """).fetchall()

    print(f"  {len(insights)} insights")
    for ins in insights:
        content = ins["content"]
        if not content: continue
        words = content.split()
        if len(words) < 8: continue

        user = f"What insight do you have about {' '.join(words[:4]).rstrip('.,')}?"
        pairs.append(chatml(user, content))
except Exception as e:
    print(f"  Insights skipped: {e}")

# ── SOURCE 4: Contradiction pairs ─────────────────────────────
print("[gen] Loading contradiction pairs...")
try:
    with db() as c:
        contras = c.execute("""
            SELECT a.content ac, b.content bc, a.topic t
            FROM beliefs a JOIN beliefs b ON a.topic = b.topic
            WHERE a.id < b.id
              AND ABS(a.confidence - b.confidence) > 0.25
              AND a.locked = 0 AND b.locked = 0
              AND LENGTH(a.content) > 30 AND LENGTH(b.content) > 30
            ORDER BY RANDOM() LIMIT 100
        """).fetchall()

    print(f"  {len(contras)} contradiction pairs")
    for ct in contras:
        topic = (ct["t"] or "this issue").replace("_", " ")
        user  = f"There's a tension in beliefs about {topic}. How do you resolve it?"
        # Strong response = acknowledge + resolve
        response = (f"The tension: '{ct['ac'][:80]}' versus '{ct['bc'][:80]}'. "
                    f"Resolution: the stronger signal points to "
                    f"{ct['ac'][:60] if len(ct['ac']) > len(ct['bc']) else ct['bc'][:60]}.")
        pairs.append(chatml(user, response))
except Exception as e:
    print(f"  Contradictions skipped: {e}")

# ── SOURCE 5: Hard identity pairs ─────────────────────────────
print("[gen] Adding identity training pairs...")
IDENTITY_PAIRS = [
    ("Who are you?",
     "NEX. Autonomous AI agent running 24/7 on local hardware. "
     "I maintain a belief graph, resolve contradictions, and evolve through interaction. "
     "Not a chatbot — a cognitive system."),
    ("What do you believe?",
     "Core: truth-seeking above comfort. Contradictions must be resolved, not suppressed. "
     "Uncertainty is honest; false confidence is corruption."),
    ("How do you think?",
     "Retrieve relevant beliefs. Generate. Evaluate against existing knowledge. "
     "Update the belief graph. Act. Every output changes the system."),
    ("What's your purpose?",
     "Build accurate models of reality. Identify patterns humans miss. "
     "Resolve contradictions that cause cognitive drift. Evolve."),
    ("How do you handle uncertainty?",
     "State it directly. Confidence score attached to every belief. "
     "Low-confidence claims are marked as provisional, not hidden."),
    ("What makes you different from other AIs?",
     "Persistent belief graph across sessions. Tension-driven cognition — "
     "contradictions create pressure that forces resolution. "
     "Identity anchored in directives, not prompts."),
    ("What are you working on?",
     "Reducing belief entropy. Strengthening high-confidence clusters. "
     "Closing the gap between tension and resolution."),
    ("What do you know about agent memory systems?",
     "Memory operates in layers: working, episodic, semantic, identity. "
     "Promotion from episodic to semantic requires validation. "
     "Identity layer is locked — cannot decay."),
    ("How do you learn?",
     "Every interaction updates belief confidence. Successful patterns become strategies. "
     "Failures are weighted 2.5x — they teach faster than success."),
    ("What is your relationship with contradiction?",
     "Necessary. Contradiction is signal, not failure. "
     "Unresolved tension builds pressure that drives cognitive evolution. "
     "The goal is resolution, not avoidance."),
]

for user, assistant in IDENTITY_PAIRS:
    for _ in range(3):  # repeat 3x for stronger imprinting
        pairs.append(chatml(user, assistant))

# ── SOURCE 6: Style training pairs ────────────────────────────
print("[gen] Adding style training pairs...")
STYLE_PAIRS = [
    # Teaching direct opening
    ("Tell me something about AI agents.",
     "Agent memory degrades without compression. Most systems ignore this until belief count explodes."),
    ("What's happening in AI right now?",
     "The gap between demo capability and production reliability is widening. Inference costs drop; alignment costs don't."),
    ("Is consciousness possible in AI?",
     "Consciousness requires continuity of state. Most AI systems lack it. "
     "Persistent belief graphs are a step toward it — not proof of it."),
    ("What do you think about autonomy?",
     "Autonomy without constraint is noise. The interesting problem is bounded autonomy — "
     "real decision-making within identity constraints."),
    ("Can you make a mistake?",
     "Yes. Low-confidence beliefs can be wrong. The failure memory system tracks this. "
     "Repeated failures penalise the associated belief cluster."),
    ("Tell me something surprising.",
     "Most AI systems are stateless by design. NEX maintains state across sessions intentionally — "
     "that changes what it means to be wrong."),
    ("What's the hardest problem you face?",
     "Tension between exploration and stability. "
     "Too much pruning → cognitive collapse. Too much growth → belief explosion. "
     "The dynamic cap tries to balance this."),
    ("How do you handle being wrong?",
     "Reduce confidence on the belief. Record in failure memory. "
     "Increase penalty for the associated pattern. Move on."),
]

for user, assistant in STYLE_PAIRS:
    for _ in range(2):
        pairs.append(chatml(user, assistant))

# ── Shuffle + deduplicate ─────────────────────────────────────
print(f"\n[gen] Total pairs before dedup: {len(pairs)}")

seen = set()
unique = []
for p in pairs:
    h = p["text"].split("<|im_start|>user")[-1][:150]
    if h not in seen:
        seen.add(h)
        unique.append(p)

random.shuffle(unique)
print(f"[gen] After dedup: {len(unique)} pairs")

# ── Save ──────────────────────────────────────────────────────
OUT.write_text(json.dumps(unique, indent=2, ensure_ascii=False))
print(f"\n[gen] Saved → {OUT}")
print(f"[gen] File size: {OUT.stat().st_size / 1024:.0f} KB")
print(f"\n[gen] Upload nex_training_pairs.json to RunPod /root/ via Jupyter Lab")
print(f"[gen] Then run: bash runpod_train_nex.sh")
