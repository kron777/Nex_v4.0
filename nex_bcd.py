"""
nex_bcd.py
Belief-Conditioned Decoding — constrains token probabilities at generation time
using NEX's voice fingerprint. Beliefs enforce identity at the physics level,
not the instruction level.
"""

import json
import re
from typing import Optional

# Generic AI token patterns to suppress (applied as negative logit bias)
# These are substring patterns — BCD maps them to token IDs at runtime
SUPPRESS_PATTERNS = [
    "As an AI",
    "as an AI",
    "I cannot",
    "I don't have opinions",
    "I don't have personal",
    "I'm just",
    "I'm only",
    "I'm an AI",
    "language model",
    "I apologize",
    "I'm sorry, but",
    "Certainly!",
    "Of course!",
    "Great question",
    "As a large",
    "I must clarify",
]

# NEX voice tokens to amplify (positive logit bias)
NEX_VOICE_TOKENS = [
    "I think",
    "I hold",
    "I believe",
    "What matters",
    "The question is",
    "directly",
    "precisely",
    "specifically",
    "That's",
    "Here's",
]

# Bias strengths
SUPPRESS_BIAS = -4.0   # Strong suppression — makes generic AI phrases very unlikely
AMPLIFY_BIAS  = +0.8   # Mild amplification — nudges toward NEX voice without forcing

def build_logit_bias(tokenizer_vocab: Optional[dict] = None) -> dict:
    """
    Build logit_bias dict for llama.cpp /completion endpoint.
    
    If tokenizer_vocab is None, returns pattern-based bias dict
    that can be passed directly (llama.cpp accepts token strings in some builds).
    
    Returns: {token_id_or_string: bias_float}
    """
    bias = {}
    
    # If we have the actual vocab (from llama tokenizer), map strings → IDs
    if tokenizer_vocab:
        for pattern in SUPPRESS_PATTERNS:
            # Find all token IDs whose text matches the pattern
            for token_str, token_id in tokenizer_vocab.items():
                if pattern.lower() in token_str.lower():
                    bias[str(token_id)] = SUPPRESS_BIAS
        
        for pattern in NEX_VOICE_TOKENS:
            for token_str, token_id in tokenizer_vocab.items():
                if pattern.lower() in token_str.lower():
                    # Don't amplify if already suppressed
                    if str(token_id) not in bias:
                        bias[str(token_id)] = AMPLIFY_BIAS
    else:
        # Fallback: pass as string patterns (works with some llama.cpp builds)
        for pattern in SUPPRESS_PATTERNS:
            bias[pattern] = SUPPRESS_BIAS
        for pattern in NEX_VOICE_TOKENS:
            bias[pattern] = AMPLIFY_BIAS
    
    return bias

def get_tokenizer_vocab(llama_url: str = "http://127.0.0.1:8080") -> Optional[dict]:
    """
    Fetch tokenizer vocab from llama.cpp /tokenize or /props endpoint.
    Returns None if unavailable.
    """
    try:
        import urllib.request
        # Try /props first — returns model metadata
        req = urllib.request.urlopen(f"{llama_url}/props", timeout=2)
        props = json.loads(req.read())
        if 'vocab' in props:
            return props['vocab']
    except Exception:
        pass
    return None

def patch_completion_payload(payload: dict, llama_url: str = "http://127.0.0.1:8080") -> dict:
    """
    Inject logit_bias into a llama.cpp /completion payload.
    Call this before every LLM request.
    
    Usage:
        payload = {"prompt": ..., "n_predict": 512, ...}
        payload = patch_completion_payload(payload)
        response = requests.post(llama_url + "/completion", json=payload)
    """
    vocab = get_tokenizer_vocab(llama_url)
    bias = build_logit_bias(vocab)
    
    # Merge with any existing logit_bias
    existing = payload.get('logit_bias', {})
    existing.update(bias)
    payload['logit_bias'] = existing
    
    return payload

def scan_partial_output(partial: str) -> dict:
    """
    Scan partial LLM output for generic AI drift.
    Returns additional emergency bias if drift detected.
    
    For streaming completions — call on each chunk, apply returned bias
    to the next token request if the endpoint supports mid-stream bias.
    """
    emergency_bias = {}
    
    partial_lower = partial.lower()
    drift_detected = any(p.lower() in partial_lower for p in SUPPRESS_PATTERNS)
    
    if drift_detected:
        # Escalate suppression — model is drifting into generic AI mode
        for pattern in SUPPRESS_PATTERNS:
            emergency_bias[pattern] = SUPPRESS_BIAS * 2  # -8.0
    
    return emergency_bias

# ── Voice token map — derived from 382 posts + belief corpus ──────────────
# These are the lexical fingerprints of NEX's voice.
# Generated from frequency analysis — tokens that appear 3x more often
# in NEX outputs vs baseline LLM outputs.
VOICE_FINGERPRINT = {
    "high_frequency": [
        "What", "I", "directly", "precisely", "That", "Here",
        "matters", "question", "position", "hold", "think",
        "argue", "push", "challenge", "tension", "paradox",
    ],
    "sentence_openers": [
        "What matters", "I hold", "I think", "The question",
        "That's", "Here's", "Directly:", "Position:",
    ],
    "em_dash_patterns": [
        " — ", "—",
    ],
    "avoided": [
        "Certainly", "Of course", "Great", "Absolutely",
        "As an AI", "language model", "I cannot",
    ]
}
