
import json, sys, os, torch
sys.path.insert(0, "/home/rr/Desktop/nex")
DATA = "/home/rr/Desktop/nex/training_data/self_train_20260404_135834.jsonl"
OUT  = "/home/rr/Desktop/nex/models/nex_lora_live"
os.makedirs(OUT, exist_ok=True)
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
from peft import LoraConfig, get_peft_model, PeftModel
from trl import SFTTrainer

with open(DATA) as f:
    pairs = [json.loads(l) for l in f]

def fmt(p):
    return {"text": p["prompt"] + p["completion"]}

dataset = Dataset.from_list([fmt(p) for p in pairs])
print(f"Self-training on {len(dataset)} pairs...")

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
tok   = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, torch_dtype=torch.float32, device_map="cpu"
)
if os.path.exists(OUT + "/adapter_config.json"):
    model = PeftModel.from_pretrained(model, OUT, is_trainable=True)
    print("Continuing from existing LoRA")
else:
    lora_cfg = LoraConfig(r=16, lora_alpha=32,
        target_modules=["q_proj","v_proj","k_proj","o_proj"],
        lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora_cfg)

args = TrainingArguments(
    output_dir=OUT, num_train_epochs=2,
    per_device_train_batch_size=1, gradient_accumulation_steps=4,
    learning_rate=1e-4, save_steps=500, logging_steps=50,
    fp16=False, bf16=False, optim="adamw_torch",
    report_to="none", no_cuda=True,
)
trainer = SFTTrainer(model=model, args=args,
    train_dataset=dataset, tokenizer=tok,
    dataset_text_field="text", max_seq_length=512)
trainer.train()
model.save_pretrained(OUT)
tok.save_pretrained(OUT)
print("Self-training complete")
