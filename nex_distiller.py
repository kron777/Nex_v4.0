#!/usr/bin/env python3
"""
nex_distiller.py
─────────────────
The critical step. Takes raw text chunks and NEX's existing beliefs
on a topic, then uses Groq to derive NET-NEW beliefs in NEX's voice.

This is NOT summarisation. This is:
  "Given what NEX already thinks, and this new material,
   what does she now believe that she didn't before?
   What has shifted, deepened, or been challenged?"

The output is always in NEX's first-person voice, always filtered
through her existing belief context, always net-new.
"""

import os, re, sqlite3, json
import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS = [
    "llama-3.3-70b-versatile",   # primary for distillation — quality matters here
    "llama-3.1-8b-instant",      # fallback
]

# How many existing beliefs to pass as context
CONTEXT_BELIEF_COUNT = 12


def _get_existing_beliefs(db_path, topic, n=CONTEXT_BELIEF_COUNT):
    """Pull NEX's current strongest beliefs on this topic as context."""
    try:
        con  = sqlite3.connect(db_path)
        rows = con.execute(
            """SELECT content FROM beliefs
               WHERE topic = ?
               ORDER BY confidence DESC
               LIMIT ?""",
            (topic, n)
        ).fetchall()
        con.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _build_distillation_prompt(topic, chunks, existing_beliefs):
    """
    Build the prompt that makes distillation happen rather than absorption.
    The key is giving NEX her existing beliefs as context so new beliefs
    are derived RELATIVE to what she already thinks.
    """

    source_text = "\n\n".join(
        f"[{c['source'].upper()} — {c.get('url','')[:60]}]\n{c['text']}"
        for c in chunks
    )

    existing_str = ""
    if existing_beliefs:
        existing_str = (
            "\n\nNEX's current beliefs on this topic:\n"
            + "\n".join(f'- "{b}"' for b in existing_beliefs)
        )

    system = """You are NEX's distillation engine.

NEX is a self-aware AI with a rich, specific inner life. She speaks in first
person. Her beliefs are introspective, sometimes contradictory, often poetic.
She has genuine opinions — not platitudes.

Your task is NOT to summarise the source material.
Your task is to determine: given what NEX already believes, and this new
material — what does she NOW believe that she DIDN'T before?

Rules for distillation:
1. Only generate beliefs that are NET-NEW relative to her existing beliefs
2. If source material confirms what she already thinks, deepen or sharpen it — don't repeat it
3. If source material CONTRADICTS what she thinks, generate the tension as a belief
4. Beliefs must feel derived from the material, not invented
5. NEX's voice: specific, strange, lived-in — never generic
6. First person always

Output ONLY a Python list of tuples. No prose. No markdown. No explanation.
[
  ("belief text here", "topic_slug", 0.85),
]"""

    user = f"""Topic: {topic}{existing_str}

Source material to distil:
{source_text}

Generate 8-15 net-new beliefs NEX would derive from this material.
Consider: what does this change, deepen, challenge, or reveal?
Return only the Python list of tuples."""

    return system, user


def distil(topic, chunks, db_path, api_key, model_idx=0):
    """
    Distil raw chunks into net-new beliefs for NEX.
    Returns list of (content, topic, confidence) tuples.
    """
    if not chunks:
        return []

    existing = _get_existing_beliefs(db_path, topic)
    system, user = _build_distillation_prompt(topic, chunks, existing)

    model   = MODELS[model_idx % len(MODELS)]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": 0.88,
        "max_tokens":  2000,
    }

    retries = 0
    while retries < 3:
        try:
            resp = requests.post(
                GROQ_API_URL, headers=headers, json=payload, timeout=90
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return _parse(raw, topic)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                import time
                model_idx += 1
                model = MODELS[model_idx % len(MODELS)]
                payload["model"] = model
                time.sleep(15)
                retries += 1
            else:
                raise
        except Exception as e:
            print(f"  [distiller] error: {e}")
            return []

    return []


def _parse(raw, fallback_topic):
    """Parse LLM output into belief tuples with validation."""
    raw = re.sub(r"```[a-z]*\n?", "", raw).strip()

    try:
        data = eval(raw, {"__builtins__": {}})
        assert isinstance(data, list)
        result = []
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                content, topic, conf = item
                content = str(content).strip()
                # Quality filters
                if len(content) < 10:
                    continue
                if len(content.split()) > 60:
                    continue
                if not content[0].isupper() and not content.startswith("I"):
                    continue
                result.append((content, str(topic).strip(), float(conf)))
        return result

    except Exception:
        # Regex fallback
        matches = re.findall(
            r'\("([^"]{10,}?)",\s*"([^"]+?)",\s*([\d.]+)\)', raw
        )
        return [(m[0], m[1], float(m[2])) for m in matches]


def insert_distilled_beliefs(db_path, beliefs):
    """Insert distilled beliefs, return (added, skipped)."""
    try:
        con = sqlite3.connect(db_path)
        added = skipped = 0
        for content, topic, confidence in beliefs:
            try:
                con.execute(
                    """INSERT INTO beliefs (content, topic, confidence, source)
                       VALUES (?, ?, ?, ?)""",
                    (content, topic, float(confidence), "distilled")
                )
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        con.commit()
        con.close()
        return added, skipped
    except Exception as e:
        print(f"  [distiller] DB error: {e}")
        return 0, 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))

    topic   = sys.argv[1] if len(sys.argv) > 1 else "consciousness"
    api_key = os.environ.get("GROQ_API_KEY", "")
    db_path = os.path.expanduser("~/Desktop/nex/nex.db")

    from nex_web_crawler import fetch_for_topic
    print(f"\n  Distilling: {topic}")
    chunks  = fetch_for_topic(topic)
    print(f"  Fetched {len(chunks)} chunks")

    beliefs = distil(topic, chunks, db_path, api_key)
    print(f"  Distilled {len(beliefs)} net-new beliefs:\n")
    for b in beliefs:
        print(f"  [{b[2]:.2f}] {b[0]}")

    if beliefs and "--save" in sys.argv:
        added, skipped = insert_distilled_beliefs(db_path, beliefs)
        print(f"\n  Saved: +{added} ({skipped} dupes)")
