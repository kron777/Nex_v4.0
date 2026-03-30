import os
import re

def patch_file(path, search_pattern, replacement, is_regex=False):
    if not os.path.exists(path):
        print(f"Skipping {path} (not found)")
        return
    
    with open(path, 'r') as f:
        content = f.read()
    
    if is_regex:
        new_content = re.sub(search_pattern, replacement, content)
    else:
        new_content = content.replace(search_pattern, replacement)
        
    if new_content != content:
        with open(path, 'w') as f:
            f.write(new_content)
        print(f"Patched: {path}")
    else:
        print(f"No changes needed or already patched: {path}")

# --- CONFIGURATION ---
NEX_DIR = os.path.expanduser("~/Desktop/nex")
os.chdir(NEX_DIR)

print("Starting surgical voice patch...")

# 1. Strip "bridge:" from the belief content retrieval
patch_file(
    "nex/belief_bridge.py",
    'content = b.get("content", "")[:150].replace("\\n", " ")',
    'content = b.get("content", "").replace("bridge:", "").replace("BRIDGE:", "").strip()[:150].replace("\\n", " ")'
)

# 2. Remove the "which connects to —" hardcoded connector
patch_file(
    "nex/nex_belief_graph.py",
    'chain.append(f"{b1} which connects to — {b2}")',
    'chain.append(f"{b1}. {b2}")'
)

# 3. Clean up the synthesizer's " And — " joining logic
patch_file(
    "nex/nex_synthesizer.py",
    'return " And — ".join(chain)',
    'return " ".join(chain)'
)

# 4. Global character engine strip (Final safety net)
patch_file(
    "nex_character_engine.py",
    'text = text.replace("\\n", " ")',
    'text = text.replace("bridge:", "").replace("BRIDGE:", "").replace("\\n", " ")'
)

print("\nPatching complete. Nex's voice is now clean.")
