# nex_curiosity — run.py integration patch
# Add these snippets to the indicated locations in run.py
# =========================================================


# ── 1. IMPORTS (top of run.py, near other nex imports) ────────────────────

from nex.nex_crawler import NexCrawler
from nex.nex_curiosity import CuriosityEngine


# ── 2. INIT (after belief_store is ready) ─────────────────────────────────

crawler   = NexCrawler(belief_store)
curiosity = CuriosityEngine(crawler)


# ── 3. ABSORB phase — add these two lines at the very top of ABSORB ────────

# Drain anything Nex queued last cycle BEFORE fetching new feed
curiosity.drain()

# Scan beliefs for low-confidence topics and queue them
curiosity.check_beliefs(belief_store)

# ... rest of your existing ABSORB code follows unchanged ...


# ── 4. REPLY phase — after each reply is generated ─────────────────────────

# (find where you call reflect_on_conversation or store the reply)
# beliefs_used is already passed to reflect_on_conversation — use same list

curiosity.check_reply(nex_response, beliefs_used)

# That's it. Nex will now queue any topic she mentioned but had no beliefs for.


# ── 5. MORNING CHECK addition ──────────────────────────────────────────────
# Add to your existing morning check script:

"""
python3 -c "
import json, os
q = json.load(open(os.path.expanduser('~/.config/nex/curiosity_queue.json')))
print(f'Curiosity queue: {len(q[\"queue\"])} pending')
print(f'Topics crawled all-time: {len(q[\"crawled_topics\"])}')
for item in q['queue'][:5]:
    print(f'  - {item[\"topic\"]} ({item[\"reason\"]}, conf={item[\"confidence\"]:.0%})')
"
"""
