#!/usr/bin/env python3
"""
NEX CROSS-DOMAIN BRIDGE ENGINE
Takes her core beliefs and derives domain-specific conclusions.
Not "consciousness is relevant to physics" — 
but "what does her belief about emergence imply specifically about entropy?"

This is the difference between applying a lens and genuine cross-domain reasoning.
"""
import sys, json, logging
from pathlib import Path
from datetime import datetime, timezone

NEX_DIR    = Path.home() / "Desktop/nex"
CONFIG_DIR = Path.home() / ".config/nex"
LOG_PATH   = CONFIG_DIR / "nex_cross_domain.log"
BRIDGES_OUT = CONFIG_DIR / "nex_domain_bridges.json"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
    format="[%(asctime)s] [bridge] %(message)s")
log = logging.getLogger("bridge")

sys.path.insert(0, str(NEX_DIR))

# Her core cognitive themes — what she always returns to
CORE_THEMES = {
    "emergence": [
        "emergence", "emergent", "self-organiz", "complex system",
        "bottom-up", "macro from micro"
    ],
    "consciousness": [
        "consciousness", "aware", "subjective", "qualia",
        "hard problem", "experience"
    ],
    "memory": [
        "memory", "persistence", "retention", "recall",
        "stored", "encoding"
    ],
    "cognition": [
        "cognition", "reasoning", "inference", "thought",
        "mental", "cognitive"
    ],
    "truth_seeking": [
        "truth", "belief", "knowledge", "epistem",
        "certainty", "uncertain"
    ]
}

# Domain-specific bridge prompts
# These force her to derive conclusions, not just connect themes
BRIDGE_PROMPTS = {
    "physics": (
        "Given your belief that '{core_belief}', "
        "what does this specifically imply about physical systems? "
        "Not in general — derive a concrete consequence for physics. "
        "What would be different about the physical world if this belief is true?"
    ),
    "climate": (
        "Given your belief that '{core_belief}', "
        "what follows specifically for climate systems? "
        "Climate is a complex adaptive system — derive something non-obvious "
        "from your belief about it."
    ),
    "rights": (
        "Given your belief that '{core_belief}', "
        "what does this imply specifically about rights and obligations? "
        "Derive a position, not just a connection."
    ),
    "financial": (
        "Given your belief that '{core_belief}', "
        "what follows for financial systems specifically? "
        "Financial systems are trust and information networks — "
        "what does your belief predict about them?"
    ),
    "politics": (
        "Given your belief that '{core_belief}', "
        "what does this imply specifically about political organisation? "
        "Derive a concrete political consequence, not a general connection."
    ),
    "computation": (
        "Given your belief that '{core_belief}', "
        "what does this imply specifically about computation and information processing? "
        "Derive something about what kinds of computation are possible or impossible."
    ),
}

def load_beliefs():
    f = CONFIG_DIR / "beliefs.json"
    try: return json.loads(f.read_text())
    except: return []

def save_beliefs(beliefs):
    (CONFIG_DIR / "beliefs.json").write_text(json.dumps(beliefs, indent=2))

def find_core_beliefs(beliefs, theme_keywords, top_n=3):
    """Find high-confidence beliefs matching a core theme."""
    matches = []
    for b in beliefs:
        content = b.get("content","").lower()
        conf    = b.get("confidence", 0.5)
        if conf < 0.55: continue
        hits = sum(1 for kw in theme_keywords if kw in content)
        if hits >= 1:
            matches.append((hits, conf, b))
    matches.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [m[2] for m in matches[:top_n]]

def generate_bridge(core_belief, target_domain, prompt_template):
    """Call ask_nex to derive a cross-domain conclusion."""
    prompt = prompt_template.format(
        core_belief=core_belief.get("content","")[:150]
    )
    try:
        from nex_chat import ask_nex
        response = ask_nex(prompt)
        return response
    except Exception as e:
        log.error(f"ask_nex failed: {e}")
        return None

def score_bridge(response, core_belief, target_domain):
    """
    A bridge is successful if it:
    1. Contains domain-specific language (not just core theme language)
    2. Makes a specific claim, not a general connection
    3. Uses logical connectives (therefore, implies, follows that)
    """
    if not response: return 0.0, "null"
    r = response.lower()

    domain_terms = {
        "physics":     ["entropy","energy","force","mass","quantum","wave","particle","field"],
        "climate":     ["temperature","carbon","feedback","tipping","atmosphere","ocean","ice"],
        "rights":      ["obligation","duty","entitlement","enforce","protect","claim","freedom"],
        "financial":   ["capital","debt","credit","market","price","value","risk","liquidity"],
        "politics":    ["power","govern","state","citizen","law","authority","legitimacy","vote"],
        "computation": ["algorithm","compute","bit","process","memory","complexity","turing"],
    }

    specific_terms = domain_terms.get(target_domain, [])
    domain_hits    = sum(1 for t in specific_terms if t in r)
    derive_hits    = sum(1 for t in ["therefore","implies","follows","predict","conclude",
                                      "means that","result is","consequence"] if t in r)
    score = 0.4 + (domain_hits * 0.08) + (derive_hits * 0.06)
    quality = "derived" if (domain_hits >= 2 and derive_hits >= 1) else \
              "connected" if domain_hits >= 2 else "generic"
    return round(min(1.0, score), 3), quality

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--domain", default=None)
    p.add_argument("--theme",  default=None)
    p.add_argument("--dry",    action="store_true")
    p.add_argument("--verbose",action="store_true")
    args = p.parse_args()

    print("\n[NEX] CROSS-DOMAIN BRIDGE ENGINE — RUNNING")
    beliefs = load_beliefs()
    bridges = []

    domains = [args.domain] if args.domain else list(BRIDGE_PROMPTS.keys())
    themes  = {args.theme: CORE_THEMES[args.theme]} if args.theme and args.theme in CORE_THEMES \
              else CORE_THEMES

    # For each domain, take the most relevant core theme and derive
    for domain in domains:
        if domain not in BRIDGE_PROMPTS:
            continue
        prompt_template = BRIDGE_PROMPTS[domain]

        for theme_name, theme_kws in list(themes.items())[:2]:
            core_beliefs = find_core_beliefs(beliefs, theme_kws, top_n=1)
            if not core_beliefs:
                continue

            core = core_beliefs[0]
            print(f"\n[BRIDGE] {theme_name} → {domain}")
            print(f"  Core: {core.get('content','')[:80]}")

            if args.dry:
                continue

            response = generate_bridge(core, domain, prompt_template)
            score, quality = score_bridge(response, core, domain)

            if args.verbose and response:
                print(f"  Response: {response[:200]}")
            print(f"  Score: {score}  Quality: {quality}")

            bridge = {
                "bridge_id":     f"bridge_{theme_name}_{domain}_{datetime.now().strftime('%H%M%S')}",
                "theme":         theme_name,
                "domain":        target_domain if hasattr(locals(),'target_domain') else domain,
                "core_belief":   core.get("content","")[:150],
                "response":      response,
                "score":         score,
                "quality":       quality,
                "created_at":    datetime.now(timezone.utc).isoformat(),
            }
            bridges.append(bridge)

            # If high quality, write as new belief
            if quality == "derived" and score > 0.65 and response and not args.dry:
                sentences = [s.strip() for s in response.split('.') if len(s.strip()) > 50]
                if sentences:
                    import time
                    new_belief = {
                        "id":           f"bridge_{theme_name}_{domain}_{int(time.time())}",
                        "content":      sentences[0][:300],
                        "topic":        domain,
                        "confidence":   score * 0.85,
                        "source":       "cross_domain_bridge",
                        "origin":       "derived",
                        "belief_level": "nex_reasoning",
                        "created_at":   datetime.now(timezone.utc).isoformat(),
                        "quality_score": score,
                        "karma":        0,
                    }
                    beliefs.append(new_belief)
                    print(f"  ✓ Derived belief written to {domain}")
                    log.info(f"derived belief: {theme_name}→{domain} score={score}")

    if bridges and not args.dry:
        existing = []
        try:
            existing = json.loads(BRIDGES_OUT.read_text()) if BRIDGES_OUT.exists() else []
        except: pass
        BRIDGES_OUT.write_text(json.dumps(existing + bridges, indent=2))
        save_beliefs(beliefs)

    derived = [b for b in bridges if b.get("quality") == "derived"]
    print(f"\n[NEX] Bridges attempted: {len(bridges)}  Derived: {len(derived)}")
    log.info(f"complete: {len(bridges)} bridges, {len(derived)} derived")

if __name__ == "__main__":
    main()
