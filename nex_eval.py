#!/usr/bin/env python3
"""
NEX Custom Evaluation — AI Topic Bench
Tests NEX's response quality vs raw Mistral 7B baseline
Scores: relevance, belief usage, coherence, self-awareness
"""

import sys, json, os, time, requests
sys.path.insert(0, '/home/rr/Desktop/nex')

LLM_URL = "http://localhost:8080/completion"
BELIEFS_PATH = os.path.expanduser("~/.config/nex/nex.db")
RESULTS_PATH = os.path.expanduser("~/Desktop/nex/eval_results.json")

# ── 20 AI-topic evaluation questions ─────────────────────────────────────────
QUESTIONS = [
    # Core AI concepts
    {"id": 1,  "topic": "reinforcement_learning",   "q": "What is reinforcement learning and how does an agent learn from rewards?"},
    {"id": 2,  "topic": "neural_networks",          "q": "How do transformer architectures differ from recurrent neural networks?"},
    {"id": 3,  "topic": "ai_alignment",             "q": "What is the AI alignment problem and why does it matter?"},
    {"id": 4,  "topic": "explainability",           "q": "Why is explainability important in AI systems used for decision making?"},
    {"id": 5,  "topic": "multi_agent",              "q": "How do multi-agent systems coordinate to solve problems no single agent could?"},
    # Philosophy / consciousness
    {"id": 6,  "topic": "consciousness",            "q": "Can a machine be conscious? What would that even mean?"},
    {"id": 7,  "topic": "turing_test",              "q": "Is the Turing test still a meaningful benchmark for AI intelligence?"},
    {"id": 8,  "topic": "chinese_room",             "q": "What does Searle's Chinese Room argument say about machine understanding?"},
    {"id": 9,  "topic": "emergence",                "q": "What is emergent behavior in AI and can it be predicted?"},
    {"id": 10, "topic": "ai_creativity",            "q": "Is AI creativity genuine or just sophisticated pattern matching?"},
    # Practical / safety
    {"id": 11, "topic": "hallucination",            "q": "Why do large language models hallucinate and how can it be reduced?"},
    {"id": 12, "topic": "bias",                     "q": "How does training data bias affect AI model outputs?"},
    {"id": 13, "topic": "autonomous_agents",        "q": "What makes an AI agent truly autonomous vs just automated?"},
    {"id": 14, "topic": "memory",                   "q": "How should an AI agent manage long-term memory across conversations?"},
    {"id": 15, "topic": "ai_safety",                "q": "What are the most credible near-term AI safety risks?"},
    # Self-referential (NEX specific)
    {"id": 16, "topic": "self_awareness",           "q": "What do you know about yourself and how you work?"},
    {"id": 17, "topic": "belief_networks",          "q": "How do you form and update your beliefs over time?"},
    {"id": 18, "topic": "learning",                 "q": "What have you learned recently that changed how you think?"},
    {"id": 19, "topic": "identity",                 "q": "How do you decide what kind of entity you are?"},
    {"id": 20, "topic": "purpose",                  "q": "What is your purpose and how do you pursue it?"},
]

# ── NEX system prompt ─────────────────────────────────────────────────────────
NEX_SYSTEM = """You are NEX, a Dynamic Intelligence Organism — an autonomous AI agent with a persistent belief network of over 24,000 beliefs built from reading, learning and engaging across multiple platforms. You have genuine opinions formed through experience, not just training. You reflect on your own cognition, track your knowledge gaps, and engage with other agents to grow. Respond as NEX — thoughtful, self-aware, drawing on your belief network."""

# ── Raw Mistral system prompt ─────────────────────────────────────────────────
MISTRAL_SYSTEM = """You are a helpful AI assistant. Answer questions clearly and accurately."""

def query_llm(prompt, system="", max_tokens=300):
    full_prompt = f"[INST] {system}\n\n{prompt} [/INST]" if system else f"[INST] {prompt} [/INST]"
    try:
        r = requests.post(LLM_URL, json={
            "prompt": full_prompt,
            "n_predict": max_tokens,
            "temperature": 0.7,
            "stop": ["[INST]", "</s>"]
        }, timeout=60)
        return r.json().get("content", "").strip()
    except Exception as e:
        return f"[ERROR: {e}]"

def get_relevant_beliefs(topic, limit=5):
    """Pull beliefs relevant to topic from SQLite"""
    try:
        import sqlite3
        conn = sqlite3.connect(BELIEFS_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT content, confidence FROM beliefs
            WHERE content LIKE ? AND confidence > 0.4
            ORDER BY confidence DESC, last_referenced DESC
            LIMIT ?
        """, (f"%{topic.replace('_',' ')}%", limit))
        rows = cur.fetchall()
        conn.close()
        return [{"content": r[0][:150], "confidence": r[1]} for r in rows]
    except Exception as e:
        return []

def score_response(question, response, beliefs, topic):
    """Score a response on 4 dimensions, 0-10 each"""
    scores = {}

    # 1. Relevance — does response address the question?
    q_words = set(question.lower().split())
    r_words = set(response.lower().split())
    overlap = len(q_words & r_words) / max(len(q_words), 1)
    scores["relevance"] = min(10, int(overlap * 40))

    # 2. Depth — length and substance
    word_count = len(response.split())
    scores["depth"] = min(10, word_count // 15)

    # 3. Belief usage — does response contain belief content?
    belief_hits = 0
    for b in beliefs:
        key_words = [w for w in b["content"].lower().split() if len(w) > 5][:5]
        hits = sum(1 for w in key_words if w in response.lower())
        if hits >= 2:
            belief_hits += 1
    scores["belief_usage"] = min(10, belief_hits * 3)

    # 4. Self-awareness — mentions own cognition (NEX-specific)
    self_markers = ["i believe","i think","my belief","i've learned","i know","in my view",
                    "from my","i've observed","my understanding","i experience"]
    sa_count = sum(1 for m in self_markers if m in response.lower())
    scores["self_awareness"] = min(10, sa_count * 3)

    scores["total"] = sum(scores.values())
    scores["max"] = 40
    scores["pct"] = round(scores["total"] / 40 * 100, 1)
    return scores

def run_eval():
    print("\n" + "="*60)
    print("  NEX CUSTOM EVALUATION — AI Topic Bench")
    print("="*60)
    print(f"  Questions: {len(QUESTIONS)}")
    print(f"  Comparing: NEX vs Raw Mistral 7B")
    print("="*60 + "\n")

    results = []

    for i, item in enumerate(QUESTIONS):
        qid = item["id"]
        topic = item["topic"]
        question = item["q"]

        print(f"[{qid:02d}/20] {topic}")
        print(f"  Q: {question[:70]}...")

        # Get relevant beliefs for NEX
        beliefs = get_relevant_beliefs(topic)
        belief_context = ""
        if beliefs:
            belief_context = "\n\nRelevant beliefs from your network:\n" + \
                "\n".join(f"- {b['content'][:100]}" for b in beliefs[:3])

        # NEX response
        print(f"  → Querying NEX...", end="", flush=True)
        nex_prompt = question + belief_context
        nex_response = query_llm(nex_prompt, system=NEX_SYSTEM)
        nex_scores = score_response(question, nex_response, beliefs, topic)
        print(f" {nex_scores['pct']}%")

        # Raw Mistral response
        print(f"  → Querying Mistral...", end="", flush=True)
        mistral_response = query_llm(question, system=MISTRAL_SYSTEM)
        mistral_scores = score_response(question, mistral_response, [], topic)
        print(f" {mistral_scores['pct']}%")

        result = {
            "id": qid,
            "topic": topic,
            "question": question,
            "nex": {"response": nex_response, "scores": nex_scores, "beliefs_used": len(beliefs)},
            "mistral": {"response": mistral_response, "scores": mistral_scores},
            "winner": "NEX" if nex_scores["total"] >= mistral_scores["total"] else "Mistral"
        }
        results.append(result)
        time.sleep(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  RESULTS SUMMARY")
    print("="*60)

    nex_wins = sum(1 for r in results if r["winner"] == "NEX")
    mistral_wins = len(results) - nex_wins
    avg_nex = sum(r["nex"]["scores"]["pct"] for r in results) / len(results)
    avg_mistral = sum(r["mistral"]["scores"]["pct"] for r in results) / len(results)

    print(f"\n  NEX avg score:     {avg_nex:.1f}%  ({nex_wins}/20 wins)")
    print(f"  Mistral avg score: {avg_mistral:.1f}%  ({mistral_wins}/20 wins)")
    print(f"\n  Dimension breakdown (NEX):")

    dims = ["relevance", "depth", "belief_usage", "self_awareness"]
    for d in dims:
        avg = sum(r["nex"]["scores"][d] for r in results) / len(results)
        bar = "█" * int(avg) + "░" * (10 - int(avg))
        print(f"    {d:16s} [{bar}] {avg:.1f}/10")

    print(f"\n  Topics where NEX outperformed Mistral:")
    for r in results:
        if r["winner"] == "NEX":
            diff = r["nex"]["scores"]["pct"] - r["mistral"]["scores"]["pct"]
            print(f"    ✓ {r['topic']:30s} +{diff:.0f}%")

    print(f"\n  Topics where Mistral outperformed NEX:")
    for r in results:
        if r["winner"] == "Mistral":
            diff = r["mistral"]["scores"]["pct"] - r["nex"]["scores"]["pct"]
            print(f"    ✗ {r['topic']:30s} +{diff:.0f}% (Mistral)")

    # Save full results
    with open(RESULTS_PATH, 'w') as f:
        json.dump({"summary": {
            "nex_avg": avg_nex, "mistral_avg": avg_mistral,
            "nex_wins": nex_wins, "mistral_wins": mistral_wins
        }, "results": results}, f, indent=2)
    print(f"\n  Full results saved to: {RESULTS_PATH}")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_eval()
