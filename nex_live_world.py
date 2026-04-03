#!/usr/bin/env python3
"""
nex_live_world.py — Live World Model Orchestrator for NEX v4.0

Wires nex_world_model.py + nex_session_memory.py into the response pipeline.
Every conversation updates NEX's persistent world state.

Three operations:
  pre_response(query)     → returns world context string to inject into prompt
  post_response(q, r)     → extracts facts from response, updates world + session
  get_context(query)      → retrieve relevant world facts for a query

World state tracks:
  - Entities mentioned in conversation (people, orgs, topics, concepts)
  - Their properties as extracted by LLM
  - Session history (last N turns)
  - Conversation-derived beliefs flagged for graph injection

Usage in generate():
    from nex_live_world import pre_response, post_response
    world_ctx = pre_response(query)          # inject before prompt
    response  = llm_call(prompt + world_ctx)
    post_response(query, response)           # update world state after

CLI:
    python3 nex_live_world.py --stats
    python3 nex_live_world.py --show-entity "NEX"
    python3 nex_live_world.py --recent 5
"""

import json
import logging
import re
import sqlite3
import time
import requests
from pathlib import Path
from typing import Optional

log     = logging.getLogger("nex.live_world")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

# ── Config ────────────────────────────────────────────────────────────────────
MAX_WORLD_FACTS    = 5    # max facts to inject per response
MAX_SESSION_TURNS  = 3    # recent turns to inject
EXTRACT_ENABLED    = True # LLM extraction after response
MIN_RESPONSE_LEN   = 30   # skip extraction on very short responses

# ── Lazy singletons ───────────────────────────────────────────────────────────
_world_model   = None
_session_mem   = None


def _get_world():
    global _world_model
    if _world_model is None:
        from nex_world_model import WorldModel
        _world_model = WorldModel(DB_PATH)
    return _world_model


def _get_session():
    global _session_mem
    if _session_mem is None:
        from nex_session_memory import SessionMemory
        _session_mem = SessionMemory(DB_PATH)
    return _session_mem


# ── Entity extraction via LLM ─────────────────────────────────────────────────

EXTRACT_PROMPT = """Extract factual claims from this text. Return JSON only.
Format: [{{"entity": "name", "property": "attribute", "value": "fact"}}]
Rules:
- Only concrete, specific facts (not opinions or questions)
- entity = the subject (person, org, concept, system)
- property = what is being stated about it
- value = the fact itself (max 80 chars)
- Max 5 facts. If none, return []

Text: {text}

JSON:"""


def _extract_facts_llm(text: str) -> list[dict]:
    """Use LLM to extract entity-property-value triples from text."""
    if len(text.split()) < 10:
        return []
    try:
        prompt = EXTRACT_PROMPT.format(text=text[:400])
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 200,
            "temperature": 0.0,
            "stop": ["<|im_end|>", "<|im_start|>", "\n\n"],
            "cache_prompt": False,
        }, timeout=15)
        raw = r.json().get("content", "").strip()

        # Extract JSON array
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if not match:
            return []
        facts = json.loads(match.group(0))
        if not isinstance(facts, list):
            return []
        # Validate structure
        valid = []
        for f in facts:
            if (isinstance(f, dict) and
                    "entity" in f and "property" in f and "value" in f):
                valid.append({
                    "entity":   str(f["entity"])[:50],
                    "property": str(f["property"])[:50],
                    "value":    str(f["value"])[:100],
                })
        return valid[:5]
    except Exception as e:
        log.debug(f"Extraction error: {e}")
        return []


def _extract_facts_regex(text: str) -> list[dict]:
    """Fallback regex extraction for simple patterns."""
    facts = []
    patterns = [
        (r'\bNEX\s+(?:is|has|was)\s+([^,.]{5,60})', "NEX", "description"),
        (r'\bI\s+(?:am|have|hold|think|believe)\s+([^,.]{5,60})', "NEX", "self_state"),
    ]
    for pat, entity, prop in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            value = m.group(1).strip()
            if len(value) > 5:
                facts.append({"entity": entity, "property": prop, "value": value})
    return facts[:3]


# ── Pre-response: build world context for prompt injection ────────────────────

def pre_response(query: str, user_id: str = "default") -> str:
    """
    Called before LLM response generation.
    Returns a context string to inject into the prompt.
    Pulls: recent session turns + relevant world facts.
    """
    lines = []

    # 1. Recent session history
    try:
        session = _get_session()
        recent = session.get_recent(user_id=user_id, n=MAX_SESSION_TURNS)
        if recent:
            lines.append("Recent conversation:")
            for turn in recent[-MAX_SESSION_TURNS:]:
                role = turn.get("role", "?")
                content = turn.get("content", "")[:100]
                lines.append(f"  {role}: {content}")
            lines.append("")
    except Exception as e:
        log.debug(f"Session history error: {e}")

    # 2. Relevant world facts — extract key nouns from query
    try:
        wm = _get_world()
        # Find entities mentioned in query
        words = re.findall(r'\b[A-Z][a-z]+\b', query)
        words += ["NEX"]  # always include NEX's self-knowledge
        seen = set()
        fact_lines = []
        for word in words:
            if word in seen:
                continue
            seen.add(word)
            facts = wm.get(word)
            if facts:
                for prop, data in list(facts.items())[:2]:
                    if data["confidence"] >= 0.6:
                        fact_lines.append(
                            f"  {word} — {prop}: {data['value'][:80]}"
                        )
        if fact_lines:
            lines.append("Known world facts:")
            lines.extend(fact_lines[:MAX_WORLD_FACTS])
            lines.append("")
    except Exception as e:
        log.debug(f"World facts error: {e}")

    # Inject user model context
    try:
        from nex_user_model import get_user_context as _get_uctx
        user_ctx = _get_uctx()
        if user_ctx:
            lines.insert(0, user_ctx)
    except Exception:
        pass

    return "\n".join(lines) if lines else ""


# ── Post-response: update world state from conversation ───────────────────────

def post_response(query: str, response: str,
                  user_id: str = "default",
                  topic: str = "") -> dict:
    """
    Called after LLM response generation.
    Updates session history and extracts world facts.
    Returns summary of what was updated.
    """
    updated = {"session": False, "facts_extracted": 0, "facts_stored": 0}

    # 0. Update user model from conversation
    try:
        from nex_user_model import update_from_conversation as _um_update
        _um_update(query, response)
    except Exception:
        pass

    # 1. Store in session history
    try:
        session = _get_session()
        session.add("user",      query[:500],    user_id=user_id, topic=topic)
        session.add("assistant", response[:500], user_id=user_id, topic=topic)
        updated["session"] = True
    except Exception as e:
        log.debug(f"Session store error: {e}")

    # 2. Extract facts from response
    if not EXTRACT_ENABLED or len(response.split()) < MIN_RESPONSE_LEN // 3:
        return updated

    try:
        # Try LLM extraction first, fall back to regex
        facts = _extract_facts_llm(response)
        if not facts:
            facts = _extract_facts_regex(response)

        updated["facts_extracted"] = len(facts)

        # Store in world model
        wm = _get_world()
        stored = 0
        for fact in facts:
            try:
                wm.update(
                    entity=fact["entity"],
                    property=fact["property"],
                    value=fact["value"],
                    confidence=0.65,
                    source="conversation"
                )
                stored += 1
            except Exception:
                pass
        updated["facts_stored"] = stored
        log.debug(f"World update: {stored} facts stored from response")

    except Exception as e:
        log.debug(f"Post-response extraction error: {e}")

    return updated


# ── Context retrieval ─────────────────────────────────────────────────────────

def get_context(query: str) -> dict:
    """
    Get combined world + session context for a query.
    Returns structured dict for flexible injection.
    """
    ctx = {
        "session_turns": [],
        "world_facts": {},
        "context_str": "",
    }

    try:
        session = _get_session()
        ctx["session_turns"] = session.get_recent(n=MAX_SESSION_TURNS)
    except Exception:
        pass

    try:
        wm = _get_world()
        words = re.findall(r'\b[A-Z][a-z]+\b', query) + ["NEX"]
        for word in set(words):
            facts = wm.get(word)
            if facts:
                ctx["world_facts"][word] = facts
    except Exception:
        pass

    ctx["context_str"] = pre_response(query)
    return ctx


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="NEX live world model")
    parser.add_argument("--stats",       action="store_true")
    parser.add_argument("--show-entity", type=str, metavar="NAME")
    parser.add_argument("--recent",      type=int, metavar="N", default=5)
    parser.add_argument("--seed",        action="store_true", help="Seed NEX self-knowledge")
    args = parser.parse_args()

    if args.stats:
        wm = _get_world()
        s  = wm.stats()
        sm = _get_session()
        ss = sm.stats()
        print(f"\n{'═'*45}")
        print(f"  Live World Model Stats")
        print(f"{'═'*45}")
        print(f"  World facts   : {s['total_facts']:,}")
        print(f"  Entities      : {s['entities']:,}")
        print(f"  Session turns : {ss.get('total', 0):,}")
        print(f"{'═'*45}\n")
        return

    if args.show_entity:
        wm = _get_world()
        facts = wm.get(args.show_entity)
        if not facts:
            print(f"No facts known about '{args.show_entity}'")
        else:
            print(f"\nKnown about '{args.show_entity}':")
            for prop, data in facts.items():
                print(f"  {prop}: {data['value']} (conf={data['confidence']:.2f})")
        return

    if args.recent:
        sm = _get_session()
        turns = sm.get_recent(n=args.recent)
        if not turns:
            print("No session history found.")
        else:
            print(f"\nLast {args.recent} turns:")
            for t in turns:
                role = t.get("role", "?")
                content = t.get("content", "")[:100]
                print(f"  [{role}] {content}")
        return

    if args.seed:
        wm = _get_world()
        # Seed NEX self-knowledge from current system state
        db = sqlite3.connect(str(DB_PATH))
        belief_count = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        edge_count   = db.execute("SELECT COUNT(*) FROM belief_relations").fetchone()[0]
        db.close()

        wm.update("NEX", "type",          "Dynamic Intelligence Organism",     confidence=1.0, source="seed")
        wm.update("NEX", "model",         "Qwen2.5-3B fine-tuned (FT#7)",      confidence=1.0, source="seed")
        wm.update("NEX", "belief_count",  str(belief_count),                   confidence=1.0, source="seed")
        wm.update("NEX", "edge_count",    str(edge_count),                     confidence=1.0, source="seed")
        wm.update("NEX", "eval_score",    "88/100 STRONG",                     confidence=0.9, source="seed")
        wm.update("NEX", "fine_tunes",    "FT#1-7 complete",                   confidence=1.0, source="seed")
        wm.update("NEX", "llama_server",  "port 8080, systemd managed",        confidence=1.0, source="seed")
        wm.update("NEX", "identity",      "belief-graph AI, not prompt engine", confidence=1.0, source="seed")
        print(f"Seeded NEX self-knowledge ({belief_count:,} beliefs, {edge_count:,} edges)")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
