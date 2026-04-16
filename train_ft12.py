#!/usr/bin/env python3
"""FT#12 — CPU training, pure fp32, no GPU"""
import json, sys, torch
from pathlib import Path

DATA   = Path.home() / 'Desktop/nex/training_data/ft12_accumulator.jsonl'
OUT    = Path.home() / 'Desktop/nex/models/nex_v5_ft12'
MERGED = Path.home() / 'Desktop/nex/models/nex_v5_ft12_merged'
MODEL  = '/media/rr/NEX/models/Qwen2.5-3B-Instruct'

from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
from peft import LoraConfig, get_peft_model
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
print(f"Dataset: {len(dataset)} examples")

tok = AutoTokenizer.from_pretrained(MODEL)
tok.pad_token = tok.eos_token

# CPU only — no GPU
model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    torch_dtype=torch.float32,
    device_map='cpu',
    low_cpu_mem_usage=True,
)
model.config.use_cache = False

lora_cfg = LoraConfig(
    r=4,
    lora_alpha=8,
    target_modules=['q_proj','v_proj'],
    lora_dropout=0.05,
    bias='none',
    task_type='CAUSAL_LM',
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

args = TrainingArguments(
    output_dir=str(OUT),
    num_train_epochs=3,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    learning_rate=2e-4,
    warmup_steps=20,
    logging_steps=10,
    save_steps=200,
    fp16=False,
    bf16=False,
    max_grad_norm=1.0,
    optim='adamw_torch',
    report_to='none',
    dataloader_num_workers=0,
    no_cuda=True,
)

trainer = SFTTrainer(
    model=model,
    tokenizer=tok,
    train_dataset=dataset,
    args=args,
    dataset_text_field='text',
    max_seq_length=256,
)

print("\nStarting FT#12 CPU training...")
print("Expected time: 6-8 hours")
trainer.train()
trainer.save_model(str(OUT))
print(f"✓ LoRA saved to {OUT}")

# Merge
print("\nMerging...")
from peft import PeftModel
base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float16, device_map='cpu')
merged = PeftModel.from_pretrained(base, str(OUT))
merged = merged.merge_and_unload()
merged.save_pretrained(str(MERGED))
tok.save_pretrained(str(MERGED))
print(f"✓ Merged to {MERGED}")
print(f"\nConvert to GGUF:")
print(f"python3 /media/rr/NEX/llama.cpp/convert_hf_to_gguf.py {MERGED} --outtype q4_k_m --outfile ~/Desktop/nex/models/nex_v5_ft12.gguf")
