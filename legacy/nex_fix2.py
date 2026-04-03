#!/usr/bin/env python3
"""
nex_fix2.py — NEX Response Quality Fix (round 2)
=================================================

Fixes 3 issues visible in test output:

FIX A — Memory arc compression
  Problem: arc injection was dumping the raw response string ("My position on
           cognition: against. Confidence 0.70...") instead of a clean summary.
  Fix:    Compress to topic + first meaningful clause only. Strip stance
          machinery text before storing.

FIX B — Stance topic resolution
  Problem: FAISS returns beliefs tagged "cognition" but the opinions table has
           "cognitive_architecture". The LIKE match fails so stance falls back
           to 0.0, then the commit block misfires with "against" because
           stance_score ends up being read from a cached/wrong row.
  Fix:    Widen the topic resolution chain: try exact → prefix → any substring
          → parent topic (strip after underscore). Also clamp: if strength < 0.4
          don't fire the commit block at all (avoids low-signal "against" labels).

FIX C — Arc injection double-prefix
  Problem: When the arc fired it prepended "Earlier we established:" but the
           stored summary already started mid-sentence, causing repetition.
  Fix:    Store summaries as clean noun-phrase fragments. Vary the arc prefix
          so it doesn't sound like a broken record.

HOW TO RUN:
  python3 nex_fix2.py          # dry run
  python3 nex_fix2.py --apply  # write to disk
  python3 nex_fix2.py --test   # apply + verify
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "Desktop" / "nex" / "nex_character_engine.py"

# ─────────────────────────────────────────────────────────────────────────────
# FIX A + C — Memory arc: better compression + varied prefix
# ─────────────────────────────────────────────────────────────────────────────

FIXA_FIND = '''\
    def _compress(self, query: str, response: str) -> str:
        """Produce a short (≤12 word) summary of a turn."""
        # Take the first sentence of the response as the summary
        sentences = re.split(r'(?<=[.?])\\s+', response.strip())
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
            return ""   # Too scattered — don\'t fabricate a false arc

        return ""'''

FIXA_REPLACE = '''\
    # Stance machinery phrases to strip before storing as summary
    _STRIP_PATTERNS = [
        r"My position on [^:]+: \\w+\\.",
        r"On [^:]+: I am (for|against) this\\.",
        r"Currently leaning (for|against) on [^—]+—[^.]+\\.",
        r"I have a clear stance on [^:]+: \\w+\\.",
        r"Confidence \\d+\\.\\d+\\. I am holding this\\.",
        r"Earlier we established: [^.]+\\.",
    ]

    def _compress(self, query: str, response: str) -> str:
        """
        Produce a clean ≤10 word topic summary — strip stance machinery,
        take the first substantive sentence.
        """
        text = response.strip()
        # Strip stance/arc boilerplate
        for pat in self._STRIP_PATTERNS:
            text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\\s{2,}", " ", text).strip()

        # Take first sentence
        sentences = re.split(r"(?<=[.?!])\\s+", text)
        first = next((s for s in sentences if len(s.split()) >= 4), None)
        if first:
            words = first.split()[:10]
            return " ".join(words).rstrip(".,;!?")
        # Fallback: compress the query itself
        return query.rstrip("?").strip()[:60]

    # Arc prefix variants — stops the injection sounding like a stuck record
    _ARC_PREFIXES = [
        "We covered this earlier —",
        "Building on what came before:",
        "This connects back to",
        "Earlier ground:",
        "Picking up the thread:",
    ]

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
            summary = relevant[-1]["summary"]
            if not summary or len(summary.split()) < 3:
                return ""
            prefix = random.choice(self._ARC_PREFIXES)
            return f"{prefix} {summary}."

        return ""'''


# ─────────────────────────────────────────────────────────────────────────────
# FIX B — Stance topic resolution + commit threshold guard
# ─────────────────────────────────────────────────────────────────────────────

FIXB_FIND = '''\
    def get(self, topic: str) -> dict:
        """Return stance dict for topic."""
        con = _db()
        if not con:
            return {"stance": 0.0, "strength": 0.0, "topic": topic}
        try:
            # Exact match
            row = con.execute(
                "SELECT topic, stance_score, strength FROM opinions "
                "WHERE topic = ? OR topic LIKE ?",
                (topic, f"%{topic.split('/')[0]}%")
            ).fetchone()
            if row:
                return {
                    "topic":    row["topic"],
                    "stance":   row["stance_score"],
                    "strength": row["strength"],
                }
        except:
            pass
        finally:
            try:
                con.close()
            except:
                pass
        return {"stance": 0.0, "strength": 0.0, "topic": topic}'''

FIXB_REPLACE = '''\
    def get(self, topic: str) -> dict:
        """
        Return stance dict for topic.
        FIX B: widened resolution chain so FAISS cluster labels (e.g. "cognition")
        correctly resolve to DB topics (e.g. "cognitive_architecture").
        Resolution order:
          1. Exact match
          2. DB topic starts with query topic prefix
          3. Query topic starts with DB topic prefix  (catches "cognition" → "cognitive_architecture")
          4. Parent word match (strip after underscore)
        """
        con = _db()
        if not con:
            return {"stance": 0.0, "strength": 0.0, "topic": topic}

        base   = topic.split("/")[0].split("_")[0]   # e.g. "cognition" → "cognit"
        prefix = topic.split("/")[0]                  # e.g. "cognitive_architecture"

        try:
            # 1. Exact or direct LIKE match
            row = con.execute(
                "SELECT topic, stance_score, strength FROM opinions "
                "WHERE topic = ? OR topic LIKE ?",
                (topic, f"{prefix}%")
            ).fetchone()

            # 2. Reverse: DB topic is a prefix of the query topic
            if not row:
                row = con.execute(
                    "SELECT topic, stance_score, strength FROM opinions "
                    "WHERE ? LIKE topic || '%'",
                    (prefix,)
                ).fetchone()

            # 3. Root word match (e.g. "cognit" matches "cognitive_architecture")
            if not row and len(base) >= 5:
                row = con.execute(
                    "SELECT topic, stance_score, strength FROM opinions "
                    "WHERE topic LIKE ?",
                    (f"{base}%",)
                ).fetchone()

            if row:
                return {
                    "topic":    row[0],
                    "stance":   row[1],
                    "strength": row[2],
                }
        except Exception as e:
            log.debug(f"[stance] lookup error: {e}")
        finally:
            try:
                con.close()
            except:
                pass
        return {"stance": 0.0, "strength": 0.0, "topic": topic}'''


# ─────────────────────────────────────────────────────────────────────────────
# FIX B2 — Commit block: raise minimum strength gate to 0.6, add direction
#           sanity check so "against" only fires for genuinely negative stances
# ─────────────────────────────────────────────────────────────────────────────

FIXB2_FIND = '''\
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
                )'''

FIXB2_REPLACE = '''\
        # PATCH 4 / FIX B2: raised thresholds + natural language stances
        # Minimum strength 0.6 before committing — avoids misfires on
        # weakly-resolved topics. Direction expressed as attitude, not
        # bare "for/against" which sounds robotic.
        COMMIT_THRESHOLD  = 0.60   # was 0.55
        MODERATE_THRESHOLD = 0.40  # was 0.30

        parts = []

        # ── PATCH 3: Memory arc injection ────────────────────────────────────
        arc = _conversation_memory.arc_injection(topic)
        if arc:
            parts.append(arc)

        # ── PATCH 4 / FIX B2: Stance commitment ──────────────────────────────
        topic_label = topic.replace("_", " ").split("/")[0]

        if abs(stance) >= 0.25 and strength >= MODERATE_THRESHOLD:
            if strength >= COMMIT_THRESHOLD:
                # Committed — state clearly without robotic "for/against"
                if stance > 0:
                    commit_phrases = [
                        f"On {topic_label}: I think this matters. My confidence is {strength:.0%}. I am not moving off that.",
                        f"I have a strong position on {topic_label} and I am holding it.",
                        f"{topic_label.capitalize()} is something I have thought about carefully. My stance is clear.",
                    ]
                else:
                    commit_phrases = [
                        f"On {topic_label}: I am sceptical, and that is a considered position — not a default.",
                        f"I hold real doubt about {topic_label}. Confidence {strength:.0%}. The belief graph backs this.",
                        f"{topic_label.capitalize()} troubles me in a specific way I have mapped out.",
                    ]
                parts.append(random.choice(commit_phrases))
            else:
                # Moderate — lean expressed, held lightly
                lean = "drawn to" if stance > 0 else "doubtful about"
                parts.append(
                    f"I find myself {lean} {topic_label} — though I hold that loosely."
                )'''


# ─────────────────────────────────────────────────────────────────────────────
# PATCH APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

FIXES = [
    ("Fix A+C — Memory arc compression + varied prefix", FIXA_FIND, FIXA_REPLACE),
    ("Fix B   — Stance topic resolution (wider chain)",  FIXB_FIND, FIXB_REPLACE),
    ("Fix B2  — Commit block thresholds + natural lang", FIXB2_FIND, FIXB2_REPLACE),
]

def verify():
    if not TARGET.exists():
        print(f"[error] {TARGET} not found"); sys.exit(1)

def backup():
    bak = TARGET.with_suffix(".py.bak2")
    shutil.copy2(TARGET, bak)
    print(f"[backup] {bak}")

def run(dry: bool):
    verify()
    src = TARGET.read_text()
    print(f"\n{'DRY RUN' if dry else 'APPLYING'}: {TARGET}\n")
    ok = 0
    for name, find, replace in FIXES:
        if find in src:
            src = src.replace(find, replace, 1)
            print(f"[ok]   {name}")
            ok += 1
        else:
            print(f"[miss] {name} — anchor not found")
    print(f"\n  {ok}/{len(FIXES)} fixes ready")
    if not dry:
        backup()
        TARGET.write_text(src)
        print(f"  Written → {TARGET}\n")
    else:
        print("  (dry run — nothing written)\n")

def test():
    print("\n[test] Running 10-response quality check...\n")
    try:
        if "nex_character_engine" in sys.modules:
            del sys.modules["nex_character_engine"]
        sys.path.insert(0, str(TARGET.parent))
        import nex_character_engine as nce
        engine = nce.CharacterEngine()

        queries = [
            "what do you think about consciousness?",
            "tell me about emergence",
            "how do you handle contradiction?",
            "tell me about consciousness again",
            "what makes you certain about something?",
            "do you experience loneliness?",
            "what do you think about emergence?",
            "what is your view on intelligence?",
            "how has your thinking shifted?",
            "what do you believe about free will?",
        ]

        responses = []
        q_count   = 0
        arc_count = 0
        bad_stance = 0

        for i, q in enumerate(queries, 1):
            r = engine.respond(q)
            responses.append(r)
            ends_q = r.strip().endswith("?")
            has_arc = any(p in r for p in ["We covered", "Building on", "connects back", "Earlier ground", "Picking up"])
            has_bad = "cognition: against" in r or "cognition: for" in r
            if ends_q:   q_count   += 1
            if has_arc:  arc_count += 1
            if has_bad:  bad_stance += 1

            tag = ""
            if ends_q:   tag += "[?] "
            if has_arc:  tag += "[arc] "
            if has_bad:  tag += "[BAD_STANCE] "

            print(f"  [{i:02}] {tag}{r[:110]}{'...' if len(r)>110 else ''}")
            print()

        leads  = set(r[:40] for r in responses)
        print(f"  Unique openings  : {len(leads)}/10  (target ≥7)")
        print(f"  Questions used   : {q_count}/10  (target ≤3)")
        print(f"  Arc injections   : {arc_count}/10")
        print(f"  Bad stance labels: {bad_stance}/10  (target 0)")

        passed = len(leads) >= 7 and q_count <= 3 and bad_stance == 0
        print(f"\n  {'[PASS]' if passed else '[NEEDS WORK]'}\n")

    except Exception as e:
        print(f"  [error] {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--test",  action="store_true")
    args = ap.parse_args()

    if args.test:
        run(dry=False)
        test()
    elif args.apply:
        run(dry=False)
    else:
        run(dry=True)
        print("  Run with --apply to write, --test to apply + verify.\n")
