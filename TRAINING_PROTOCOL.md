# NEX Training Protocol — RX 6600 LE (8GB VRAM)

## Hardware
- GPU: AMD Radeon RX 6600 LE (8GB VRAM)
- CPU: AMD Ryzen 7 5800X
- RAM: 24GB
- Storage: 1TB HDD + 4TB data drive

## Pre-training checklist
1. Kill llama-server first — it uses ~3GB VRAM
```
   pkill -9 -f "llama-server"
```
2. Verify VRAM free ≥ 7GB before starting

## Launch command
```bash
cd ~/Desktop/nex && source venv/bin/activate
HSA_OVERRIDE_GFX_VERSION=10.3.0 HIP_VISIBLE_DEVICES=0 \
python3 -c "
from nex_self_trainer import handle_training_command
def send(msg): print(f'[TG] {msg}')
handle_training_command('/light', send)
"
```

## Key fixes applied
- `torch_dtype=` → `dtype=` (transformers deprecation)
- `device_map="auto"` → `device_map={"":0}` (ROCm explicit GPU)
- `dtype=torch.float16` (fp16 = ~6.4GB, fits in 8GB)
- `t.join()` added after `t.start()` in handle_training_command (prevents daemon thread abort)
- BitsAndBytes removed — incompatible with ROCm GFX 10.3.0
- PyTorch: 2.5.1+rocm6.2 (NOT cuda build)

## After training completes
Restart llama-server manually.

## Intensity VRAM estimates (fp16)
- light/medium/heavy/havok: all ~6.4GB model + ~0.5GB LoRA overhead = safe

## Post-training GGUF workflow
1. Convert merged model: --outtype f16 (NOT q4_k_m)
2. Quantize f16 → q8_0 (f16 too large for 8GB VRAM context buffers)
   llama-quantize nex_light_v1.gguf nex_light_v1_q8.gguf q8_0
3. Load with: --n-gpu-layers 28 --ctx-size 2048
4. Verify: curl http://localhost:8080/v1/models

## Trained model location
/media/rr/4TBDATA/llmz/nex_trained/nex_light_v1_q8.gguf
