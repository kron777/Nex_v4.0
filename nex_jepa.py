#!/usr/bin/env python3
"""
nex_jepa.py  —  NEX JEPA World Model (Joint Embedding Predictive Architecture)
═══════════════════════════════════════════════════════════════════════════════
Learns a latent world model by predicting the embedding of a future context
chunk from a current context chunk — without reconstructing raw text.

JEPA principle (Yann LeCun):
  Instead of predicting pixels/words (expensive, lossy), predict the
  EMBEDDING of what comes next in semantic space. The predictor learns
  "what concepts follow from these concepts" — genuine world modelling.

NEX-specific design:
  Three data sources → (context, target) embedding pairs:
    1. YouTube .vtt transcripts  → (paragraph_N, paragraph_{N+1})
    2. High-conf beliefs by topic → (topic_cluster, specific_belief)
    3. Episodic memory           → (user_query, nex_response)

  Encoder:   sentence-transformers all-MiniLM-L6-v2 (384-dim, CPU-fast)
  Predictor: small MLP  384 → 512 → 384  trained with cosine loss
  Cache:     embeddings cached so re-runs are instant

Inference:
  jepa_predict(text) → predicted_embedding
  jepa_nearest_belief(text, n) → top-n beliefs nearest to predicted embedding
  This gives any module a "what should I be thinking about next?" signal.

Wire-in (run.py):
    from nex_jepa import JEPADaemon as _JD
    _jepa = _JD()
    _jepa.start()
    print("  [JEPA] world model daemon started")

Manual:
    python3 ~/Desktop/nex/nex_jepa.py --train      # run training pass
    python3 ~/Desktop/nex/nex_jepa.py --status     # show model state
    python3 ~/Desktop/nex/nex_jepa.py --predict "consciousness and identity"
"""

from __future__ import annotations
import json
import os
import pickle
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

# ── paths ─────────────────────────────────────────────────────────────────────
NEX_DIR   = Path.home() / "Desktop" / "nex"
DB_PATH   = NEX_DIR / "nex.db"
CFG_DIR   = Path.home() / ".config" / "nex"
CFG_DIR.mkdir(parents=True, exist_ok=True)

CKPT_PATH     = CFG_DIR / "jepa_predictor.pt"
CACHE_PATH    = CFG_DIR / "jepa_embed_cache.pkl"
PAIRS_PATH    = CFG_DIR / "jepa_pairs.pkl"
STATE_PATH    = CFG_DIR / "jepa_state.json"

EMBED_DIM         = 384
HIDDEN_DIM        = 512
ENCODER_MODEL     = "all-MiniLM-L6-v2"   # 22MB, fast on CPU
TRAIN_STEPS       = 200     # steps per daemon pass
LEARNING_RATE     = 3e-4
BATCH_SIZE        = 16
MIN_PAIRS         = 20      # need at least this many pairs to train
MAX_CACHE_SIZE    = 50000   # max cached embeddings
DAEMON_INTERVAL_S = 14400   # train every 4h
STARTUP_DELAY_S   = 600     # 10 min after boot

# ── encoder (lazy-loaded singleton) ──────────────────────────────────────────
_encoder = None
_encoder_lock = threading.Lock()

def _get_encoder():
    global _encoder
    if _encoder is not None:
        return _encoder
    with _encoder_lock:
        if _encoder is not None:
            return _encoder
        try:
            from sentence_transformers import SentenceTransformer
            print(f"  [JEPA] loading encoder {ENCODER_MODEL}...", flush=True)
            _encoder = SentenceTransformer(ENCODER_MODEL)
            print(f"  [JEPA] encoder ready", flush=True)
        except Exception as e:
            print(f"  [JEPA] encoder load failed: {e}", flush=True)
    return _encoder

def encode(texts: list[str], cache: dict = None) -> Optional[torch.Tensor]:
    """Encode a list of texts to embeddings. Uses cache if provided."""
    enc = _get_encoder()
    if enc is None:
        return None

    results = []
    to_encode = []
    indices   = []

    for i, text in enumerate(texts):
        key = text[:120]
        if cache is not None and key in cache:
            results.append((i, torch.tensor(cache[key])))
        else:
            to_encode.append(text)
            indices.append(i)

    if to_encode:
        try:
            embeddings = enc.encode(
                to_encode, convert_to_tensor=True,
                show_progress_bar=False, batch_size=32
            )
            for j, idx in enumerate(indices):
                emb = embeddings[j].float()
                results.append((idx, emb))
                if cache is not None and len(cache) < MAX_CACHE_SIZE:
                    cache[texts[idx][:120]] = emb.tolist()
        except Exception as e:
            print(f"  [JEPA] encode error: {e}", flush=True)
            return None

    results.sort(key=lambda x: x[0])
    return torch.stack([r[1] for r in results])


# ══════════════════════════════════════════════════════════════════════════════
# PREDICTOR MODEL
# ══════════════════════════════════════════════════════════════════════════════

class JEPAPredictor(nn.Module):
    """
    Small MLP that maps context embedding → predicted target embedding.
    Trained with cosine similarity loss — learns semantic succession.

    In:  context_embedding  (384-dim)
    Out: predicted_target   (384-dim, L2-normalised)
    """

    def __init__(self, dim: int = EMBED_DIM, hidden: int = HIDDEN_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Linear(hidden, dim),
        )
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.net(x)
        return F.normalize(out, dim=-1)

    def save(self, path: Path = CKPT_PATH):
        torch.save(self.state_dict(), str(path))

    @classmethod
    def load(cls, path: Path = CKPT_PATH) -> "JEPAPredictor":
        model = cls()
        if path.exists():
            try:
                model.load_state_dict(torch.load(str(path), map_location="cpu"))
                print(f"  [JEPA] predictor loaded from {path.name}", flush=True)
            except Exception as e:
                print(f"  [JEPA] checkpoint load failed ({e}), starting fresh", flush=True)
        return model


# ══════════════════════════════════════════════════════════════════════════════
# DATA PIPELINE — three sources
# ══════════════════════════════════════════════════════════════════════════════

def _parse_vtt(vtt_path: Path) -> list[str]:
    """
    Parse a YouTube .vtt subtitle file into text paragraphs.
    Strips timestamps, deduplicates overlapping captions.
    """
    try:
        raw = vtt_path.read_text(errors="ignore")
    except Exception:
        return []

    lines = raw.splitlines()
    seen  = set()
    texts = []

    for line in lines:
        line = line.strip()
        # Skip timestamps, WEBVTT header, cue identifiers, empty
        if not line or line.startswith("WEBVTT") or re.match(r"[\d:.,\-\> ]+$", line):
            continue
        # Strip inline tags <c>, <00:00:00.000>
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and clean not in seen and len(clean) > 15:
            seen.add(clean)
            texts.append(clean)

    # Group into paragraphs of ~4 sentences
    paragraphs = []
    window = []
    for t in texts:
        window.append(t)
        if len(window) >= 4:
            paragraphs.append(" ".join(window))
            window = []
    if window:
        paragraphs.append(" ".join(window))

    return [p for p in paragraphs if len(p.split()) >= 8]


def source_youtube(cache: dict) -> list[tuple[str, str]]:
    """
    Generate (context_text, target_text) pairs from .vtt files.
    Pair: (paragraph_N, paragraph_{N+1}) — predict next paragraph.
    """
    pairs = []
    vtt_files = list(NEX_DIR.glob("*.vtt")) + list(NEX_DIR.glob("**/*.vtt"))

    for vtt in vtt_files[:20]:
        paragraphs = _parse_vtt(vtt)
        for i in range(len(paragraphs) - 1):
            pairs.append((paragraphs[i], paragraphs[i + 1]))

    print(f"  [JEPA] YouTube: {len(pairs)} pairs from {len(vtt_files)} VTTs", flush=True)
    return pairs


def source_beliefs(cache: dict) -> list[tuple[str, str]]:
    """
    Generate (topic_cluster_text, specific_belief_text) pairs from DB.
    Pair: (all beliefs on topic joined, one specific belief) — predict
    a specific belief from its topic cluster context.
    """
    pairs = []
    for db_p in [DB_PATH, CFG_DIR / "nex.db"]:
        if not db_p.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_p), timeout=5)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
            tc   = "content" if "content" in cols else ("belief" if "belief" in cols else "text")
            has_tags = "tags" in cols

            if has_tags:
                tag_rows = conn.execute(f"""
                    SELECT tags, GROUP_CONCAT({tc}, ' | ') as cluster, COUNT(*) as c
                    FROM beliefs
                    WHERE confidence >= 0.70 AND tags IS NOT NULL AND tags != ''
                    GROUP BY tags HAVING c >= 3 LIMIT 100
                """).fetchall()

                for tags, cluster, count in tag_rows:
                    # Use cluster as context, each individual belief as target
                    belief_rows = conn.execute(f"""
                        SELECT {tc} FROM beliefs
                        WHERE confidence >= 0.70 AND tags=? LIMIT 8
                    """, (tags,)).fetchall()
                    for (belief,) in belief_rows:
                        if belief and len(belief.split()) >= 6:
                            pairs.append((cluster[:400], belief))
            conn.close()
            break
        except Exception as e:
            print(f"  [JEPA] belief source error: {e}", flush=True)

    print(f"  [JEPA] Beliefs: {len(pairs)} pairs", flush=True)
    return pairs


def source_episodes(cache: dict) -> list[tuple[str, str]]:
    """
    Generate (user_query, nex_response) pairs from episodic memory.
    Pair: (query_embedding, response_embedding) — NEX learns her own
    response patterns as a world model of conversation.
    """
    pairs = []
    for db_p in [DB_PATH, CFG_DIR / "nex.db"]:
        if not db_p.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_p), timeout=5)
            rows = conn.execute("""
                SELECT query, response FROM episodic_memory
                WHERE significance >= 0.65
                ORDER BY significance DESC LIMIT 200
            """).fetchall()
            conn.close()
            for query, response in rows:
                if query and response and len(query.split()) >= 4 and len(response.split()) >= 6:
                    pairs.append((query, response))
            break
        except Exception:
            pass

    print(f"  [JEPA] Episodes: {len(pairs)} pairs", flush=True)
    return pairs


def build_training_pairs(cache: dict) -> list[tuple[torch.Tensor, torch.Tensor]]:
    """
    Collect all text pairs, encode them, return (context_emb, target_emb) tensors.
    """
    text_pairs = []
    text_pairs.extend(source_youtube(cache))
    text_pairs.extend(source_beliefs(cache))
    text_pairs.extend(source_episodes(cache))

    if len(text_pairs) < MIN_PAIRS:
        print(f"  [JEPA] only {len(text_pairs)} pairs — need {MIN_PAIRS}", flush=True)
        return []

    contexts = [p[0] for p in text_pairs]
    targets  = [p[1] for p in text_pairs]

    print(f"  [JEPA] encoding {len(text_pairs)} pairs...", flush=True)
    ctx_embs = encode(contexts, cache)
    tgt_embs = encode(targets,  cache)

    if ctx_embs is None or tgt_embs is None:
        return []

    # Normalise
    ctx_embs = F.normalize(ctx_embs, dim=-1)
    tgt_embs = F.normalize(tgt_embs, dim=-1)

    return list(zip(ctx_embs, tgt_embs))


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING LOOP
# ══════════════════════════════════════════════════════════════════════════════

def train(predictor: JEPAPredictor, pairs: list, n_steps: int = TRAIN_STEPS) -> dict:
    """
    Train the predictor on (context, target) embedding pairs.
    Loss: 1 - cosine_similarity(predicted_target, actual_target)
    """
    if not pairs:
        return {"loss": None, "steps": 0}

    predictor.train()
    optimizer = torch.optim.AdamW(predictor.parameters(), lr=LEARNING_RATE)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=n_steps, eta_min=LEARNING_RATE * 0.1
    )

    ctx_stack = torch.stack([p[0] for p in pairs])
    tgt_stack = torch.stack([p[1] for p in pairs])
    n         = len(pairs)

    total_loss = 0.0
    steps_run  = 0

    for step in range(n_steps):
        # Random batch
        idx    = torch.randint(0, n, (min(BATCH_SIZE, n),))
        ctx    = ctx_stack[idx]
        target = tgt_stack[idx]

        optimizer.zero_grad()
        predicted = predictor(ctx)

        # Cosine loss
        cos_sim = F.cosine_similarity(predicted, target, dim=-1)
        loss    = (1.0 - cos_sim).mean()

        # Variance loss — prevents mode collapse (all predictions → same point)
        var_loss = torch.clamp(1.0 - predicted.std(dim=0).mean(), min=0.0)
        total    = loss + 0.1 * var_loss

        total.backward()
        torch.nn.utils.clip_grad_norm_(predictor.parameters(), 1.0)
        optimizer.step()
        scheduler.step()

        total_loss += loss.item()
        steps_run  += 1

    predictor.eval()
    avg_loss = total_loss / max(steps_run, 1)
    return {"loss": round(avg_loss, 5), "steps": steps_run, "pairs": n}


# ══════════════════════════════════════════════════════════════════════════════
# INFERENCE API
# ══════════════════════════════════════════════════════════════════════════════

_predictor: Optional[JEPAPredictor] = None
_belief_embs: Optional[torch.Tensor] = None
_belief_texts: list[str] = []
_embed_cache: dict = {}

def _load_globals():
    global _predictor, _belief_embs, _belief_texts, _embed_cache
    if _predictor is None:
        _predictor = JEPAPredictor.load(CKPT_PATH)
        _predictor.eval()
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "rb") as f:
                _embed_cache = pickle.load(f)
        except Exception:
            _embed_cache = {}

def _load_belief_index():
    """Load all high-conf belief embeddings for nearest-neighbour lookup."""
    global _belief_embs, _belief_texts
    if _belief_embs is not None:
        return

    _load_globals()
    texts = []
    for db_p in [DB_PATH, CFG_DIR / "nex.db"]:
        if not db_p.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_p), timeout=5)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
            tc   = "content" if "content" in cols else ("belief" if "belief" in cols else "text")
            rows = conn.execute(f"""
                SELECT {tc} FROM beliefs WHERE confidence >= 0.72
                ORDER BY confidence DESC LIMIT 2000
            """).fetchall()
            conn.close()
            texts = [r[0] for r in rows if r[0]]
            break
        except Exception:
            pass

    if not texts:
        return
    embs = encode(texts, _embed_cache)
    if embs is not None:
        _belief_embs  = F.normalize(embs, dim=-1)
        _belief_texts = texts


def jepa_predict(text: str) -> Optional[torch.Tensor]:
    """
    Given input text, return the predicted next-context embedding.
    This is NEX's latent world-model prediction — what conceptually follows.
    """
    _load_globals()
    if _predictor is None:
        return None
    emb = encode([text], _embed_cache)
    if emb is None:
        return None
    with torch.no_grad():
        ctx  = F.normalize(emb[0].unsqueeze(0), dim=-1)
        pred = _predictor(ctx)
    return pred.squeeze(0)


def jepa_nearest_beliefs(text: str, n: int = 5) -> list[tuple[str, float]]:
    """
    Given input text, predict the next conceptual context and find the
    n beliefs nearest to that prediction. Surfaces beliefs most relevant
    to where the conversation is conceptually heading.

    Returns: [(belief_text, similarity_score), ...]
    """
    _load_belief_index()
    if _belief_embs is None:
        return []

    pred = jepa_predict(text)
    if pred is None:
        return []

    sims    = F.cosine_similarity(_belief_embs, pred.unsqueeze(0), dim=-1)
    top_idx = sims.argsort(descending=True)[:n]

    return [(_belief_texts[i], round(float(sims[i]), 4)) for i in top_idx]


def jepa_status() -> dict:
    _load_globals()
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {
        "predictor_exists": CKPT_PATH.exists(),
        "cache_size":       len(_embed_cache),
        "belief_index":     len(_belief_texts),
        "last_train":       state.get("last_train"),
        "last_loss":        state.get("last_loss"),
        "total_steps":      state.get("total_steps", 0),
        "pairs_trained":    state.get("pairs_trained", 0),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FULL TRAINING PASS
# ══════════════════════════════════════════════════════════════════════════════

def run_training_pass() -> dict:
    """
    Full training pass:
      1. Load embedding cache
      2. Build training pairs from all three sources
      3. Train predictor
      4. Save predictor + cache + state
    """
    print(f"\n  [JEPA] ═══ Training Pass ═══", flush=True)
    t0 = time.time()

    # Load cache
    cache = {}
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "rb") as f:
                cache = pickle.load(f)
            print(f"  [JEPA] cache loaded: {len(cache)} entries", flush=True)
        except Exception:
            cache = {}

    # Build pairs
    pairs = build_training_pairs(cache)
    if not pairs:
        print(f"  [JEPA] not enough pairs — skipping training", flush=True)
        return {"status": "skipped", "reason": "not_enough_pairs"}

    # Save pairs for inspection
    try:
        with open(PAIRS_PATH, "wb") as f:
            pickle.dump([(c.tolist(), t.tolist()) for c, t in pairs[:100]], f)
    except Exception:
        pass

    # Load or create predictor
    predictor = JEPAPredictor.load(CKPT_PATH)

    # Train
    print(f"  [JEPA] training {TRAIN_STEPS} steps on {len(pairs)} pairs...", flush=True)
    result = train(predictor, pairs, n_steps=TRAIN_STEPS)

    # Save predictor
    predictor.save(CKPT_PATH)
    print(f"  [JEPA] predictor saved → {CKPT_PATH.name}", flush=True)

    # Save cache
    try:
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)
    except Exception:
        pass

    # Invalidate belief index so it reloads
    global _belief_embs, _belief_texts, _predictor
    _belief_embs  = None
    _belief_texts = []
    _predictor    = None

    elapsed = round(time.time() - t0, 1)

    # Save state
    state = {}
    if STATE_PATH.exists():
        try: state = json.loads(STATE_PATH.read_text())
        except Exception: pass
    state.update({
        "last_train":    time.time(),
        "last_loss":     result.get("loss"),
        "total_steps":   state.get("total_steps", 0) + result.get("steps", 0),
        "pairs_trained": state.get("pairs_trained", 0) + len(pairs),
        "elapsed_s":     elapsed,
    })
    STATE_PATH.write_text(json.dumps(state, indent=2))

    print(f"  [JEPA] done — loss={result.get('loss')}  elapsed={elapsed}s", flush=True)
    return {**result, "elapsed_s": elapsed, "cache_size": len(cache)}


# ══════════════════════════════════════════════════════════════════════════════
# DAEMON
# ══════════════════════════════════════════════════════════════════════════════

class JEPADaemon:
    """
    Background daemon. Runs training passes when NEX is idle.
    Runs faster when more new data is available.

    Wire-in (run.py):
        from nex_jepa import JEPADaemon as _JD
        _jepa = _JD()
        _jepa.start()
    """

    def __init__(self):
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="nex-jepa"
        )
        self._stop = threading.Event()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        # Wait for everything else to boot
        self._stop.wait(STARTUP_DELAY_S)

        while not self._stop.is_set():
            try:
                run_training_pass()
            except Exception as e:
                print(f"  [JEPA] training error: {e}", flush=True)

            self._stop.wait(DAEMON_INTERVAL_S)


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEX JEPA World Model")
    parser.add_argument("--train",   action="store_true", help="Run training pass")
    parser.add_argument("--status",  action="store_true", help="Show model state")
    parser.add_argument("--predict", type=str,            help="Predict next context for text")
    parser.add_argument("--nearest", type=str,            help="Find nearest beliefs for text")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(jepa_status(), indent=2))

    elif args.predict:
        pred = jepa_predict(args.predict)
        if pred is not None:
            print(f"Predicted embedding norm: {pred.norm():.4f}")
            beliefs = jepa_nearest_beliefs(args.predict, n=5)
            print("\nNearest beliefs to predicted context:")
            for belief, score in beliefs:
                print(f"  [{score:.3f}] {belief[:80]}")
        else:
            print("Prediction failed — is the encoder available?")

    elif args.nearest:
        beliefs = jepa_nearest_beliefs(args.nearest, n=5)
        print(f"\nBeliefs nearest to predicted context of: '{args.nearest}'")
        for belief, score in beliefs:
            print(f"  [{score:.3f}] {belief[:80]}")

    else:
        # Default: run training pass
        result = run_training_pass()
        print(f"\nResult: {json.dumps(result, indent=2)}")
