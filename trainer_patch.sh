#!/bin/bash
# trainer_patch.sh — wire nex_trainer into run.py
# Run: bash ~/Desktop/nex/trainer_patch.sh

# PATCH 1 — import NexConfig and SelfTrainer
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "from nex.nex_db        import NexDB"
addition = """from nex.nex_db        import NexDB
from nex.nex_trainer   import SelfTrainer, NexConfig"""
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 1 applied")
PYEOF

# PATCH 2 — init NexConfig and SelfTrainer after other engines
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "                memory      = MemoryEngine()"
addition = """                memory      = MemoryEngine()
                nex_config  = NexConfig()
                trainer     = SelfTrainer(nex_config, self_engine=self_engine)"""
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 2 applied")
PYEOF

# PATCH 3 — replace hardcoded temperature in _llm() with config values
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = '                try:\n                r = _req.post("http://localhost:8080/completion", json={\n                    "prompt": f"[INST] {system}\\n\\n{prompt} [/INST]",\n                    "n_predict": 200,\n                    "temperature": 0.75,\n                    "stop": ["</s>", "[INST]", "\\n\\n\\n"]\n                }, timeout=60)'
# If exact match fails, try the simpler temperature line only
import re
# Replace just the temperature and n_predict in the local llm function
src = re.sub(
    r'("n_predict": )200,\n(\s+"temperature": )0\.75,',
    r'\g<1>nex_config.get_llm_params().get("max_tokens", 200),\n\2nex_config.get_llm_params().get("temperature", 0.75),\n                    "top_p": nex_config.get_llm_params().get("top_p", 0.90),\n                    "repeat_penalty": nex_config.get_llm_params().get("repeat_penalty", 1.10),',
    src, count=1
)
open(path, "w").write(src)
print("PATCH 3 applied")
PYEOF

# PATCH 4 — add metrics collection and trainer.maybe_propose() in REFLECT
python3 << 'PYEOF'
path = "/home/rr/Desktop/nex/run.py"
src = open(path).read()
anchor = "                        # ── 6b. DEPTH ENGINE ─────────────────────────────"
addition = """                        # ── 6a. TRAINER: check if retraining needed ───────
                        try:
                            _ref_stats = db.get_reflection_stats()
                            _conf_row  = db.get(
                                "SELECT AVG(confidence) as a FROM beliefs"
                            )
                            _hconf_row = db.get(
                                "SELECT COUNT(*) as c FROM beliefs WHERE confidence > 0.70"
                            )
                            _train_metrics = {
                                "topic_alignment":  _ref_stats.get("avg_alignment", 0) or 0,
                                "avg_confidence":   (_conf_row["a"] if _conf_row else 0) or 0,
                                "high_conf_count":  (_hconf_row["c"] if _hconf_row else 0),
                                "reflection_score": _ref_stats.get("avg_alignment", 0) or 0,
                                "cycle_count":      cycle,
                            }
                            trainer.maybe_propose(_train_metrics)
                        except Exception as _te: pass

                        # ── 6b. DEPTH ENGINE ─────────────────────────────"""
src = src.replace(anchor, addition, 1)
open(path, "w").write(src)
print("PATCH 4 applied")
PYEOF

# VERIFY
python3 -m py_compile ~/Desktop/nex/run.py && echo "✓ Syntax OK" || echo "✗ Syntax error"
