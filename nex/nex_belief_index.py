"""
nex_belief_index.py — O(k) inverted token index for belief retrieval.
Replaces O(N) linear scan in _load_all_beliefs().
"""
import os, re, json, time, threading
from pathlib import Path
from collections import defaultdict

_INDEX: dict = {}          # token → set of belief ids
_BELIEFS: dict = {}        # id → belief dict
_MTIME: float = 0.0
_LOCK = threading.Lock()

def _tokenise(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[a-z]{3,}", text.lower())]

def build_index(beliefs: list[dict]) -> None:
    """Call with the full belief list after loading from DB."""
    global _INDEX, _BELIEFS, _MTIME
    idx: dict = defaultdict(set)
    store: dict = {}
    for b in beliefs:
        bid = b.get("id") or b.get("belief_id") or id(b)
        store[bid] = b
        tokens = _tokenise(b.get("text", "") + " " + b.get("topic", ""))
        for tok in tokens:
            idx[tok].add(bid)
    with _LOCK:
        _INDEX   = dict(idx)
        _BELIEFS = store
        _MTIME   = time.time()
    print(f"  [BeliefIndex] built — {len(store)} beliefs indexed")

def query(text: str, top_k: int = 12) -> list[dict]:
    """Return top_k beliefs matching query tokens."""
    tokens = _tokenise(text)
    if not tokens or not _BELIEFS:
        return []
    scores: dict = defaultdict(int)
    with _LOCK:
        for tok in tokens:
            for bid in _INDEX.get(tok, set()):
                scores[bid] += 1
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    with _LOCK:
        return [_BELIEFS[bid] for bid, _ in ranked if bid in _BELIEFS]

def size() -> int:
    return len(_BELIEFS)
