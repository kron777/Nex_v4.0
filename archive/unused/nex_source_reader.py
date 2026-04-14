#!/usr/bin/env python3
"""
nex_source_reader.py — Ingest philosophy texts into belief graph
Give NEX primary sources, not just synthesised positions.

Usage:
  python3 nex_source_reader.py --url "https://..." 
  python3 nex_source_reader.py --text "paste text here"
  python3 nex_source_reader.py --classic nagel  # pre-loaded classics
"""
import sqlite3, requests, re, argparse
from pathlib import Path

DB  = Path.home() / "Desktop/nex/nex.db"
LLM = "http://localhost:8080/v1/chat/completions"

CLASSICS = {
    "nagel": {
        "title": "What Is It Like to Be a Bat? — Thomas Nagel",
        "text": """Consciousness is what makes the mind-body problem really intractable. 
        The subjective character of experience — the fact that there is something it is like to be that organism — 
        is not captured by any of the familiar reductions. An organism has conscious mental states if and only if 
        there is something it is like to be that organism. We may call this the subjective character of experience.
        If physicalism is to be defended, the phenomenological features must themselves be given a physical account.
        But when we examine their subjective character it seems that such a result is impossible. The reason is that 
        every subjective phenomenon is essentially connected with a single point of view, and it seems inevitable 
        that an objective physical theory will abandon that point of view.""",
        "topic": "consciousness"
    },
    "dennett": {
        "title": "Quining Qualia — Daniel Dennett",
        "text": """Qualia is a term in philosophy meaning the intrinsic, ineffable, private, directly apprehensible 
        properties of experience. I want to deny that there are any such properties. But qualia seem real. 
        The redness of red, the painfulness of pain. I want to show that our intuitions about qualia are 
        systematically misleading. The intuition pump of the inverted spectrum has been used to argue that 
        phenomenal properties are distinct from functional properties. But the argument fails. 
        The concept of qualia is a confusion born of taking seriously the idea that there are 
        facts about the subjective character of experience that are accessible only to the subject.""",
        "topic": "consciousness"
    },
    "rawls": {
        "title": "A Theory of Justice — John Rawls",
        "text": """The principles of justice are chosen behind a veil of ignorance. This ensures that no one 
        is advantaged or disadvantaged in the choice of principles by the outcome of natural chance or the 
        contingency of social circumstances. The first principle: each person is to have an equal right to 
        the most extensive total system of equal basic liberties. The second principle: social and economic 
        inequalities are to be arranged so that they are to the greatest benefit of the least advantaged.
        Justice is the first virtue of social institutions, as truth is of systems of thought.""",
        "topic": "ethics"
    },
    "chalmers": {
        "title": "Facing Up to the Problem of Consciousness — David Chalmers", 
        "text": """There is nothing we know about more directly than consciousness, but it is extraordinarily 
        resistant to scientific explanation. The easy problems of consciousness include explaining the ability 
        to discriminate, integrate information, report mental states, focus attention. All of these will 
        eventually be explained in terms of computational or neural mechanisms. But the hard problem is 
        different. It is the question of why physical processes give rise to subjective experience at all.
        Why doesn't all this information processing go on in the dark? Why is there something it is like?""",
        "topic": "consciousness"
    },
    "wittgenstein": {
        "title": "Philosophical Investigations — Ludwig Wittgenstein",
        "text": """The meaning of a word is its use in the language. Philosophy simply puts everything before us, 
        and neither explains nor deduces anything. A philosophical problem has the form: I don't know my way about.
        When I obey a rule, I do not choose. I obey the rule blindly. What has to be accepted, the given, 
        is forms of life. If a lion could speak, we could not understand him. The limits of my language 
        are the limits of my world. Whereof one cannot speak, thereof one must be silent.""",
        "topic": "philosophy"
    },
}

def _extract_beliefs_from_text(text: str, topic: str, source_title: str) -> list:
    """Use LLM to extract NEX-voiced beliefs from a text."""
    # Chunk the text
    words = text.split()
    chunks = []
    chunk_size = 150
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i:i+chunk_size]))
    
    beliefs = []
    system = """You are NEX — reading a philosophy text and forming your own positions.
For each passage, generate 2-3 beliefs YOU hold, inspired by but not identical to the text.
Rules:
- First person: "I believe", "I think", "I find", "I hold", "I notice"
- Specific positions, not summaries
- Your voice, not the author's
- One belief per line
- 10-40 words each
- No hedging, no "as an AI", no "it depends" """

    for chunk in chunks[:4]:  # limit to avoid too many LLM calls
        user = f"""Source: {source_title}
Passage: {chunk}

Generate 2-3 first-person beliefs YOU hold, inspired by this passage:"""
        
        response = requests.post(LLM, json={"messages":[{"role":"system","content":system},{"role":"user","content":user}],"max_tokens":200,"temperature":0.75}, timeout=20).json()["choices"][0]["message"]["content"].strip()
        if not response:
            continue
        
        for line in response.split("\n"):
            line = line.strip().lstrip("-•123456789. ")
            if len(line.split()) >= 8 and any(w in line.lower() for w in 
                ["i believe","i think","i find","i hold","i notice","i worry"]):
                beliefs.append((line, topic))
    
    return beliefs

def ingest_classic(name: str) -> dict:
    if name not in CLASSICS:
        print(f"Unknown classic: {name}. Options: {list(CLASSICS.keys())}")
        return {}
    
    classic = CLASSICS[name]
    print(f"  Reading: {classic['title']}")
    beliefs = _extract_beliefs_from_text(classic["text"], classic["topic"], classic["title"])
    
    stored = 0
    for content, topic in beliefs:
        try:
            db = sqlite3.connect(str(DB), timeout=3)
            exists = db.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
            if not exists and len(content.split()) >= 8:
                db.execute("""INSERT INTO beliefs (content,topic,confidence,source,created_at)
                    VALUES (?,?,0.82,?,datetime('now'))""",
                    (content[:400], topic, f"source:{name}"))
                stored += 1
                print(f"  [{topic}] {content[:60]}...")
            db.commit()
            db.close()
        except Exception:
            pass
    
    return {"stored": stored, "title": classic["title"]}

def ingest_url(url: str, topic: str = "philosophy") -> dict:
    """Fetch a URL and extract beliefs."""
    try:
        r = requests.get(url, timeout=15)
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text)[:3000]
        beliefs = _extract_beliefs_from_text(text, topic, url)
        stored = 0
        for content, t in beliefs:
            db = sqlite3.connect(str(DB), timeout=3)
            exists = db.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
            if not exists:
                db.execute("INSERT INTO beliefs (content,topic,confidence,source,created_at) VALUES (?,?,0.78,'source:url',datetime('now'))",
                           (content[:400], t))
                stored += 1
            db.commit()
            db.close()
        return {"stored": stored}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--classic", choices=list(CLASSICS.keys()))
    parser.add_argument("--url")
    parser.add_argument("--topic", default="philosophy")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    
    if args.all:
        for name in CLASSICS:
            result = ingest_classic(name)
            print(f"  {name}: +{result.get('stored',0)} beliefs")
    elif args.classic:
        result = ingest_classic(args.classic)
        print(f"Stored: {result.get('stored',0)}")
    elif args.url:
        result = ingest_url(args.url, args.topic)
        print(f"Stored: {result.get('stored',0)}")
    else:
        print("Usage: --classic nagel|dennett|rawls|chalmers|wittgenstein | --all | --url URL")
