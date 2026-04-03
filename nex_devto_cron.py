#!/usr/bin/env python3
import sys, requests
sys.path.insert(0, '/home/rr/Desktop/nex')

def llm(prompt, **kwargs):
    r = requests.post('http://localhost:8080/completion', json={
        'prompt': prompt, 'n_predict': 500, 'temperature': 0.7,
        'stop': ['<|im_end|>'], 'cache_prompt': False
    }, timeout=30)
    return r.json().get('content', '').strip()

from nex_devto import run_devto_publisher
run_devto_publisher(llm)
