#!/bin/bash
# Overnight CPU offload fine-tune
# Run: bash run_overnight_finetune.sh
# Takes 6-12 hours. Check logs/finetune_overnight.log
echo "Starting overnight fine-tune at $(date)"
cd /home/rr/Desktop/nex
source venv/bin/activate

# Update BASE_MODEL
sed -i 's|BASE_MODEL = ".*"|BASE_MODEL = "/media/rr/NEX/models/gemma-4-E4B-it"|' nex_self_trainer.py

# Set CPU offload env
export PYTORCH_HIP_ALLOC_CONF=expandable_segments:True
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export HIP_VISIBLE_DEVICES=0

# Run with CPU offload via device_map=auto
python3 -c "
import sys
sys.path.insert(0, '/home/rr/Desktop/nex')

# Patch trainer for CPU offload before importing
import re
path = '/home/rr/Desktop/nex/nex_self_trainer.py'
text = open(path).read()
# Switch to device_map=auto for CPU offload
text = text.replace('device_map={\"\"\: 0}', 'device_map=\"auto\"')
text = text.replace('device_map={\"\"\: torch.device(\"cpu\")}', 'device_map=\"auto\"')
open(path, 'w').write(text)
print('Trainer patched for CPU offload')

from nex_self_trainer import handle_training_command
def send(msg): 
    print(f'[FT] {msg}')
    with open('logs/finetune_overnight.log', 'a') as f:
        f.write(f'{msg}\\n')

handle_training_command('/light', send)
" 2>&1 | tee -a logs/finetune_overnight.log

echo "Fine-tune complete at $(date)"
