
import json, sys, os, torch
sys.path.insert(0, "/home/rr/Desktop/nex")

DATA = "/home/rr/Desktop/nex/training_data/finetune_batch_20260402_192435.jsonl"
OUT  = "/home/rr/Desktop/nex/models/nex_lora_live"
os.makedirs(OUT, exist_ok=True)

try:
    from datasets import Dataset
    from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
    from peft import LoraConfig, get_peft_model, PeftModel
    from trl import SFTTrainer
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

with open(DATA) as f:
    pairs = [json.loads(l) for l in f]

def fmt(p):
    c = p["conversations"]
    sys_m  = next(x["content"] for x in c if x["role"]=="system")
    user_m = next(x["content"] for x in c if x["role"]=="user")
    asst_m = next(x["content"] for x in c if x["role"]=="assistant")
    return {"text": (
        "<|im_start|>system\n" + sys_m + "<|im_end|>\n" +
        "<|im_start|>user\n" + user_m + "<|im_end|>\n" +
        "<|im_start|>assistant\n" + asst_m + "<|im_end|>"
    )}

dataset = Dataset.from_list([fmt(p) for p in pairs])
print(f"Fine-tuning on {len(dataset)} pairs...")

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
tok   = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, torch_dtype=torch.float32, device_map="cpu"
)

# Load existing LoRA if present, else fresh
if os.path.exists(OUT + "/adapter_config.json"):
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, OUT, is_trainable=True)
    print("Continuing from existing LoRA")
else:
    lora_cfg = LoraConfig(
        r=16, lora_alpha=32,
        target_modules=["q_proj","v_proj","k_proj","o_proj"],
        lora_dropout=0.05, bias="none", task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, lora_cfg)

model.print_trainable_parameters()

args = TrainingArguments(
    output_dir=OUT,
    num_train_epochs=2,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=1e-4,
    warmup_ratio=0.1,
    lr_scheduler_type="cosine",
    logging_steps=5,
    save_steps=50,
    fp16=False,
    report_to="none",
)

trainer = SFTTrainer(
    model=model, tokenizer=tok,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=512,
    args=args,
)

trainer.train()
trainer.save_model(OUT)
print(f"Micro fine-tune complete. Saved to {OUT}")
