#!/usr/bin/env python3
"""Fix gradient checkpointing conflict with LoRA on ROCm."""
from pathlib import Path

path = Path("~/Desktop/nex/nex_self_trainer.py").expanduser()
src  = path.read_text()

# Fix 1: Remove model.gradient_checkpointing_enable() — conflicts with LoRA on ROCm
old1 = "    model.gradient_checkpointing_enable()\n    trainer = SFTTrainer("
new1 = "    # gradient_checkpointing disabled — conflicts with LoRA on ROCm\n    model.config.use_cache = False\n    trainer = SFTTrainer("
if old1 in src:
    src = src.replace(old1, new1)
    print("Fixed: removed gradient_checkpointing_enable()")
else:
    print("Pattern 1 not found")

# Fix 2: Disable gradient_checkpointing in SFTConfig
old2 = "        fp16=_use_gpu,"
new2 = "        fp16=_use_gpu,\n        gradient_checkpointing=False,"
if old2 in src:
    src = src.replace(old2, new2)
    print("Fixed: disabled gradient_checkpointing in SFTConfig")
else:
    print("Pattern 2 not found")

path.write_text(src)
print("Done")
