import subprocess

override = """[Service]
ExecStart=
ExecStart=/media/rr/NEX/llama.cpp/build/bin/llama-server -m /home/rr/Desktop/nex/models/nex_v5_q4km.gguf -ngl 20 --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0 -c 2048 --port 8080 --host 0.0.0.0
"""

import os
os.makedirs('/etc/systemd/system/nex-llama.service.d', exist_ok=True)
with open('/etc/systemd/system/nex-llama.service.d/override.conf', 'w') as f:
    f.write(override)
print('override written')

subprocess.run(['systemctl', 'daemon-reload'], check=True)
print('daemon reloaded')

subprocess.run(['systemctl', 'restart', 'nex-llama'], check=True)
print('nex-llama restarted')
