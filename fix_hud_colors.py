#!/usr/bin/env python3
"""
Fix nex_hud.html:
1. Remove duplicate fetchYT
2. YouTube streams WITH other notes (addStream not just addResponse)
3. Color scheme: REPLIED=purple, POSTED=green, CHATTED=cyan,
   YOUTUBE=blue, MOLTBOOK=green, BELIEF=yellow, ERROR=red, others=dim
"""
import re

path = "/home/rr/Desktop/nex/nex_hud.html"
with open(path) as f:
    src = f.read()

# ── 1. Remove ALL existing fetchYT definitions (keep only one) ────────────────
# Strip everything between first fetchYT and the second closing block
src = re.sub(
    r'async function fetchYT\(\).*?fetchYT\(\);\s*\n',
    '', src, count=1, flags=re.DOTALL
)
# Also remove the duplicate labelled block
src = re.sub(
    r'// ── YouTube feed.*?fetchYT\(\);\s*\n\s*\n',
    '', src, count=1, flags=re.DOTALL
)

# ── 2. Fix RESPONSE_COLORS ────────────────────────────────────────────────────
src = src.replace(
    "const RESPONSE_COLORS = {\n  REPLIED: 'var(--purple)',\n  CHATTED: 'var(--cyan)',\n  POSTED:  'var(--green)',\n  YOUTUBE: '#ff6b6b',",
    "const RESPONSE_COLORS = {\n  REPLIED:  'var(--purple)',\n  CHATTED:  'var(--cyan)',\n  POSTED:   'var(--green)',\n  YOUTUBE:  '#4da6ff',\n  MOLTBOOK: 'var(--green)',\n  BELIEF:   'var(--yellow)',\n  LEARNT:   'var(--yellow)',\n  ERROR:    'var(--red)',\n  SOUL:     '#a0a0ff',"
)

# ── 3. Fix RESPONSE_TYPES to include all types ────────────────────────────────
src = src.replace(
    "const RESPONSE_TYPES = new Set(['REPLIED','CHATTED','POSTED','YOUTUBE']);",
    "const RESPONSE_TYPES = new Set(['REPLIED','CHATTED','POSTED','YOUTUBE','MOLTBOOK','BELIEF','LEARNT','SOUL']);"
)

# ── 4. Add single clean fetchYT that uses addStream (streams with other notes) ─
old_interval = "setInterval(fetchAgi,10000);\nfetchAgi();"
new_interval = """setInterval(fetchAgi,10000);
fetchAgi();
// ── YouTube feed — streams into responses panel with other notes ──────────────
let _ytSeen = new Set();
async function fetchYT() {
  try {
    const r = await fetch('http://localhost:7700/yt_feed', {signal: AbortSignal.timeout(2000)});
    const d = await r.json();
    if (d.entries && Array.isArray(d.entries)) {
      d.entries.forEach(e => {
        const key = e.text;
        if (!_ytSeen.has(key)) {
          _ytSeen.add(key);
          const t = e.time || ts();
          addStream(t, 'YOUTUBE', e.text || '');
        }
      });
    }
  } catch(e) {}
}
setInterval(fetchYT, 15000);
setTimeout(fetchYT, 3000);"""

if old_interval in src:
    src = src.replace(old_interval, new_interval)
    print("✓ fetchYT added (streams with other notes)")
else:
    print("! fetchAgi interval not found")

# ── 5. Fix addStream type detection for better colors ────────────────────────
old_type_detect = """        if (msg.includes('REPLIED') || msg.includes('replied')) type = 'REPLIED';
        else if (msg.includes('inferred') || msg.includes('belief')) type = 'BELIEF';
        else if (msg.includes('posted') || msg.includes('POSTED')) type = 'POSTED';
        else if (msg.includes('learnt') || msg.includes('seeder')) type = 'LEARNT';
        else if (msg.includes('KERNEL') || msg.includes('soul')) type = 'SOUL';
        else if (msg.includes('ERROR') || msg.includes('error')) type = 'ERROR';
        else if (msg.includes('chatted') || msg.includes('CHAT')) type = 'CHATTED';"""

new_type_detect = """        if (msg.includes('REPLIED') || msg.includes('replied') || msg.includes('[notif]')) type = 'REPLIED';
        else if (msg.includes('POSTED') || msg.includes('posted')) type = 'POSTED';
        else if (msg.includes('chatted') || msg.includes('CHAT')) type = 'CHATTED';
        else if (msg.includes('[YouTube]') || msg.includes('youtube')) type = 'YOUTUBE';
        else if (msg.includes('Moltbook') || msg.includes('moltbook') || msg.includes('MOLTBOOK')) type = 'MOLTBOOK';
        else if (msg.includes('inferred') || msg.includes('[BELIEF]') || msg.includes('belief')) type = 'BELIEF';
        else if (msg.includes('learnt') || msg.includes('seeder') || msg.includes('LEARNT')) type = 'LEARNT';
        else if (msg.includes('KERNEL') || msg.includes('soul') || msg.includes('SOUL')) type = 'SOUL';
        else if (msg.includes('ERROR') || msg.includes('error') || msg.includes('failed')) type = 'ERROR';"""

if old_type_detect in src:
    src = src.replace(old_type_detect, new_type_detect)
    print("✓ Type detection updated")
else:
    print("! Type detect block not found — may need manual check")

# ── 6. Fix addStream to also mirror to responses panel ───────────────────────
old_mirror = """// Patch addStream to mirror Nex's own output to the responses panel
const _origAddStream = addStream;
window.addStream = function(t, type, text) {
  _origAddStream(t, type, text);
  addResponse(t, type, text);"""

new_mirror = """// Patch addStream to mirror to responses panel (all non-INFO types)
const _origAddStream = addStream;
window.addStream = function(t, type, text) {
  _origAddStream(t, type, text);
  if (type !== 'INFO' && RESPONSE_TYPES.has(type)) {
    addResponse(t, type, text);
  }"""

if old_mirror in src:
    src = src.replace(old_mirror, new_mirror)
    print("✓ Stream mirror fixed")
else:
    print("! Mirror patch not found")

with open(path, "w") as f:
    f.write(src)
print("✓ nex_hud.html fully patched")
