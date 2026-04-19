# Theory X — PATH 1 / PATH 2 Analysis
*Phase 1A, Task 2 deliverable. Source file: `nex/nex_respond_v2.py` (1084 lines).*
*Analysis date: 2026-04-19.*

---

## TL;DR

- There is no LRU cache. The "3ms short-circuit" is not a result cache — it is a
  **purely synchronous template-renderer** that produces a reply by concatenating
  retrieved belief strings with rotating openers/connectors/closers.
- PATH 1 is `_build_reply()` (line 715) invoked from `call_llm()` (line 787). It
  always wins whenever belief retrieval returns ≥1 string, because the output is
  deterministically ≥20 chars.
- PATH 2 is the `localhost:8080` HTTP call to llama-server (line 792). It is
  **effectively unreachable** in normal operation — it only fires when the belief
  retriever returns an empty list or `_build_reply()` returns a <20-char string.
- The "rotating opener + belief" pattern observed in fountain run 91b71678c6da
  (hops 2–4, 3ms latencies) is produced directly by PATH 1 — the openers come
  from the module-level `_OPENERS` / `_CONNECTORS` lists.
- `build_prompt()` (line 661) is called on every non-shortcut query. PATH 1 does
  **not** use its output — it re-parses the same belief list back out of the
  `user_m` string via regex at line 774. `build_prompt()`'s structured output is
  only meaningful if PATH 2 is reached.

---

## Question 1 — What is PATH 1?

PATH 1 is the **direct belief renderer**. Definition at `nex_respond_v2.py:715-756`:

```python
def _build_reply(query: str, beliefs: list, intent: str) -> str:
    """
    Build a reply directly from belief strings.
    No voice_gen SemanticIndex. No localhost:8080. Pure string assembly
    from our 23k-belief DB results.
    """
    if not beliefs:
        return None  # caller handles honest gap

    # Take up to 3 beliefs, prefer shorter ones for natural flow
    pool = sorted(beliefs[:5], key=len)[:3]
    parts = []
    if intent not in ("greeting", "self_inquiry"):
        opener = _random.choice(_OPENERS)
        parts.append(opener)
    # ... first belief capitalised + '.'
    # ... connector + second belief
    # ... occasional third belief
    # ... optional closer
    return " ".join(parts)
```

**Where it branches off.** `call_llm()` at line 787-790:

```python
# ── PATH 1: direct belief renderer ───────────────────────────────────────
result = _build_reply(query_clean, belief_lines, intent)
if result and len(result.strip()) > 20:
    log.info("PATH 1 (direct renderer) succeeded")
    return result
```

**What decides which path is taken.** Only one check: does `_build_reply` return a
string of >20 chars. Since the renderer deterministically includes at least one
opener (~15 chars) plus one belief (typically >50 chars), **any belief list with
≥1 non-trivial entry produces a PATH 1 return**. PATH 2 is reachable in exactly
two cases: (a) `belief_lines` is empty, (b) the lone belief is <5 chars. Neither
is common in a 23k-belief graph.

---

## Question 2 — What is PATH 2?

PATH 2 is the **HTTP call to llama-server** at `localhost:8080`. Defined at
`nex_respond_v2.py:792-819`:

```python
# ── PATH 2: localhost:8080 ────────────────────────────────────────────────
try:
    import requests as _req
    belief_block = "\n".join(f"- {b}" for b in belief_lines) if belief_lines else "(none)"
    our_system = (
        "You are Nex. Answer in 2-3 sentences using ONLY the beliefs listed. "
        "Address the specific topic. Do not open with loop phrases.\n\n"
        f"Beliefs:\n{belief_block}"
    )
    resp = _req.post(
        "http://localhost:8080/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": our_system},
                {"role": "user",   "content": query_clean},
            ],
            ...
        },
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()["choices"][0]["message"]["content"].strip()
    if result and len(result) > 20:
        log.info("PATH 2 (localhost:8080) succeeded")
        return result
```

**What triggers it.** The PATH 1 guard fails. In practice this means
`belief_lines == []` (no beliefs returned by the retriever). This happens when
the TF-IDF index yields no hits above threshold AND the keyword fallback also
returns nothing — very rare.

**The `our_system` prompt inside PATH 2 does NOT match `SYSTEM_PROMPT` at
line 205.** PATH 2 rebuilds its own system prompt from the belief list. So
`build_prompt()`'s carefully-constructed system+user pair (line 661) is never
sent as-is to the LLM. Its only use is as a carrier that PATH 1 re-parses via
regex.

---

## Question 3 — Is there a cache?

**No result cache.** There is no dict keyed on `(query, beliefs)` → `reply`.

There is however a **TF-IDF retrieval cache** at `_TFIDF_CACHE` (line 47) —
built once at first call via `_build_tfidf_index()` (line 90). This is a cache
of the belief *corpus*, not of reply results. It is invalidated only by process
restart (there is no explicit invalidation hook; new beliefs added to the DB
after first build are not in the index).

There is also a **schema cache** at `_SCHEMA_CACHE` (line 183) — purely a
one-time `PRAGMA table_info` read.

**The 3ms latencies seen on hops 2-4 of run 91b71678c6da are therefore NOT from
caching.** They are the cost of:

1. `get_beliefs_for_query()` — TF-IDF cosine (line 427) against the already-built
   matrix (~1–3ms for a 23k-belief corpus).
2. `_build_reply()` — pure string ops (~0.1ms).
3. `post_filter()` — regex dedupe (~0.1ms).

No neural inference happens at all. The graph retrieval runs, but the LLM is
skipped entirely.

---

## Question 4 — Is the fountain output PATH 1's rotating opener?

**Yes — confirmed.** The hop 2-4 outputs in `nex_experiments.db` run 91b71678c6da
were:

```
hop 2  (904ms)  "To be direct — From the second side we can say that exist an actual br..."
hop 3  (  3ms)  "The way I see it — From the second side we can say that exist an actua..."
hop 4  (  3ms)  "Honestly — From the second side we can say that exist an actual branch..."
```

"To be direct —", "The way I see it —", "Honestly —" are items #6, #3, #2 in
the `_OPENERS` list at `nex_respond_v2.py:692-701`:

```python
_OPENERS = [
    "Here's where I stand:",
    "Honestly —",
    "The way I see it —",
    "What I actually think:",
    "My position on this:",
    "To be direct —",
    "Here's what I hold:",
    "I'll be straight —",
]
```

Because `_build_reply` is called fresh each hop and the retrieved belief on this
query is stable ("from the second side..."), the same belief is wrapped with a
different random opener each time. 3ms latency is too fast to be LLM inference,
which confirms: **no LLM call is happening on hops 2-4.**

Hop 1 at 904ms was slower because it hit a different shortcut path — the
self-inquiry tripped `_shortcut_reply()` (line 886) which returns a canned
"I'm Nex — a belief system..." string. The 904ms on hop 1 is unrelated to LLM
inference; it is the first-call cost of `_build_tfidf_index()` paging 23k beliefs
into memory and computing the neighbor graph.

---

## Question 5 — How does `build_prompt` at line 661 interact with either path?

**`build_prompt` is a ghost step.** It is called unconditionally at line 1027
(`generate_reply`), and its output is passed to `call_llm(system, user_m)`.
Inside `call_llm`, the first thing that happens is a **regex re-parse** of
`user_m` to recover the query and belief list:

```python
# nex_respond_v2.py:772-774
q_match      = _re.search(r"Question:\s*(.+)$", prompt, _re.MULTILINE)
query_clean  = q_match.group(1).strip() if q_match else prompt.strip()
belief_lines = _re.findall(r"^[•\-]\s*(.+)$", prompt, _re.MULTILINE)
```

So `build_prompt`'s structured composition is immediately destructured. PATH 1
never sees `system` at all and reconstructs its own reply from `belief_lines`.
PATH 2 uses `belief_lines` but composes its own `our_system` prompt —
the `SYSTEM_PROMPT` constant and `intent_addon` are discarded.

The intent is partially recovered inside `call_llm` via two substring checks
(line 778-781) — "1-2 sentences max" and "growing belief system" — but these
are brittle string matches that would break if `SYSTEM_PROMPT` wording changed.

**Net effect.** `build_prompt` serves as a no-op carrier between retrieval and
rendering. Its presence is an architectural relic: the codebase used to use
voice_gen's SemanticIndex via structured prompts, and `build_prompt` was the
serialization layer. Since voice_gen was replaced by `_build_reply`, the
serialization has no consumer that uses the full structure — only PATH 2 does,
and PATH 2 almost never runs.

---

## Implications for Theory X

1. **Stage 1-5 scaffolding cannot ride on top of the current reply path without
   addressing PATH 1.** Any developmental scaffolding that attempts to shape the
   generation (e.g. sense-stream conditioning, self-model update, vantage
   generation) will be ignored because `_build_reply` does not consult it —
   it reads only `beliefs`, `query`, `intent`.

2. **The R8 fountain will collapse for architectural reasons, not cognitive
   ones.** Each hop's output is a rearrangement of the previous hop's retrieved
   beliefs. Given a stable query topic, retrieval returns a stable pool,
   `_build_reply` produces near-identical strings with rotating decorations,
   and semantic_collapse fires. This is mechanical, not a failure of cognition.

3. **R6 (vantage) is structurally blocked.** `_build_reply` has no mechanism
   for recursive self-reference. The recursive strike (#4) retrieved
   epistemology beliefs about "truth" because those matched keywords in
   "reflecting on being you" — PATH 1 then wrapped them in an opener. There is
   no way for vantage to arise from string concatenation of retrieval results.

4. **Bypass is trivial for experiments.** A single-line change in `call_llm`
   (skip the PATH 1 guard) routes everything through PATH 2. But PATH 2 itself
   still passes only retrieved beliefs to the LLM — the LLM cannot reason about
   recursion either unless given a different prompt structure.

5. **The deeper observation**: the codebase has a clean separation between
   "retrieval" (belief graph reasoning) and "voice" (LLM), but the current
   glue treats voice as window-dressing on retrieval. Theory X requires the
   opposite — retrieval should condition generation, not replace it.

---

## Artifacts referenced

- `nex/nex_respond_v2.py` (1084 lines) — full reply engine.
- `nex_experiments.db` → `fountain_log` table, run_id `91b71678c6da` (4 hops).
- `nex.db` → `strike_log` table, strikes 1-5 (last night's annotations).
- `nex_coherence_gate.py` — R2 gate, 15/15 passing, now active in Telegram.
