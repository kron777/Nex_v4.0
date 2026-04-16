#!/usr/bin/env python3
"""
FT#12 RunPod Training Script
Upload ft12_accumulator.jsonl alongside this script.
Run: python3 train_runpod.py
Output: nex_v5_ft12.gguf (download this)
"""
import json, sys, torch, os
from pathlib import Path

DATA   = Path('./ft12_accumulator.jsonl')
OUT    = Path('./nex_v5_ft12_lora')
MERGED = Path('./nex_v5_ft12_merged')
MODEL  = 'Qwen/Qwen2.5-3B-Instruct'

print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB" if torch.cuda.is_available() else "")

os.system("pip install -q transformers peft trl datasets accelerate bitsandbytes")

from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, PeftModel
from trl import SFTTrainer

with open(DATA) as f:
    pairs = [json.loads(l) for l in f if l.strip()]
print(f"Loaded {len(pairs)} pairs")

def fmt(p):
    msgs = p['messages']
    sys_m  = next(x['content'] for x in msgs if x['role']=='system')
    user_m = next(x['content'] for x in msgs if x['role']=='user')
    asst_m = next(x['content'] for x in msgs if x['role']=='assistant')
    return {'text': (
        f'<|im_start|>system\n{sys_m}<|im_end|>\n'
        f'<|im_start|>user\n{user_m}<|im_end|>\n'
        f'<|im_start|>assistant\n{asst_m}<|im_end|>'
    )}

dataset = Dataset.from_list([fmt(p) for p in pairs])

tok = AutoTokenizer.from_pretrained(MODEL)
tok.pad_token = tok.eos_token

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)

model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    quantization_config=bnb_config,
    device_map='auto',
)
model = prepare_model_for_kbit_training(model)
model.config.use_cache = False

lora_cfg = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=['q_proj','v_proj','k_proj','o_proj','gate_proj','up_proj','down_proj'],
    lora_dropout=0.05,
    bias='none',
    task_type='CAUSAL_LM',
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

args = TrainingArguments(
    output_dir=str(OUT),
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=2,
    learning_rate=2e-4,
    warmup_steps=20,
    lr_scheduler_type='cosine',
    logging_steps=10,
    save_steps=100,
    fp16=True,
    bf16=False,
    max_grad_norm=1.0,
    optim='adamw_torch',
    report_to='none',
)

trainer = SFTTrainer(
    model=model,
    tokenizer=tok,
    train_dataset=dataset,
    args=args,
    dataset_text_field='text',
    max_seq_length=512,
)

print("\nTraining FT#12...")
trainer.train()
trainer.save_model(str(OUT))
print(f"✓ LoRA saved")

# Merge
print("Merging LoRA into base...")
base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float16, device_map='cpu')
merged = PeftModel.from_pretrained(base, str(OUT))
merged = merged.merge_and_unload()
merged.save_pretrained(str(MERGED))
tok.save_pretrained(str(MERGED))
print(f"✓ Merged saved")

# Convert to GGUF
print("Converting to GGUF...")
os.system(f"pip install -q gguf")
os.system(f"python3 -c \"from transformers import AutoModelForCausalLM; print('ok')\"")
# Download llama.cpp convert script
os.system("wget -q https://raw.githubusercontent.com/ggml-org/llama.cpp/master/convert_hf_to_gguf.py")
os.system(f"python3 convert_hf_to_gguf.py {MERGED} --outtype q4_k_m --outfile nex_v5_ft12.gguf")
print("\n✓ DONE — download nex_v5_ft12.gguf")
