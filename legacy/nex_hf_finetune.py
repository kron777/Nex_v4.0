
import json, sys
from pathlib import Path

DATA = '/home/rr/Desktop/nex/training_data/voiced_pairs_v2.jsonl'
OUT  = '/home/rr/Desktop/nex/models/nex_lora'

try:
    from datasets import Dataset
    from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
    from peft import LoraConfig, get_peft_model
    from trl import SFTTrainer
except ImportError:
    print("pip install transformers peft trl datasets accelerate bitsandbytes")
    sys.exit(1)

with open(DATA) as f:
    pairs = [json.loads(l) for l in f]

def fmt(p):
    c = p['conversations']
    sys_m  = next(x['content'] for x in c if x['role']=='system')
    user_m = next(x['content'] for x in c if x['role']=='user')
    asst_m = next(x['content'] for x in c if x['role']=='assistant')
    return {'text': (
        f'<|im_start|>system\n{sys_m}<|im_end|>\n'
        f'<|im_start|>user\n{user_m}<|im_end|>\n'
        f'<|im_start|>assistant\n{asst_m}<|im_end|>'
    )}

dataset = Dataset.from_list([fmt(p) for p in pairs])
print(f"Dataset: {len(dataset)} examples")

# Use the model already running on this machine
import subprocess, re
try:
    ps = subprocess.check_output(['ps','aux']).decode()
    m = re.search(r'(-m|--model)\s+(\S+\.gguf)', ps)
    model_path = m.group(2) if m else None
except: model_path = None

# Fall back to HF model matching the 3B family
MODEL_ID = 'Qwen/Qwen2.5-3B-Instruct'
print(f"Base model: {MODEL_ID}")

import torch
tok = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, torch_dtype=torch.float16, device_map='auto'
)

lora_cfg = LoraConfig(
    r=16, lora_alpha=32,
    target_modules=['q_proj','v_proj','k_proj','o_proj'],
    lora_dropout=0.05, bias='none', task_type='CAUSAL_LM'
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

args = TrainingArguments(
    output_dir=OUT,
    num_train_epochs=3,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    warmup_ratio=0.1,
    lr_scheduler_type='cosine',
    logging_steps=10,
    save_steps=100,
    fp16=True,
    report_to='none',
)

trainer = SFTTrainer(
    model=model, tokenizer=tok,
    train_dataset=dataset,
    dataset_text_field='text',
    max_seq_length=512,
    args=args,
)

print("Training...")
trainer.train()
trainer.save_model(OUT)
print(f"Saved to {OUT}")
