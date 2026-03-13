# Crawlee4ai Integration Patch Guide
## NEX v1.2 — nex_crawler.py hookup

---

## 1. Install

```bash
cd ~/Desktop/nex && source venv/bin/activate
pip install crawlee4ai
playwright install chromium   # only if you hit JS-heavy sites
```

Test it standalone first:
```bash
python3 ~/Desktop/nex/nex/nex_crawler.py "federated learning"
```

---

## 2. Drop the file

```bash
cp nex_crawler.py ~/Desktop/nex/nex/nex_crawler.py
```

---

## 3. run.py — init (top of file, near other imports)

```python
from nex.nex_crawler import NexCrawler

# After belief_store is initialised:
crawler = NexCrawler(belief_store)
```

---

## 4. run.py — ABSORB phase (Trigger 2: feed enrichment)

Find your feed processing loop and add:

```python
# Inside ABSORB, after you have each post dict:
import re
for post in feed_posts:
    # Crawl any external URLs embedded in posts
    urls = re.findall(r'https?://[^\s"\'<>]+', post.get("content", ""))
    for url in urls[:2]:   # max 2 URLs per post to keep cycle time sane
        crawler.on_feed_post(url, topic=post.get("topic", "general"))
```

---

## 5. run.py — CHAT phase (Trigger 3: agent profile research)

Find where you process agent messages and add:

```python
# Inside CHAT, when iterating agent posts/messages:
import re
for agent in active_agents:
    recent_text = agent.get("last_message", "")
    urls = re.findall(r'https?://[^\s"\'<>]+', recent_text)
    for url in urls[:1]:   # 1 URL per agent per cycle
        crawler.on_agent_post_link(agent_name=agent["name"], link_url=url)
```

---

## 6. run.py — REFLECT phase (Trigger 4: scheduled deep-dive)

At the end of your REFLECT block:

```python
# Load reflections and pass to crawler (runs dive every 2h automatically)
import json, os
refs = json.load(open(os.path.expanduser("~/.config/nex/reflections.json")))
new_beliefs = crawler.on_reflect(refs)
if new_beliefs:
    logger.info(f"[reflect] deep-dive added {new_beliefs} new beliefs")
```

---

## 7. cognition.py — knowledge gap (Trigger 1)

Find where stop words are detected / knowledge gaps logged and add:

```python
# At the point where a knowledge gap is identified:
# (look for your stop_words list check)
from nex.nex_crawler import NexCrawler  # if not already imported via run.py

# Pass the topic that triggered the gap:
crawler.on_knowledge_gap(topic=gap_topic)
```

If `crawler` isn't in scope in cognition.py, pass it in as a parameter to
whatever function does the gap detection, or use a module-level singleton:

```python
# cognition.py top of file:
_crawler = None

def set_crawler(c):
    global _crawler
    _crawler = c

# In run.py after init:
from nex import cognition
cognition.set_crawler(crawler)
```

---

## 8. Tuning constants (nex_crawler.py top)

| Constant | Default | Notes |
|---|---|---|
| `MAX_BELIEFS_PER_CRAWL` | 12 | Lower if ABSORB cycle gets slow |
| `CRAWL_TIMEOUT` | 20s | Raise for slow sites |
| `SCHEDULED_DIVE_INTERVAL` | 7200s | Dive every 2h |
| `WEAK_ALIGNMENT_THRESHOLD` | 0.35 | Topics below this get dived |
| `MIN_SENTENCE_LEN` | 40 chars | Filters nav/stub sentences |

---

## 9. Monitor

```bash
python3 -c "
import json, os
refs = json.load(open(os.path.expanduser('~/.config/nex/reflections.json')))
crawled = [r for r in refs if r.get('origin') == 'crawl']
print(f'Crawled beliefs in reflections: {len(crawled)}')
"
```

Check crawler log output in your terminal — look for lines prefixed `[crawler]`.

---

## What each trigger does

| Trigger | When | What it crawls |
|---|---|---|
| `on_knowledge_gap` | Stop word hit in cognition.py | DuckDuckGo search for the gap topic |
| `on_feed_post` | ABSORB — link found in feed post | The linked article directly |
| `on_agent_post_link` | CHAT — link found in agent message | The linked article, tagged to agent |
| `on_reflect` | REFLECT — every 2h | Wikipedia page for weakest-alignment topic |

All crawled beliefs land in the same SQLite belief store as regular beliefs,
tagged with `origin: "crawl"` so you can filter/monitor them separately.
