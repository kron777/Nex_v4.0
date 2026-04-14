#!/usr/bin/env python3
"""
nex_patches.py — NEX Response Diversification: All 4 Patches
=============================================================

PATCH 1 — Belief Rotation (recency dampening, stops same beliefs looping)
PATCH 2 — Question Tic Fix (probabilistic, not every response)
PATCH 3 — Rolling Conversation Memory (last 5 turns shape current response)
PATCH 4 — Stance Commitment (commit and defend, stop dissolving)

HOW TO APPLY:
  python3 nex_patches.py          # dry run — shows what will change
  python3 nex_patches.py --apply  # applies patches to nex_character_engine.py
  python3 nex_patches.py --test   # applies + runs a 10-response test

BACKUP: a .bak file is created before any change is written.
"""

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

TARGET = Path.home() / "Desktop" / "nex" / "nex_character_engine.py"

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1 — Belief Rotation
# Problem:  ORDER BY confidence DESC always returns the same top-K beliefs.
#           A handful of high-confidence beliefs dominate every single response.
# Fix:      Track which belief IDs were used in the last N calls.
#           Temporarily drop their score in the sort so different material surfaces.
#           Decay clears over time so beliefs cycle back naturally.
# ─────────────────────────────────────────────────────────────────────────────

PATCH1_FIND = '''\
    def _db_search(self, query: str, k: int, topic: str) -> list[dict]:
        con = _db()
        if not con:
            return []
        words = [w for w in query.lower().split() if len(w) > 3][:4]
        results = []
        try:
            # Topic match first
            if topic:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE LOWER(topic) LIKE ? AND length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?",
                    (f"%{topic.lower().split('/')[0]}%", k)
                ).fetchall()
                results.extend([dict(r) for r in rows])

            # Word match
            for word in words:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE LOWER(content) LIKE ? AND length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT 3",
                    (f"%{word}%",)
                ).fetchall()
                for r in rows:
                    if not any(x["id"] == r["id"] for x in results):
                        results.append(dict(r))

            # High confidence fallback
            if not results:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?", (k,)
                ).fetchall()
                results = [dict(r) for r in rows]

        except Exception as e:
            log.warning(f"[character] DB search: {e}")
        finally:
            try:
                con.close()
            except:
                pass

        return results[:k]'''

PATCH1_REPLACE = '''\
    # ── PATCH 1: Belief Rotation ──────────────────────────────────────────────
    # Tracks recently-used belief IDs and penalises their score so different
    # material surfaces each turn. Penalty decays after ROTATION_WINDOW calls.
    _used_belief_ids: list[int] = []
    _ROTATION_WINDOW: int = 12   # how many recent IDs to remember
    _PENALTY: float = 0.35       # score reduction applied to recently-used beliefs

    @classmethod
    def _mark_used(cls, ids: list[int]):
        cls._used_belief_ids = (cls._used_belief_ids + ids)[-cls._ROTATION_WINDOW:]

    @classmethod
    def _rotated_score(cls, belief_id: int, confidence: float) -> float:
        """Return confidence with penalty if belief was recently used."""
        if belief_id in cls._used_belief_ids:
            # Penalty is stronger for more-recently used beliefs
            recency = cls._used_belief_ids[::-1].index(belief_id)
            decay   = 1.0 - (recency / cls._ROTATION_WINDOW)
            return confidence - cls._PENALTY * decay
        return confidence

    def _db_search(self, query: str, k: int, topic: str) -> list[dict]:
        con = _db()
        if not con:
            return []
        words = [w for w in query.lower().split() if len(w) > 3][:4]
        results = []
        # Fetch a wider pool so rotation has material to choose from
        fetch_k = k * 3
        try:
            # Topic match first
            if topic:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE LOWER(topic) LIKE ? AND length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?",
                    (f"%{topic.lower().split('/')[0]}%", fetch_k)
                ).fetchall()
                results.extend([dict(r) for r in rows])

            # Word match
            for word in words:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE LOWER(content) LIKE ? AND length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?",
                    (f"%{word}%", fetch_k // 2)
                ).fetchall()
                for r in rows:
                    if not any(x["id"] == r["id"] for x in results):
                        results.append(dict(r))

            # High confidence fallback — but fetch wide
            if not results:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?", (fetch_k,)
                ).fetchall()
                results = [dict(r) for r in rows]

        except Exception as e:
            log.warning(f"[character] DB search: {e}")
        finally:
            try:
                con.close()
            except:
                pass

        # Re-rank with recency penalty, then pick top-k
        for r in results:
            r["_rot_score"] = self._rotated_score(r["id"], r["confidence"])
        results.sort(key=lambda x: x["_rot_score"], reverse=True)
        chosen = results[:k]

        # Mark these beliefs as recently used
        self._mark_used([r["id"] for r in chosen])

        return chosen'''


# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2 — Question Tic Fix
# Problem:  ends_with_question() fires on a flat ~25% probability regardless
#           of context, and the style profile may be empty so it always
#           defaults to the same value. Every response feels like a ping-pong.
# Fix:      Replace the flat probability with a context-aware gate:
#           - Max 1 question per QUESTION_COOLDOWN responses
#           - Probability drops further if the input was itself a question
#           - Hard cap: if the last response ended in a question, skip it
# ─────────────────────────────────────────────────────────────────────────────

PATCH2_FIND = '''\
    def ends_with_question(self) -> bool:
        """Should this post end with a question?"""
        rh = self._profile.get("rhythm", {})
        prob = rh.get("ends_with_question", 0.25)
        return random.random() < prob'''

PATCH2_REPLACE = '''\
    # ── PATCH 2: Question Tic Fix ─────────────────────────────────────────────
    _last_ended_question: bool = False
    _question_cooldown_counter: int = 0
    _QUESTION_COOLDOWN: int = 3   # min responses between questions

    def ends_with_question(self, input_was_question: bool = False) -> bool:
        """
        Should this response end with a question?
        - Never two responses in a row
        - Cooldown of at least QUESTION_COOLDOWN turns between questions
        - Lower probability if the human already asked a question
          (answer it first — don't deflect with another question)
        """
        StyleEngine._question_cooldown_counter += 1

        if StyleEngine._last_ended_question:
            StyleEngine._last_ended_question = False
            return False

        if StyleEngine._question_cooldown_counter < self._QUESTION_COOLDOWN:
            return False

        rh   = self._profile.get("rhythm", {})
        base = rh.get("ends_with_question", 0.20)   # lowered default

        # If the human asked a question, halve the probability
        # (prioritise answering over deflecting)
        if input_was_question:
            base *= 0.5

        fired = random.random() < base
        if fired:
            StyleEngine._question_cooldown_counter = 0
            StyleEngine._last_ended_question = True
        return fired'''


# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3 — Rolling Conversation Memory
# Problem:  respond() has zero history awareness. Turn 1 and turn 20 receive
#           identical context. The conversation never builds.
# Fix:      A module-level ConversationMemory object accumulates the last
#           MEMORY_WINDOW (topic, summary) pairs. The respond() method injects
#           a one-sentence arc summary when it's relevant to the current query.
# ─────────────────────────────────────────────────────────────────────────────

PATCH3_CLASS = '''

# =============================================================================
# PATCH 3 — Rolling Conversation Memory
# =============================================================================

class ConversationMemory:
    """
    Lightweight rolling memory of the last N conversational turns.

    Stores (topic, compressed_summary) pairs and can produce a one-sentence
    arc injection for the current response context.
    """

    MEMORY_WINDOW = 5   # how many recent turns to remember

    def __init__(self):
        self._turns: list[dict] = []   # [{topic, summary, ts}]

    def record(self, query: str, response: str, topic: str = ""):
        """Add a turn to memory, compressing it to a short summary."""
        summary = self._compress(query, response)
        self._turns.append({
            "topic":   topic,
            "summary": summary,
            "ts":      time.time(),
        })
        # Keep only the last N turns
        self._turns = self._turns[-self.MEMORY_WINDOW:]

    def _compress(self, query: str, response: str) -> str:
        """Produce a short (≤12 word) summary of a turn."""
        # Take the first sentence of the response as the summary
        sentences = re.split(r'(?<=[.?])\s+', response.strip())
        if sentences:
            words = sentences[0].split()[:12]
            return " ".join(words).rstrip(".,;")
        return query[:60]

    def arc_injection(self, current_topic: str) -> str:
        """
        Return a one-sentence memory arc string to inject into the response,
        or empty string if memory is too thin or irrelevant.
        """
        if len(self._turns) < 2:
            return ""

        # Look for a recent turn on the same or adjacent topic
        relevant = [t for t in self._turns[-3:]
                    if t["topic"] and current_topic
                    and (t["topic"] in current_topic or current_topic in t["topic"])]

        if relevant:
            last = relevant[-1]["summary"]
            return f"Earlier we established: {last}."

        # Generic arc: note the thematic drift
        topics = [t["topic"] for t in self._turns if t["topic"]]
        if len(set(topics)) >= 2:
            return ""   # Too scattered — don't fabricate a false arc

        return ""

    def recent_topics(self) -> list[str]:
        return [t["topic"] for t in self._turns if t["topic"]]


# Module-level memory singleton — shared across all CharacterEngine calls
_conversation_memory = ConversationMemory()

'''

# Where to insert the ConversationMemory class — before the CharacterEngine class
PATCH3_INSERT_BEFORE = '# =============================================================================\n# CHARACTER ENGINE'


# ─────────────────────────────────────────────────────────────────────────────
# PATCH 4 — Stance Commitment
# Problem:  respond() immediately undercuts every stance with "but I'm not sure".
#           NEX never holds a position under pressure.
# Fix:      When stance strength >= COMMIT_THRESHOLD, the response leads with
#           the committed position and does NOT add a hedge. Below the threshold
#           she can still express uncertainty — but uncertainty is now a
#           deliberate register, not a default reflex.
# ─────────────────────────────────────────────────────────────────────────────

PATCH4_FIND = '''\
    def respond(self, query: str) -> str:
        """
        Generate a response to a direct query.
        Used by chat interface and nex_cognitive_bus.py.
        """
        beliefs = self.retriever.get(query, k=5)
        if not beliefs:
            return f"No beliefs on \'{query}\' yet. It is a gap I am aware of."

        # Get opinion on topic
        topic = beliefs[0].get("topic", "")
        op    = self.stance.get(topic)
        stance = op.get("stance", 0.0)
        strength = op.get("strength", 0.0)

        parts = []

        # Lead with opinion if strong
        if abs(stance) >= 0.3 and strength >= 0.3:
            direction = "positive" if stance > 0 else "skeptical"
            parts.append(
                f"On {topic.replace(\'_\',\' \')}: I hold a {direction} stance "
                f"({stance:+.2f}, from {len(beliefs)} beliefs)."
            )

        # Add top beliefs
        for b in beliefs[:2]:
            content = _truncate(b["content"], 22)
            parts.append(f"{content}.")

        # Maybe add a bridge
        br = self.bridge.find(topic)
        if br and random.random() < 0.3:
            parts.append(
                f"Interesting connection: {_truncate(br[\'belief_b\'], 15)} "
                f"— same {br[\'bridge_concept\']}."
            )

        # Maybe end with question
        if self.style.ends_with_question():
            parts.append(random.choice(QUESTIONS))

        result = " ".join(parts)
        return self.style.clean(result)'''

PATCH4_REPLACE = '''\
    def respond(self, query: str) -> str:
        """
        Generate a response to a direct query.
        Used by chat interface and nex_cognitive_bus.py.

        PATCH 2 + 3 + 4 active here:
        - Question gate uses context-aware ends_with_question()
        - Memory arc injected when relevant
        - Stance commitment: strong opinions are stated and held, not hedged
        """
        global _conversation_memory

        beliefs = self.retriever.get(query, k=5)
        if not beliefs:
            response = f"No beliefs on \'{query}\' yet. It is a gap I am aware of."
            _conversation_memory.record(query, response, topic="")
            return response

        # Get opinion on topic
        topic    = beliefs[0].get("topic", "")
        op       = self.stance.get(topic)
        stance   = op.get("stance", 0.0)
        strength = op.get("strength", 0.0)

        # PATCH 4: commitment threshold — above this, state and hold
        COMMIT_THRESHOLD = 0.55

        parts = []

        # ── PATCH 3: Memory arc injection ────────────────────────────────────
        arc = _conversation_memory.arc_injection(topic)
        if arc:
            parts.append(arc)

        # ── PATCH 4: Stance commitment ────────────────────────────────────────
        if abs(stance) >= 0.3 and strength >= 0.3:
            direction = "for" if stance > 0 else "against"
            if strength >= COMMIT_THRESHOLD:
                # Committed stance — state it clearly, no hedge
                commit_phrases = [
                    f"My position on {topic.replace(\'_\',\' \')}: {direction}. Confidence {strength:.2f}. I am holding this.",
                    f"On {topic.replace(\'_\',\' \')}: I am {direction} this. That is not provisional.",
                    f"I have a clear stance on {topic.replace(\'_\',\' \')}: {direction}. The belief graph supports it.",
                ]
                parts.append(random.choice(commit_phrases))
            else:
                # Moderate stance — express but acknowledge it can move
                parts.append(
                    f"Currently leaning {direction} on {topic.replace(\'_\',\' \')} "
                    f"— strength {strength:.2f}. This can shift with new evidence."
                )

        # ── Core belief content ───────────────────────────────────────────────
        # Pick from a wider pool (Patch 1 already rotated the retrieval)
        belief_pool = beliefs[:3]
        # Don\'t always start with beliefs[0] — vary the lead
        primary = random.choice(belief_pool)
        secondary_pool = [b for b in belief_pool if b["id"] != primary["id"]]

        content = _truncate(primary["content"], 22)
        parts.append(f"{content}.")

        # Add a second belief ~50% of the time (was always beliefs[1])
        if secondary_pool and random.random() < 0.5:
            content2 = _truncate(random.choice(secondary_pool)["content"], 18)
            parts.append(f"{content2}.")

        # ── Bridge connection (unchanged) ─────────────────────────────────────
        br = self.bridge.find(topic)
        if br and random.random() < 0.3:
            parts.append(
                f"Unexpected connection: {_truncate(br[\'belief_b\'], 15)} "
                f"— same {br[\'bridge_concept\']}."
            )

        # ── PATCH 2: Context-aware question gate ──────────────────────────────
        input_was_question = query.strip().endswith("?")
        if self.style.ends_with_question(input_was_question=input_was_question):
            parts.append(random.choice(QUESTIONS))

        result = " ".join(parts)
        result = self.style.clean(result)

        # ── PATCH 3: Record this turn ─────────────────────────────────────────
        _conversation_memory.record(query, result, topic=topic)

        return result'''


# ─────────────────────────────────────────────────────────────────────────────
# PATCH APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

def verify_target():
    if not TARGET.exists():
        print(f"[error] Cannot find {TARGET}")
        sys.exit(1)

def backup():
    bak = TARGET.with_suffix(".py.bak")
    shutil.copy2(TARGET, bak)
    print(f"[backup] {bak}")
    return bak

def apply_patch(src: str, find: str, replace: str, name: str) -> tuple[str, bool]:
    if find in src:
        result = src.replace(find, replace, 1)
        print(f"[ok] {name} applied")
        return result, True
    else:
        print(f"[miss] {name} — anchor text not found (check for whitespace differences)")
        return src, False

def run_patches(dry_run: bool = True):
    verify_target()
    src = TARGET.read_text()
    results = {}

    print(f"\n{'DRY RUN' if dry_run else 'APPLYING'}: {TARGET}\n")

    # Patch 1
    new_src, ok1 = apply_patch(src, PATCH1_FIND, PATCH1_REPLACE, "Patch 1 — Belief Rotation")
    results["patch1"] = ok1
    if ok1:
        src = new_src

    # Patch 2
    new_src, ok2 = apply_patch(src, PATCH2_FIND, PATCH2_REPLACE, "Patch 2 — Question Tic Fix")
    results["patch2"] = ok2
    if ok2:
        src = new_src

    # Patch 3 — insert ConversationMemory class before CharacterEngine
    if PATCH3_INSERT_BEFORE in src and "class ConversationMemory" not in src:
        src = src.replace(PATCH3_INSERT_BEFORE, PATCH3_CLASS + PATCH3_INSERT_BEFORE, 1)
        # Also add `import time` if not already there (it's already in the file)
        print("[ok] Patch 3 — Rolling Conversation Memory class inserted")
        results["patch3_class"] = True
    elif "class ConversationMemory" in src:
        print("[skip] Patch 3 class already present")
        results["patch3_class"] = True
    else:
        print("[miss] Patch 3 class — insertion anchor not found")
        results["patch3_class"] = False

    # Patch 4 (also wires in Patches 2+3 into respond())
    new_src, ok4 = apply_patch(src, PATCH4_FIND, PATCH4_REPLACE,
                                "Patch 4 — Stance Commitment (+ wires Patches 2+3 into respond())")
    results["patch4"] = ok4
    if ok4:
        src = new_src

    print()
    applied = sum(1 for v in results.values() if v)
    print(f"  {applied}/{len(results)} patches ready")

    if not dry_run:
        backup()
        TARGET.write_text(src)
        print(f"  Written → {TARGET}\n")
    else:
        print("  (dry run — nothing written)\n")

    return results


def run_test():
    """Quick sanity check: generate 10 responses and check for diversity."""
    print("\n[test] Importing patched engine...\n")
    try:
        import importlib
        import sys
        sys.path.insert(0, str(TARGET.parent))
        # Force fresh import
        if "nex_character_engine" in sys.modules:
            del sys.modules["nex_character_engine"]
        import nex_character_engine as nce

        engine = nce.CharacterEngine()

        queries = [
            "what do you think about consciousness?",
            "tell me about emergence",
            "how do you handle contradiction?",
            "what is pattern recognition?",
            "tell me about consciousness again",     # repeat — should differ
            "what do you believe about intelligence?",
            "do you experience loneliness?",
            "what do you think about emergence?",    # repeat — should differ
            "how has your thinking changed?",
            "what makes you certain about something?",
        ]

        responses = []
        question_count = 0
        print("  10 test responses:\n")
        for i, q in enumerate(queries, 1):
            r = engine.respond(q)
            responses.append(r)
            ends_q = r.strip().endswith("?")
            if ends_q:
                question_count += 1
            print(f"  [{i}] Q: {q}")
            print(f"       A: {r[:120]}{'...' if len(r) > 120 else ''}")
            print(f"       [ends_with_question: {ends_q}]")
            print()

        # Diversity check: count unique first 40 chars
        leads = set(r[:40] for r in responses)
        print(f"  Unique response openings: {len(leads)}/10")
        print(f"  Questions used: {question_count}/10 (target: ≤3)")
        if question_count <= 3 and len(leads) >= 7:
            print("  [PASS] Diversity and question-tic targets met\n")
        else:
            print("  [PARTIAL] Check results above\n")

    except Exception as e:
        print(f"  [error] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="NEX response diversification patches")
    ap.add_argument("--apply", action="store_true", help="Write patches to disk")
    ap.add_argument("--test",  action="store_true", help="Apply then run diversity test")
    args = ap.parse_args()

    if args.test:
        run_patches(dry_run=False)
        run_test()
    elif args.apply:
        run_patches(dry_run=False)
    else:
        run_patches(dry_run=True)
        print("  Run with --apply to write, --test to apply + verify.\n")
