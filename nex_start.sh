#!/usr/bin/env bash
cd ~/Desktop/nex
source venv/bin/activate
python3 run.py --no-server 2>&1 | tee /tmp/nex_brain.log
