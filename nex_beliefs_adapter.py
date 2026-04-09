"""
NEX BELIEFS ADAPTER
Provides belief access from beliefs.json for AGI Bridge 3 scripts.
Import this instead of reading DB directly.
"""
import json, logging
from pathlib import Path
from collections import defaultdict

log        = logging.getLogger("adapter")
CFG        = Path.home() / ".config/nex"
NEX        = Path.home() / "Desktop/nex"
BFILE      = CFG / "beliefs.json"

def load_raw() -> list:
    for p in [BFILE, NEX / "beliefs.json"]:
        if p.exists():
            try:
                d = json.loads(p.read_text())
                return d if isinstance(d, list) else list(d.values())
            except Exception as e:
                log.error(f"load {p}: {e}")
    return []

def get_belief_map(conn=None) -> dict:
    tm = defaultdict(list)
    for b in load_raw():
        t = b.get("topic") or "general"
        tm[t].append({
            "content":    b.get("content",""),
            "confidence": float(b.get("confidence") or b.get("quality_score") or 0.5),
            "source":     b.get("source") or b.get("origin") or "unknown",
            "stage":      b.get("belief_level") or "external",
            "rowid":      b.get("id",""),
        })
    return dict(tm)

def get_all_beliefs(conn=None) -> list:
    return [{
        "rowid":            b.get("id",""),
        "content":          b.get("content",""),
        "topic":            b.get("topic") or "general",
        "confidence":       float(b.get("confidence") or b.get("quality_score") or 0.5),
        "provenance_stage": b.get("belief_level") or "external",
        "reinforce_count":  int(b.get("reinforce_count") or b.get("use_count") or 0),
    } for b in load_raw()]

def get_high_confidence_beliefs(conn=None, threshold=0.72) -> list:
    return [b for b in get_all_beliefs() if b["confidence"] >= threshold]

def get_self_model(conn=None) -> dict:
    for p in [CFG/"self_model.json", NEX/"self_model.json"]:
        if p.exists():
            try: return json.loads(p.read_text())
            except: pass
    return {}

def get_recent_absorb_content(conn=None, hours: int = 24) -> list:
    out = []
    for fname in ["conversations.json","insights.json","synthesis_graph.json"]:
        for base in [CFG, NEX]:
            fp = base / fname
            if fp.exists():
                try:
                    raw = json.loads(fp.read_text())
                    items = raw if isinstance(raw,list) else list(raw.values())
                    for item in items[-300:]:
                        text = item if isinstance(item,str) else (
                            item.get("content") or item.get("text") or
                            item.get("message") or "") if isinstance(item,dict) else ""
                        if text: out.append({"content":str(text)[:400],"source":fname})
                except: pass
                break
    return out[:500]

def get_db(): return None
def ensure_prediction_table(conn=None): pass
def update_belief_confidence(conn, belief_id, new_confidence, note): pass
def flag_belief_for_revision(conn, belief_id, reason): pass
def save_predictions(preds):
    (CFG/"nex_predictions.json").write_text(json.dumps(preds, indent=2))
def load_predictions() -> list:
    p = CFG/"nex_predictions.json"
    try: return json.loads(p.read_text()) if p.exists() else []
    except: return []

# ── BELIEF REVISION SUPPORT ───────────────────────────────────────────────────
def update_belief_confidence_json(belief_id: str, new_confidence: float):
    """Update confidence in beliefs.json by ID."""
    bfile = Path.home() / ".config/nex/beliefs.json"
    try:
        beliefs = json.loads(bfile.read_text())
        for b in beliefs:
            if str(b.get("id","")) == str(belief_id):
                b["confidence"]   = new_confidence
                b["quality_score"] = new_confidence
        bfile.write_text(json.dumps(beliefs, indent=2))
    except Exception as e:
        log.error(f"update_belief_confidence_json: {e}")
