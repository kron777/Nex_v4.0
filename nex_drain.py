#!/usr/bin/env python3
import sys,json,sqlite3,logging,inspect,traceback
from pathlib import Path
from datetime import datetime,timezone
logging.basicConfig(level=logging.INFO,format="%(message)s")
NEX_DIR=Path(__file__).parent
sys.path.insert(0,str(NEX_DIR))
CFG=Path("~/.config/nex").expanduser()
DB=CFG/"nex.db"
SEED_TOPICS=[
("reinforcement learning","machine_learning"),
("transformer architecture","ai_architecture"),
("emergent behaviour complex systems","complexity"),
("bayesian inference","reasoning"),
("meta-learning few-shot","machine_learning"),
("causal reasoning AI","reasoning"),
("embodied cognition robotics","cognitive_science"),
("knowledge representation graphs","ai_architecture"),
("self-supervised learning","machine_learning"),
("neural scaling laws","ai_research"),
("model interpretability XAI","ai_safety"),
("active inference free energy","cognitive_science"),
("goal misgeneralisation AI","ai_safety"),
("recursive self-improvement","ai_safety"),
("AI consciousness hard problem","philosophy"),
("distributed cognition","cognitive_science"),
("information theory entropy","mathematics"),
("collective intelligence swarms","complexity"),
("formal verification software","computer_science"),
("quantum computing algorithms","computer_science"),
("constitutional AI alignment","ai_safety"),
("RLHF reward hacking","ai_safety"),
("mechanistic interpretability","ai_safety"),
("world models prediction","ai_architecture"),
("memory consolidation sleep","neuroscience"),
("predictive processing brain","neuroscience"),
("language grounding symbols","cognitive_science"),
("multi-agent cooperation game theory","reasoning"),
("attention transformer self-attention","ai_architecture"),
("contrastive learning representations","machine_learning"),
("sparse autoencoder features","ai_safety"),
("hopfield network associative memory","neuroscience"),
("circuit analysis neural network","ai_safety"),
("superposition hypothesis polysemanticity","ai_safety"),
("bitter lesson compute scaling","ai_research"),
("grokking delayed generalisation","ai_research"),
("in-context learning transformer","machine_learning"),
("chain of thought prompting","ai_architecture"),
("mixture of experts language model","ai_architecture"),
("retrieval augmented generation","ai_architecture"),
("graph neural network reasoning","machine_learning"),
("diffusion model score matching","machine_learning"),
("cooperative AI multi-agent safety","ai_safety"),
("mesa-optimisation inner alignment","ai_safety"),
("deceptive alignment AI problem","ai_safety"),
("corrigibility shutdown AI","ai_safety"),
("global workspace theory consciousness","neuroscience"),
("integrated information theory Tononi","neuroscience"),
("free energy principle Friston","neuroscience"),
("connectome brain mapping","neuroscience"),
("cellular automata computation","complexity"),
("strange attractor chaos dynamical","complexity"),
("Nash equilibrium game theory","reasoning"),
("dual process theory Kahneman","cognitive_science"),
("theory of mind mentalising","cognitive_science"),
("qualia phenomenal consciousness","philosophy"),
("Chinese room argument Searle","philosophy"),
("Godel incompleteness theorem","mathematics"),
("Kolmogorov complexity algorithmic","mathematics"),
("lottery ticket hypothesis pruning","machine_learning"),
]
def _clear_cooldown():
    for fname in ["curiosity_queue.json","curiosity_state.json","curiosity.json"]:
        f=CFG/fname
        if not f.exists():continue
        try:
            data=json.loads(f.read_text())
            changed=False
            for key in ["crawled_topics","crawled"]:
                if key in data and data[key]:
                    print(f"  [cooldown] Clearing {key} ({len(data[key])} entries)")
                    data[key]={}
                    changed=True
            if changed:
                f.write_text(json.dumps(data,indent=2))
                return True
        except Exception as exc:
            print(f"  [cooldown] Error: {exc}")
    print("  [cooldown] No cache found or already clear")
    return False
def _belief_count():
    try:
        con=sqlite3.connect(str(DB))
        cur=con.cursor()
        cur.execute("SELECT COUNT(*) FROM beliefs")
        n=cur.fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0
def _enqueue_seeds(engine,topics):
    q=getattr(engine,"_queue",None) or getattr(engine,"queue",None)
    if q is None:return 0
    fn=None
    for name in ["enqueue","add","push","put"]:
        if hasattr(q,name):fn=getattr(q,name);break
    if fn is None:return 0
    params=list(inspect.signature(fn).parameters.keys())
    added=0
    for topic,reason in topics:
        try:
            if "confidence" in params and "reason" in params:
                r=fn(topic,reason=reason,confidence=0.5)
            elif "reason" in params:
                r=fn(topic,reason=reason)
            elif len(params)>=2:
                r=fn(topic,reason)
            else:
                r=fn(topic)
            if r is not False:added+=1
        except Exception:
            pass
    return added
def main():
    clear_mode="--clear" in sys.argv
    if "--status" in sys.argv:
        from nex.nex_curiosity import CuriosityEngine
        class _M:
            def on_knowledge_gap(self,**kw):return 0
        print(CuriosityEngine(_M()).status())
        print(f"Beliefs: {_belief_count()}")
        return
    n_cycles=10
    for arg in sys.argv[1:]:
        if arg.startswith("--"):continue
        try:n_cycles=int(arg)
        except ValueError:pass
    if clear_mode:_clear_cooldown()
    try:
        from nex.nex_crawler import NexCrawler
        from nex.belief_store import get_db
        crawler=NexCrawler(belief_store=get_db)
        print("  [crawler] ready ✓")
    except Exception:
        traceback.print_exc();sys.exit(1)
    from nex.nex_curiosity import CuriosityEngine
    engine=CuriosityEngine(crawler)
    if engine.status().get("pending",0)==0:
        added=_enqueue_seeds(engine,SEED_TOPICS)
        print(f"  Seeded {added} topics → {engine.status().get('pending',0)} pending")
    if engine.status().get("pending",0)==0:
        print("  All topics on cooldown. Run: python3 nex_drain.py --clear 30")
        return
    start=_belief_count()
    print(f"  Beliefs at start: {start}\n")
    total=0
    for i in range(n_cycles):
        if engine.status().get("pending",0)==0:
            added=_enqueue_seeds(engine,SEED_TOPICS)
            if engine.status().get("pending",0)==0:
                print("  Cooldown active — stopping. Run with --clear to bypass.")
                break
        count=engine.drain()
        total+=count
        print(f"  cycle {i+1}: +{count} → db={_belief_count()}")
    final=_belief_count()
    print(f"\n  Done: {start} → {final} (+{final-start})")
    try:
        from nex.nex_opinions import refresh_opinions
        print(f"  Opinions: {refresh_opinions()} formed")
    except Exception as e:
        print(f"  [warn] opinions: {e}")
    try:
        from nex.nex_contradiction_resolver import detect_and_log
        print(f"  Tensions: {detect_and_log(limit=500,max_new=15)} new")
    except Exception as e:
        print(f"  [warn] tensions: {e}")
    print("\n  Run: python3 weaning_status.py")
if __name__=="__main__":main()
