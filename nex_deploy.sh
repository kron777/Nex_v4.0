#!/bin/bash
# NEX Deploy — merge adapter → GGUF → q8 → restart server
set -e

ADAPTER_DIR="${1:-/home/rr/Desktop/nex/nex_trained/run_voice/final}"
BASE_MODEL="/media/rr/NEX/models/Qwen2.5-3B-Instruct"
MERGED_DIR="/home/rr/Desktop/nex/nex_trained/merged_voice"
GGUF_F16="/media/rr/NEX/llmz/nex_voice_v1.gguf"
GGUF_Q8="/media/rr/NEX/llmz/nex_voice_v1_q8.gguf"
LLAMA_SERVER="/media/rr/NEX/llama.cpp/build/bin/llama-server"
CONVERT="/media/rr/NEX/llama.cpp/convert_hf_to_gguf.py"

echo "=== NEX Deploy ==="
echo "Adapter: $ADAPTER_DIR"

# Step 1 — merge
echo "[1/4] Merging adapter..."
pkill -9 -f "llama-server" 2>/dev/null || true
sleep 2

HSA_OVERRIDE_GFX_VERSION=10.3.0 HIP_VISIBLE_DEVICES=0 \
/home/rr/Desktop/nex/venv/bin/python3 - << EOF
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch, shutil, os

base = AutoModelForCausalLM.from_pretrained("$BASE_MODEL", torch_dtype=torch.float16, device_map="cpu")
model = PeftModel.from_pretrained(base, "$ADAPTER_DIR")
model = model.merge_and_unload()
os.makedirs("$MERGED_DIR", exist_ok=True)
model.save_pretrained("$MERGED_DIR")
tok = AutoTokenizer.from_pretrained("$ADAPTER_DIR")
tok.save_pretrained("$MERGED_DIR")
print("Merge done.")
EOF

# Step 2 — convert
echo "[2/4] Converting to GGUF f16..."
/home/rr/Desktop/nex/venv/bin/python3 $CONVERT $MERGED_DIR --outtype f16 --outfile $GGUF_F16

# Step 3 — quantize
echo "[3/4] Quantizing to q8_0..."
$LLAMA_SERVER/../llama-quantize $GGUF_F16 $GGUF_Q8 q8_0

# Step 4 — restart server
echo "[4/4] Starting llama-server..."
HSA_OVERRIDE_GFX_VERSION=10.3.0 HIP_VISIBLE_DEVICES=0 \
$LLAMA_SERVER \
  --model $GGUF_Q8 \
  --n-gpu-layers 28 \
  --ctx-size 2048 \
  --port 8080 &

sleep 15
curl -s http://localhost:8080/health && echo " Server healthy." || echo " Server failed."
echo "=== Deploy complete ==="
