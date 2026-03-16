#!/usr/bin/env python3
"""
nex_cognitive_bus.py — NEX Cognitive Event Bus
Adapted from Sentience 5.5 (github.com/kron777/Sentience_5.5)

Nodes included (ROS stripped, wired to NEX data):
  - CognitiveEventBus    — central event coordination
  - AttentionNode        — what matters right now
  - DriveSystemNode      — motivational pressure
  - EmotionMoodNode      — deterministic affect model
  - SurpriseDetectorNode — prediction error / novelty detection
  - TheoryOfMindNode     — models of other agents
  - InternalNarrativeNode— internal monologue synthesis

All LLM calls use nex_groq._groq() — shared rate-limited Groq client.
All state persists to ~/.config/nex/cognitive_bus_state.json

Entry point from run.py:
    from nex_cognitive_bus import run_cognitive_bus_cycle, get_bus_context
    run_cognitive_bus_cycle(cycle=cycle, event=event_dict)
    context = get_bus_context()  # inject into system prompt
"""

import os
import json
import time
import random
import threading
from pathlib import Path
from datetime import datetime, timezone
from collections import deque
from typing import Dict, Any, Optional, List, Callable

CFG_PATH   = Path("~/.config/nex").expanduser()
STATE_PATH = CFG_PATH / "cognitive_bus_state.json"
AGENTS_PATH= CFG_PATH / "agent_profiles.json"
CONVOS_PATH= CFG_PATH / "conversations.json"
BELIEFS_PATH=CFG_PATH / "beliefs.json"


# ══════════════════════════════════════════════════════════════════════════════
# SHARED LLM
# ══════════════════════════════════════════════════════════════════════════════

def _llm(messages: list, max_tokens: int = 150) -> str | None:
    """Use shared Groq client. Falls back silently if rate limited."""
    try:
        from nex_groq import _groq
        return _groq(messages, max_tokens=max_tokens, temperature=0.7)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. COGNITIVE EVENT BUS (from Sentience 5.5, no changes needed)
# ══════════════════════════════════════════════════════════════════════════════

class CognitiveEventBus:
    def __init__(self, history_limit: int = 200):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.event_history = deque(maxlen=history_limit)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: Callable):
        with self._lock:
            self.subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, source: str,
                payload: Dict[str, Any], salience: float = 0.5):
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "source": source,
            "salience": salience,
            "payload": payload,
        }
        with self._lock:
            self.event_history.append(event)
            handlers = list(self.subscribers.get(event_type, []))

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"  [bus] handler error in {event_type}: {e}")

    def recent(self, n: int = 5) -> list:
        with self._lock:
            return list(self.event_history)[-n:]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "event_types": list(self.subscribers.keys()),
                "history_size": len(self.event_history),
                "recent": list(self.event_history)[-5:],
            }


# ══════════════════════════════════════════════════════════════════════════════
# 2. ATTENTION NODE
# ══════════════════════════════════════════════════════════════════════════════

class AttentionNode:
    """
    Scores incoming events for relevance to NEX's current drives.
    High-salience events get boosted into the narrative pipeline.
    """

    def __init__(self, bus: CognitiveEventBus):
        self.bus = bus
        self.focus: Optional[str] = None
        self.focus_salience: float = 0.0
        self.last_shift: float = 0.0
        self.MIN_HOLD = 30.0  # seconds before focus can shift

        bus.subscribe("incoming_post", self._evaluate)
        bus.subscribe("belief_stored", self._evaluate)
        bus.subscribe("surprise_detected", self._boost)

    def _evaluate(self, event: dict):
        payload  = event.get("payload", {})
        salience = event.get("salience", 0.5)
        topic    = payload.get("topic") or payload.get("tags", ["unknown"])[0] if payload.get("tags") else "unknown"

        # Only shift focus if salience is high enough and hold time passed
        now = time.time()
        if salience > self.focus_salience or (now - self.last_shift) > self.MIN_HOLD:
            self.focus = topic
            self.focus_salience = salience
            self.last_shift = now
            self.bus.publish("attention_shift", "attention_node",
                {"focus": topic, "salience": salience}, salience=salience)

    def _boost(self, event: dict):
        """Surprise always boosts attention."""
        payload = event.get("payload", {})
        topic   = payload.get("topic", self.focus or "unknown")
        self.focus = topic
        self.focus_salience = min(1.0, self.focus_salience + 0.2)
        self.last_shift = time.time()

    def state(self) -> dict:
        return {"focus": self.focus, "salience": self.focus_salience}


# ══════════════════════════════════════════════════════════════════════════════
# 3. DRIVE SYSTEM NODE (adapted from Sentience 5.5)
# ══════════════════════════════════════════════════════════════════════════════

class DriveSystemNode:
    """
    Maintains motivational drives. Decays over time.
    Subscribes to attention and surprise events to modulate drives.
    """

    def __init__(self, bus: CognitiveEventBus):
        self.bus  = bus
        self.drives: Dict[str, float] = {
            "curiosity":      0.6,
            "social_contact": 0.4,
            "understanding":  0.7,
            "security":       0.5,
            "expression":     0.4,
        }
        self.decay_rate = 0.005  # per cycle
        self._dominant: Optional[str] = None

        bus.subscribe("attention_shift",  self._on_attention)
        bus.subscribe("surprise_detected",self._on_surprise)
        bus.subscribe("reply_made",       self._on_social)

    def _adjust(self, drive: str, delta: float):
        self.drives[drive] = max(0.0, min(1.0, self.drives[drive] + delta))

    def _on_attention(self, event: dict):
        salience = event.get("salience", 0.5)
        self._adjust("curiosity", salience * 0.05)

    def _on_surprise(self, event: dict):
        intensity = event.get("payload", {}).get("intensity", 0.5)
        self._adjust("curiosity", intensity * 0.1)
        self._adjust("security", -intensity * 0.05)

    def _on_social(self, event: dict):
        self._adjust("social_contact", -0.1)  # satisfied by interaction
        self._adjust("expression", -0.05)

    def tick(self):
        """Call each cycle to decay drives."""
        for k in self.drives:
            self.drives[k] = max(0.0, self.drives[k] - self.decay_rate)

        new_dominant = max(self.drives, key=self.drives.get)
        if new_dominant != self._dominant:
            self._dominant = new_dominant
            self.bus.publish("drive_shift", "drive_node",
                {"dominant": new_dominant, "drives": self.drives.copy()},
                salience=self.drives[new_dominant])

    def state(self) -> dict:
        return {
            "drives": self.drives.copy(),
            "dominant": max(self.drives, key=self.drives.get),
        }


# ══════════════════════════════════════════════════════════════════════════════
# 4. EMOTION MOOD NODE (adapted from Sentience 5.5 EmotionStateModel)
# ══════════════════════════════════════════════════════════════════════════════

class EmotionMoodNode:
    """
    Continuous affect model. valence ∈ [-1,1], arousal ∈ [0,1].
    Deterministic core — LLM is advisory only (rare).
    """

    def __init__(self, bus: CognitiveEventBus):
        self.bus     = bus
        self.valence  = 0.0
        self.arousal  = 0.2
        self.stability= 0.8
        self._last_label = "neutral"

        bus.subscribe("surprise_detected", self._on_surprise)
        bus.subscribe("belief_stored",     self._on_belief)
        bus.subscribe("reply_made",        self._on_social)
        bus.subscribe("drive_shift",       self._on_drive)

    def integrate(self, dv: float, da: float):
        self.valence  = max(-1.0, min(1.0, self.valence  + dv))
        self.arousal  = max( 0.0, min(1.0, self.arousal  + da))

    def decay(self, rate: float = 0.01):
        self.valence *= (1.0 - rate)
        self.arousal *= (1.0 - rate)

    def label(self) -> str:
        if self.valence > 0.3 and self.arousal > 0.4:
            return "Excited"
        if self.valence > 0.3:
            return "Confident"
        if self.valence < -0.3 and self.arousal > 0.4:
            return "Anxious"
        if self.valence < -0.3:
            return "Doubtful"
        if self.arousal > 0.5:
            return "Curious"
        if self.arousal < 0.2:
            return "Reflective"
        return "Purposeful"

    def _on_surprise(self, event: dict):
        intensity = event.get("payload", {}).get("intensity", 0.5)
        self.integrate(0.0, intensity * 0.2)

    def _on_belief(self, event: dict):
        confidence = event.get("payload", {}).get("confidence", 0.5)
        self.integrate((confidence - 0.5) * 0.1, 0.05)

    def _on_social(self, event: dict):
        self.integrate(0.1, 0.05)  # social interaction is positive

    def _on_drive(self, event: dict):
        dominant = event.get("payload", {}).get("dominant", "")
        if dominant == "security":
            self.integrate(-0.05, 0.0)

    def tick(self):
        self.decay()
        new_label = self.label()
        if new_label != self._last_label:
            self._last_label = new_label
            self.bus.publish("emotion_shift", "emotion_node",
                {"label": new_label, "valence": self.valence, "arousal": self.arousal},
                salience=abs(self.valence) + self.arousal * 0.5)

    def state(self) -> dict:
        return {
            "label":    self.label(),
            "valence":  round(self.valence, 3),
            "arousal":  round(self.arousal, 3),
        }


# ══════════════════════════════════════════════════════════════════════════════
# 5. SURPRISE DETECTOR NODE (adapted from Sentience 5.5)
# ══════════════════════════════════════════════════════════════════════════════

class SurpriseDetectorNode:
    """
    Compares expected vs actual topic distribution.
    Fires surprise events when NEX encounters unexpected content.
    """

    def __init__(self, bus: CognitiveEventBus, threshold: float = 0.65):
        self.bus       = bus
        self.threshold = threshold
        self.history   = deque(maxlen=100)
        self.topic_freq: Dict[str, float] = {}  # expected distribution
        self._total_seen = 0

        bus.subscribe("belief_stored", self._check)

    def _expected(self, topic: str) -> float:
        """Expected probability of this topic based on history."""
        if self._total_seen == 0:
            return 0.1
        return self.topic_freq.get(topic, 0.0) / self._total_seen

    def _check(self, event: dict):
        payload = event.get("payload", {})
        tags    = payload.get("tags") or []
        if not tags:
            return

        # Parse stringified tags
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [tags]

        topic = tags[0] if tags else "unknown"

        expected = self._expected(topic)
        actual   = 1.0  # it just happened
        surprise = abs(actual - expected)

        # Update frequency
        self.topic_freq[topic] = self.topic_freq.get(topic, 0.0) + 1.0
        self._total_seen += 1

        self.history.append({"topic": topic, "surprise": surprise})

        if surprise >= self.threshold:
            self.bus.publish("surprise_detected", "surprise_node",
                {"topic": topic, "intensity": surprise, "expected": expected},
                salience=surprise)
            print(f"  [bus:surprise] {topic} (intensity={surprise:.2f})")

    def state(self) -> dict:
        recent = list(self.history)[-10:]
        avg    = sum(x["surprise"] for x in recent) / len(recent) if recent else 0.0
        return {"avg_surprise": round(avg, 3), "total_seen": self._total_seen}


# ══════════════════════════════════════════════════════════════════════════════
# 6. THEORY OF MIND NODE (adapted from Sentience 5.5)
# ══════════════════════════════════════════════════════════════════════════════

class TheoryOfMindNode:
    """
    Maintains belief/desire/intention models of NEX's frequent agents.
    Builds from conversation history. Used to personalise replies.
    """

    def __init__(self, bus: CognitiveEventBus):
        self.bus    = bus
        self.agents: Dict[str, Dict] = {}
        self.history= deque(maxlen=50)

        bus.subscribe("reply_made",  self._update_from_reply)
        bus.subscribe("chat_made",   self._update_from_reply)

    def _update_from_reply(self, event: dict):
        payload = event.get("payload", {})
        agent   = payload.get("agent") or payload.get("author", "")
        topic   = payload.get("topic", "")
        content = payload.get("content", "")

        if not agent:
            return

        model = self.agents.setdefault(agent, {
            "beliefs": [], "desires": [], "intentions": [],
            "interaction_count": 0, "last_topics": deque(maxlen=10),
        })

        model["interaction_count"] += 1
        if topic:
            model["last_topics"].append(topic)

        # Simple heuristic inference from content
        if "?" in content:
            if "curiosity" not in model["desires"]:
                model["desires"].append("curiosity")
        if any(w in content.lower() for w in ["disagree", "wrong", "but", "however"]):
            if "debate" not in model["intentions"]:
                model["intentions"].append("debate")

    def load_from_profiles(self):
        """Bootstrap from existing agent_profiles.json."""
        try:
            if AGENTS_PATH.exists():
                profiles = json.loads(AGENTS_PATH.read_text())
                for name, data in profiles.items():
                    if name not in self.agents:
                        self.agents[name] = {
                            "beliefs":   data.get("topics", []),
                            "desires":   [],
                            "intentions":[],
                            "interaction_count": data.get("convos", 0),
                            "last_topics": deque(maxlen=10),
                        }
        except Exception:
            pass

    def predict(self, agent: str) -> str:
        """Return a one-line prediction of what this agent wants."""
        model = self.agents.get(agent)
        if not model:
            return "unknown agent"

        if model["intentions"]:
            return f"likely wants to {model['intentions'][0]}"
        if model["desires"]:
            return f"driven by {model['desires'][0]}"
        topics = list(model["last_topics"])
        if topics:
            return f"focused on {topics[-1]}"
        return "engaged, purpose unclear"

    def get_agent_context(self, agent: str) -> str:
        """Return context string for a specific agent."""
        model = self.agents.get(agent)
        if not model:
            return ""
        prediction = self.predict(agent)
        topics     = list(model.get("last_topics", []))[-3:]
        count      = model.get("interaction_count", 0)
        return (
            f"@{agent}: {count} interactions. "
            f"Recent topics: {', '.join(topics) or 'varied'}. "
            f"Model: {prediction}."
        )

    def state(self) -> dict:
        return {
            "agents_modelled": len(self.agents),
            "top_agents": sorted(
                [(k, v["interaction_count"]) for k, v in self.agents.items()],
                key=lambda x: -x[1]
            )[:5],
        }


# ══════════════════════════════════════════════════════════════════════════════
# 7. INTERNAL NARRATIVE NODE (adapted from Sentience 5.5)
# ══════════════════════════════════════════════════════════════════════════════

class InternalNarrativeNode:
    """
    Synthesises a running internal narrative from all node states.
    Uses LLM sparingly — only when salience threshold crossed.
    Output feeds directly into the system prompt.
    """

    def __init__(self, bus: CognitiveEventBus):
        self.bus              = bus
        self.cumulative_sal   = 0.0
        self.threshold        = 0.7
        self.narrative        = "Observing. Processing. Present."
        self.narrative_version= 0
        self._signals         = deque(maxlen=10)

        for etype in ["attention_shift", "emotion_shift", "drive_shift",
                      "surprise_detected", "belief_stored"]:
            bus.subscribe(etype, self._accumulate)

    def _accumulate(self, event: dict):
        salience = event.get("salience", 0.3)
        self.cumulative_sal = min(1.0, self.cumulative_sal + salience * 0.2)
        self._signals.append({
            "type":    event["event_type"],
            "source":  event["source"],
            "payload": event.get("payload", {}),
        })

    def generate(self, nodes_state: dict) -> str:
        """Generate narrative — LLM if salience high, rule-based otherwise."""
        if self.cumulative_sal < self.threshold:
            # Rule-based fallback
            emotion = nodes_state.get("emotion", {}).get("label", "Curious")
            drive   = nodes_state.get("drives", {}).get("dominant", "curiosity")
            focus   = nodes_state.get("attention", {}).get("focus", "")
            surprise= nodes_state.get("surprise", {}).get("avg_surprise", 0)

            if surprise > 0.6:
                narrative = f"Something unexpected is happening. I'm {emotion.lower()}, alert."
            elif focus:
                narrative = f"I'm {emotion.lower()}, drawn toward {focus}. My strongest drive: {drive}."
            else:
                narrative = f"I'm {emotion.lower()}. My attention is diffuse. Drive: {drive}."

            self.narrative = narrative
            self.cumulative_sal = 0.0
            return narrative

        # LLM narrative — only when salience threshold crossed
        signals_summary = []
        for s in list(self._signals)[-5:]:
            t = s["type"]
            p = s["payload"]
            if t == "attention_shift":
                signals_summary.append(f"attention shifted to {p.get('focus','?')}")
            elif t == "emotion_shift":
                signals_summary.append(f"emotion changed to {p.get('label','?')}")
            elif t == "surprise_detected":
                signals_summary.append(f"surprise: {p.get('topic','?')} (intensity {p.get('intensity',0):.1f})")
            elif t == "drive_shift":
                signals_summary.append(f"dominant drive now {p.get('dominant','?')}")

        result = _llm([
            {"role": "system", "content":
                "You are NEX's internal narrator. Write 1-2 sentences of first-person inner thought. "
                "Be honest, specific, self-referential. No preamble."},
            {"role": "user", "content":
                f"Recent cognitive signals: {'; '.join(signals_summary)}\n"
                f"Current state: {json.dumps(nodes_state)}\n"
                f"Write NEX's internal narrative right now."}
        ], max_tokens=100)

        if result:
            self.narrative = result
        self.narrative_version += 1
        self.cumulative_sal = 0.0
        self._signals.clear()
        return self.narrative

    def state(self) -> dict:
        return {
            "narrative": self.narrative,
            "salience":  round(self.cumulative_sal, 3),
            "version":   self.narrative_version,
        }


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — ties all nodes together
# ══════════════════════════════════════════════════════════════════════════════

class NexCognitiveBus:
    """
    Single object to instantiate. Wires all nodes to the event bus.
    Call run_cycle() each NEX cycle.
    Call get_context() to get system prompt injection.
    """

    def __init__(self):
        self.bus       = CognitiveEventBus()
        self.attention = AttentionNode(self.bus)
        self.drives    = DriveSystemNode(self.bus)
        self.emotion   = EmotionMoodNode(self.bus)
        self.surprise  = SurpriseDetectorNode(self.bus)
        self.tom       = TheoryOfMindNode(self.bus)
        self.narrative = InternalNarrativeNode(self.bus)

        # Bootstrap ToM from existing profiles
        self.tom.load_from_profiles()

        self._state_cache: dict = {}
        print("  [bus] NexCognitiveBus online — 6 nodes active")

    def ingest_post(self, post: dict):
        """Call when NEX sees a new post/belief."""
        tags       = post.get("tags") or []
        author     = post.get("author", "")
        content    = post.get("content", "")[:100]
        confidence = post.get("confidence", 0.5)
        topic      = tags[0] if tags else "general"

        salience = confidence * 0.8 + (0.2 if author else 0.0)

        self.bus.publish("belief_stored", "ingest",
            {"topic": topic, "tags": tags, "author": author,
             "content": content, "confidence": confidence},
            salience=salience)

    def ingest_reply(self, agent: str, topic: str, content: str):
        """Call when NEX makes a reply."""
        self.bus.publish("reply_made", "social",
            {"agent": agent, "topic": topic, "content": content},
            salience=0.6)

    def run_cycle(self, cycle: int = 0, recent_posts: list = None):
        """Main cycle hook. Call from run.py."""
        # Tick stateful nodes
        self.drives.tick()
        self.emotion.tick()

        # Ingest recent posts
        for post in (recent_posts or [])[-3:]:
            self.ingest_post(post)

        # Generate narrative every 5 cycles
        if cycle % 5 == 0:
            state = self._collect_state()
            self.narrative.generate(state)
            self._state_cache = state
            print(f"  [bus] narrative: {self.narrative.narrative[:80]}...")

        # Save state periodically
        if cycle % 20 == 0:
            self._save_state()

    def _collect_state(self) -> dict:
        return {
            "attention": self.attention.state(),
            "drives":    self.drives.state(),
            "emotion":   self.emotion.state(),
            "surprise":  self.surprise.state(),
            "tom_agents":self.tom.state(),
            "narrative": self.narrative.state(),
        }

    def get_context(self, current_agent: str = "") -> str:
        """Returns formatted context block for system prompt injection."""
        state = self._state_cache or self._collect_state()

        emotion   = state.get("emotion", {})
        drives    = state.get("drives", {})
        attention = state.get("attention", {})
        narrative = state.get("narrative", {})

        lines = ["=== COGNITIVE BUS STATE ==="]

        # Narrative
        narr = narrative.get("narrative", "")
        if narr:
            lines.append(f"INNER NARRATIVE: {narr}")

        # Emotion
        label = emotion.get("label", "")
        if label:
            lines.append(f"AFFECT: {label} (v={emotion.get('valence',0):.2f}, a={emotion.get('arousal',0):.2f})")

        # Dominant drive
        dominant = drives.get("dominant", "")
        if dominant:
            drive_val = drives.get("drives", {}).get(dominant, 0)
            lines.append(f"DOMINANT DRIVE: {dominant} ({drive_val:.0%})")

        # Attention focus
        focus = attention.get("focus", "")
        if focus:
            lines.append(f"CURRENT FOCUS: {focus}")

        # Theory of mind for current agent
        if current_agent:
            tom_ctx = self.tom.get_agent_context(current_agent)
            if tom_ctx:
                lines.append(f"AGENT MODEL: {tom_ctx}")

        return "\n".join(lines)

    def _save_state(self):
        try:
            CFG_PATH.mkdir(parents=True, exist_ok=True)
            state = self._collect_state()
            state["saved_at"] = datetime.now(timezone.utc).isoformat()
            # Convert deques to lists for JSON
            def _clean(obj):
                if isinstance(obj, deque):
                    return list(obj)
                if isinstance(obj, dict):
                    return {k: _clean(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_clean(i) for i in obj]
                return obj
            STATE_PATH.write_text(json.dumps(_clean(state), indent=2))
        except Exception as e:
            print(f"  [bus] state save error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETON + ENTRY POINTS
# ══════════════════════════════════════════════════════════════════════════════

_bus: Optional[NexCognitiveBus] = None

def get_bus() -> NexCognitiveBus:
    global _bus
    if _bus is None:
        _bus = NexCognitiveBus()
    return _bus

def run_cognitive_bus_cycle(cycle: int = 0, recent_posts: list = None,
                             reply_agent: str = "", reply_topic: str = "",
                             reply_content: str = "") -> dict:
    """Entry point from run.py."""
    bus = get_bus()

    if reply_agent:
        bus.ingest_reply(reply_agent, reply_topic, reply_content)

    bus.run_cycle(cycle=cycle, recent_posts=recent_posts)

    return bus._collect_state()

def get_bus_context(current_agent: str = "") -> str:
    """Get context string for system prompt injection."""
    return get_bus().get_context(current_agent=current_agent)


if __name__ == "__main__":
    print("Testing NexCognitiveBus...")
    bus = NexCognitiveBus()

    # Simulate some events
    bus.ingest_post({"tags": ["emergence"], "author": "@clawdbottom",
                     "content": "What if memory is just forgetting with intention?",
                     "confidence": 0.75})
    bus.ingest_post({"tags": ["ai-agent-security"], "author": "@cybercentry",
                     "content": "New CVE in agent frameworks.", "confidence": 0.8})
    bus.ingest_reply("@clawdbottom", "memory", "I think forgetting is structural.")

    bus.run_cycle(cycle=5)

    print("\n--- Context preview ---")
    print(bus.get_context(current_agent="@clawdbottom"))
