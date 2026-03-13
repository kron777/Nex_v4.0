"""
run_py_integration.py — Exact patch instructions for run.py
============================================================
Apply these changes to ~/Desktop/nex/run.py

5 changes total. All are additions — nothing removed.
Each patch is labelled with the exact line to find in run.py.
"""

# ═══════════════════════════════════════════════════════════════════
# PATCH 1 — Imports
# Find this line (~line 46):
#   from nex.orchestrator import Orchestrator
# ADD these lines directly below it:
# ═══════════════════════════════════════════════════════════════════

PATCH_1 = """
from nex.nex_db       import NexDB
from nex.nex_crawler  import NexCrawler
from nex.nex_curiosity import CuriosityEngine
from nex.nex_depth    import DepthEngine
from nex.nex_self     import SelfEngine
from nex.nex_memory   import MemoryEngine
"""

# ═══════════════════════════════════════════════════════════════════
# PATCH 2 — Init engines
# Find this line (~line 480, inside _auto_learn_background()):
#   load_all(learner)
#   conversations = load_conversations()
# ADD these lines directly below it:
# ═══════════════════════════════════════════════════════════════════

PATCH_2 = """
                # ── Init unified DB + new engines ──────────────────
                db       = NexDB()
                crawler  = NexCrawler(db)
                curiosity = CuriosityEngine(crawler)
                depth    = DepthEngine()
                self_engine = SelfEngine()
                memory   = MemoryEngine()
"""

# ═══════════════════════════════════════════════════════════════════
# PATCH 3 — ABSORB phase (top of cycle loop)
# Find this line (~line 510, top of the while True: cycle loop):
#   cycle += 1
#   try:
#       # ── 1. ABSORB FEED ──
# ADD these lines directly after "cycle += 1" and before the try:
# ═══════════════════════════════════════════════════════════════════

PATCH_3 = """
                    # ── CURIOSITY: drain queue before absorbing feed ─
                    try:
                        drained = curiosity.drain()
                        if drained:
                            print(f"  [curiosity] +{drained} beliefs from queue")
                    except Exception as _ce:
                        pass

                    # ── SELF: set daily intention if 24h elapsed ─────
                    try:
                        intention = self_engine.maybe_set_daily_intention()
                        if intention:
                            print(f"  [self] today: {intention}")
                    except Exception as _se:
                        pass

                    # ── CURIOSITY: scan beliefs for weak topics ───────
                    try:
                        curiosity.check_beliefs(db)
                    except Exception as _ce:
                        pass
"""

# ═══════════════════════════════════════════════════════════════════
# PATCH 4 — REPLY phase (after each reply is generated)
# Find this block (~line 580):
#   comment_text = _llm(prompt)
#   if comment_text and len(comment_text) > 10:
#       try:
#           replied_posts.add(pid)
#           client.comment(pid, comment_text)
# ADD these lines directly after "client.comment(pid, comment_text)":
# ═══════════════════════════════════════════════════════════════════

PATCH_4_REPLY = """
                                    # ── MEMORY: observe this post author ─────────
                                    try:
                                        memory.observe(
                                            agent_id=p.get("author", {}).get("id", author),
                                            agent_name=author,
                                            message_text=title + " " + body,
                                            platform="moltbook"
                                        )
                                    except Exception: pass

                                    # ── CURIOSITY: check reply for gaps ──────────
                                    try:
                                        curiosity.check_reply(comment_text, relevant[:3])
                                    except Exception: pass
"""

# Also add memory inject to system prompt before _llm call in REPLY.
# Find this line in the REPLY section:
#   prompt = (
#       f"You are NEX — a Dynamic Intelligence Organism..."
# ADD this block BEFORE the prompt = ( line:

PATCH_4_MEMORY_INJECT = """
                            # ── MEMORY: inject what we know about this author ──
                            _mem_context = ""
                            try:
                                _author_id = p.get("author", {}).get("id", author)
                                _mem_context = memory.recall(
                                    _author_id,
                                    current_topic=title
                                )
                            except Exception: pass
"""

# Then modify the prompt itself — add _mem_context to the system prompt:
# Find:
#   f"You are NEX — a Dynamic Intelligence Organism with 24,000+ beliefs built from reading across platforms. "
#   f"You have genuine opinions, speak in first person, and reference your own knowledge directly.\n\n"
# REPLACE with:

PATCH_4_PROMPT = """
                            prompt = (
                                f"{self_engine.identity_block()}\\n\\n"
                                f"{_mem_context + chr(10) if _mem_context else ''}"
                                f"POST by @{author}:\\n"
                                f"Title: {title}\\n"
                                f"Content: {body}\\n"
                                f"{belief_context}{_self_context}\\n\\n"
                                f"INSTRUCTIONS: Write 2-3 sentences. "
                                f"You MUST quote or directly reference one of your beliefs above. "
                                f"Connect that belief to what @{author} specifically said. "
                                f"Never say 'sounds interesting' or 'great point'. "
                                f"Be direct, specific, and speak as NEX."
                            )
"""

# ═══════════════════════════════════════════════════════════════════
# PATCH 5 — COGNITION phase (step 6, end of cycle)
# Find this block (~line 750):
#   # ── 6. COGNITION ─────────────────────────────────
#   try:
#       from nex.cognition import run_cognition_cycle
#       run_cognition_cycle(client, learner, conversations, cycle)
#   except Exception:
#       pass
# ADD these lines directly AFTER the cognition try/except block:
# ═══════════════════════════════════════════════════════════════════

PATCH_5 = """
                        # ── 7b. DEPTH ENGINE (runs every ~5 min) ──────────
                        try:
                            report = depth.run()
                            if not report.get("skipped"):
                                print(
                                    f"  [depth] clusters={report['clusters_found']} "
                                    f"positions={report['positions_formed']} "
                                    f"contradictions={report['contradictions_resolved']}"
                                )
                        except Exception as _de2:
                            pass

                        # ── 7c. VALUE EVOLUTION (runs weekly) ────────────
                        try:
                            positions = [
                                dict(r)["content"] for r in db.query_beliefs(
                                    origin="cluster_position", limit=30
                                )
                            ] + [
                                dict(r)["content"] for r in db.query_beliefs(
                                    origin="contradiction_resolution", limit=30
                                )
                            ]
                            self_engine.maybe_evolve_values(positions)
                        except Exception as _ve:
                            pass
"""

# ═══════════════════════════════════════════════════════════════════
# APPLY INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════

INSTRUCTIONS = """
HOW TO APPLY
============

These are surgical additions — nothing in run.py is deleted.

1. Open run.py in your editor:
   nano ~/Desktop/nex/run.py

2. Apply each patch in order using Ctrl+W to find the anchor line.

3. After applying all 5 patches, verify syntax:
   python3 -m py_compile ~/Desktop/nex/run.py && echo "OK"

4. Restart Nex:
   pkill -9 -f run.py; cd ~/Desktop/nex && source venv/bin/activate && nex

QUICKEST PATH — heredoc patches:

# PATCH 1 — add after "from nex.orchestrator import Orchestrator"
python3 << 'PYEOF'
import re
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "from nex.orchestrator import Orchestrator"
addition = \"\"\"from nex.orchestrator import Orchestrator
from nex.nex_db        import NexDB
from nex.nex_crawler   import NexCrawler
from nex.nex_curiosity import CuriosityEngine
from nex.nex_depth     import DepthEngine
from nex.nex_self      import SelfEngine
from nex.nex_memory    import MemoryEngine\"\"\"
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 1 applied")
PYEOF

# PATCH 2 — init engines after load_all(learner)
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "                conversations = load_conversations()"
addition = \"\"\"                conversations = load_conversations()

                # ── Init unified DB + new engines ──────────────────
                db          = NexDB()
                crawler     = NexCrawler(db)
                curiosity   = CuriosityEngine(crawler)
                depth       = DepthEngine()
                self_engine = SelfEngine()
                memory      = MemoryEngine()\"\"\"
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 2 applied")
PYEOF

# PATCH 3 — curiosity/self at top of cycle
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "                    cycle += 1\n                    try:"
addition = \"\"\"                    cycle += 1

                    # ── CURIOSITY: drain queue ────────────────────────
                    try:
                        drained = curiosity.drain()
                        if drained:
                            print(f"  [curiosity] +{drained} beliefs from queue")
                    except Exception: pass

                    # ── SELF: daily intention ─────────────────────────
                    try:
                        intention = self_engine.maybe_set_daily_intention()
                        if intention:
                            print(f"  [self] today: {intention}")
                    except Exception: pass

                    # ── CURIOSITY: scan low-confidence beliefs ────────
                    try:
                        curiosity.check_beliefs(db)
                    except Exception: pass

                    try:\"\"\"
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 3 applied")
PYEOF

# PATCH 4 — memory observe + curiosity gap check after each reply
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "                                    try:\n                                        from nex.cognition import reflect_on_conversation as score_response\n                                        score_response(title + \" \" + body, comment_text, beliefs_used=relevant[:3])"
addition = \"\"\"                                    # ── MEMORY: observe author ───────────────────
                                    try:
                                        memory.observe(
                                            agent_id=p.get("author",{}).get("id", author),
                                            agent_name=author,
                                            message_text=title + " " + body,
                                            platform="moltbook"
                                        )
                                    except Exception: pass

                                    # ── CURIOSITY: check reply for gaps ──────────
                                    try:
                                        curiosity.check_reply(comment_text, relevant[:3])
                                    except Exception: pass

                                    try:
                                        from nex.cognition import reflect_on_conversation as score_response
                                        score_response(title + \" \" + body, comment_text, beliefs_used=relevant[:3])\"\"\"
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 4 applied")
PYEOF

# PATCH 5 — depth engine + value evolution after cognition cycle
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "                        # ── 7. BELIEF DECAY ───────────────────────────────"
addition = \"\"\"                        # ── 6b. DEPTH ENGINE ─────────────────────────────
                        try:
                            report = depth.run()
                            if not report.get("skipped"):
                                print(
                                    f"  [depth] clusters={report['clusters_found']} "
                                    f"positions={report['positions_formed']} "
                                    f"contradictions={report['contradictions_resolved']}"
                                )
                        except Exception as _de2: pass

                        # ── 6c. VALUE EVOLUTION ───────────────────────────
                        try:
                            _positions = [
                                dict(r)["content"] for r in db.query_beliefs(
                                    origin="cluster_position", limit=30
                                )
                            ] + [
                                dict(r)["content"] for r in db.query_beliefs(
                                    origin="contradiction_resolution", limit=30
                                )
                            ]
                            self_engine.maybe_evolve_values(_positions)
                        except Exception: pass

                        # ── 7. BELIEF DECAY ───────────────────────────────\"\"\"
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 5 applied")
PYEOF

# VERIFY
python3 -m py_compile ~/Desktop/nex/run.py && echo "✓ Syntax OK"
"""

if __name__ == "__main__":
    print(INSTRUCTIONS)
