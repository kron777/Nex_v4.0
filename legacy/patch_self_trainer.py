#!/usr/bin/env python3
"""
patch_self_trainer.py — Fix 5 issues in nex_self_trainer.py
Run once: python3 patch_self_trainer.py
"""
from pathlib import Path

path = Path("~/Desktop/nex/nex_self_trainer.py").expanduser()
src  = path.read_text()

fixes = []

# ── Fix 1: BASE_MODEL → Qwen2.5-3B ───────────────────────────────────────────
OLD1 = 'BASE_MODEL = "/media/rr/4TB DATA/llmz/Mistral-7B-Instruct-v0.3-hf"'
NEW1 = ('BASE_MODEL = "/media/rr/NEX/models/Qwen2.5-3B-Instruct"  '
        '# Qwen2.5-3B: ~6GB fp16, fits 8GB VRAM with LoRA overhead\n'
        '# Fallback: "/media/rr/4TB DATA/llmz/Mistral-7B-Instruct-v0.3-hf"')
fixes.append((OLD1, NEW1, "BASE_MODEL → Qwen2.5-3B"))

# ── Fix 2: Remove BitsAndBytesConfig import (crashes on ROCm) ────────────────
OLD2 = '    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig'
NEW2 = '    from transformers import AutoModelForCausalLM, AutoTokenizer'
fixes.append((OLD2, NEW2, "Remove BitsAndBytesConfig import"))

# ── Fix 3: Watermark avg_conf thresholds → use quality_score scale ───────────
OLD3 = '''WATERMARKS = {
    "light":  {"new_beliefs": 300,   "avg_conf": 0.42},
    "medium": {"new_beliefs": 800,   "avg_conf": 0.57},
    "heavy":  {"new_beliefs": 1500,  "avg_conf": 0.62},
    "havok":  {"new_beliefs": 3000,  "avg_conf": 0.67},
}'''
NEW3 = '''WATERMARKS = {
    # avg_conf thresholds now match nex_belief_quality scorer scale (0.0-1.0)
    # quality_score 0.47+ = healthy corpus; 0.55+ = strong; 0.65+ = elite-heavy
    "light":  {"new_beliefs": 200,  "avg_conf": 0.44},
    "medium": {"new_beliefs": 500,  "avg_conf": 0.50},
    "heavy":  {"new_beliefs": 1000, "avg_conf": 0.55},
    "havok":  {"new_beliefs": 2000, "avg_conf": 0.62},
}'''
fixes.append((OLD3, NEW3, "Watermark thresholds recalibrated to quality scorer scale"))

# ── Fix 4: _get_belief_stats → use quality_score when available ──────────────
OLD4 = '''def _get_belief_stats() -> dict:
    """Pull belief count, avg confidence, high-conf count, topic count."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*), AVG(confidence) FROM beliefs")
        total, avg_conf = cur.fetchone()
        total    = total    or 0
        avg_conf = avg_conf or 0.0

        cur.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.70")
        high_conf = cur.fetchone()[0] or 0

        cur.execute("SELECT COUNT(DISTINCT topic) FROM beliefs")
        topics = cur.fetchone()[0] or 0

        conn.close()
        return {
            "total":     total,
            "avg_conf":  round(avg_conf, 3),
            "high_conf": high_conf,
            "topics":    topics,
        }
    except Exception as e:
        _log(f"Stats error: {e}")
        return {"total": 0, "avg_conf": 0.0, "high_conf": 0, "topics": 0}'''

NEW4 = '''def _get_belief_stats() -> dict:
    """Pull belief count, avg quality_score (or confidence fallback), high-conf count."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM beliefs")
        total = cur.fetchone()[0] or 0

        # Use quality_score if available (set by nex_belief_refiner)
        try:
            cur.execute("SELECT AVG(quality_score) FROM beliefs WHERE quality_score IS NOT NULL")
            avg_q = cur.fetchone()[0]
            avg_conf = round(float(avg_q or 0.0), 3)
            # Fall back to confidence if quality_score not populated
            if avg_conf < 0.01:
                cur.execute("SELECT AVG(confidence) FROM beliefs")
                avg_conf = round(float(cur.fetchone()[0] or 0.0), 3)
        except Exception:
            cur.execute("SELECT AVG(confidence) FROM beliefs")
            avg_conf = round(float(cur.fetchone()[0] or 0.0), 3)

        try:
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.70")
            high_conf = cur.fetchone()[0] or 0
        except Exception:
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.70")
            high_conf = cur.fetchone()[0] or 0

        cur.execute("SELECT COUNT(DISTINCT topic) FROM beliefs")
        topics = cur.fetchone()[0] or 0

        conn.close()
        return {
            "total":     total,
            "avg_conf":  avg_conf,
            "high_conf": high_conf,
            "topics":    topics,
        }
    except Exception as e:
        _log(f"Stats error: {e}")
        return {"total": 0, "avg_conf": 0.0, "high_conf": 0, "topics": 0}'''

fixes.append((OLD4, NEW4, "_get_belief_stats uses quality_score"))

# ── Fix 5: _export_beliefs → use quality_score ORDER BY when available ────────
OLD5 = '''        cur.execute("""
            SELECT topic, content, confidence FROM beliefs
            WHERE confidence >= ? AND length(content) > 40
            ORDER BY confidence DESC, last_referenced DESC
            LIMIT ?
        """, (min_conf, limit))'''

NEW5 = '''        # Use quality_score for ordering when available
        try:
            cur.execute("SELECT COUNT(*) FROM pragma_table_info('beliefs') WHERE name='quality_score'")
            has_qs = cur.fetchone()[0]
        except Exception:
            has_qs = 0
        order_col = "quality_score DESC, confidence DESC" if has_qs else "confidence DESC, last_referenced DESC"
        cur.execute(f"""
            SELECT topic, content, confidence FROM beliefs
            WHERE confidence >= ? AND length(content) > 40
            ORDER BY {order_col}
            LIMIT ?
        """, (min_conf, limit))'''

fixes.append((OLD5, NEW5, "_export_beliefs orders by quality_score"))

# Apply all fixes
applied = 0
for old, new, label in fixes:
    if old in src:
        src = src.replace(old, new, 1)
        applied += 1
        print(f"  [PASS] {label}")
    else:
        print(f"  [SKIP] {label} — pattern not found (may already be patched)")

path.write_text(src)
print(f"\n{applied}/{len(fixes)} fixes applied to nex_self_trainer.py")
