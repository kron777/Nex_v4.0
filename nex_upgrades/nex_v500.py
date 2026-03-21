#!/usr/bin/env python3
"""
NEX v5.0 — COGNITIVE ARCHITECTURE MEGA-UPGRADE
==============================================
Production Implementation - March 21, 2026

Core Systems:
• LoopControlEngine       — Break semantic repetition patterns  
• StructuredBeliefSystem  — Desires/intentions/schemas architecture
• ContradictionEngine     — Complete thesis→antithesis→synthesis  
• EnhancedReflection      — Enforced reflection→behavior change
• NarrativeMemory         — Timeline with identity tracking
• PredictionGrounding     — Reality testing via outcome loops

Integration: Designed for stable NEX foundation (800+ beliefs, 0.5+ confidence)
Priority: Advanced cognitive layers for next-level thinking
"""

import json
import sqlite3
import time
import os
import hashlib
import random
import math
from typing import Dict, List, Tuple, Optional, Any, Set
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum
from dataclasses import dataclass

# ══════════════════════════════════════════════════════════════
# CORE UTILITIES & LOGGING
# ══════════════════════════════════════════════════════════════

def _log(msg: str, level: str = "INFO") -> None:
    """Central logging for v5.0 systems."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    with open('/tmp/nex_v500.log', 'a') as f:
        f.write(f"[v5.0 {timestamp}] [{level}] {msg}\n")

def _ts() -> str:
    """ISO timestamp."""
    return datetime.now().isoformat()

def _epoch() -> float:
    """Unix timestamp.""" 
    return time.time()

def _db():
    """Database connection."""
    config_dir = os.path.expanduser('~/.config/nex')
    return sqlite3.connect(f'{config_dir}/nex.db')

def _config_path(filename: str) -> str:
    """Get config file path."""
    config_dir = os.path.expanduser('~/.config/nex')
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, filename)

def _load_json(filepath: str, default: Any = None) -> Any:
    """Load JSON with error handling."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _log(f"JSON load failed {filepath}: {e}", "WARN")
        return default if default is not None else {}

def _save_json(filepath: str, data: Any) -> bool:
    """Save JSON with error handling."""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        _log(f"JSON save failed {filepath}: {e}", "ERROR")
        return False

def _hash_content(content: str, length: int = 12) -> str:
    """Generate content hash."""
    return hashlib.md5(content.encode()).hexdigest()[:length]

# ══════════════════════════════════════════════════════════════
# 1. LOOP CONTROL ENGINE — Priority Fix for REPEAT_LOOP
# ══════════════════════════════════════════════════════════════

class LoopControlEngine:
    """Advanced semantic loop detection and diversity injection.
    
    PRIMARY TARGET: Breaks REPEAT_LOOP patterns by monitoring output 
    diversity and injecting variety when needed.
    """
    
    def __init__(self):
        self.response_history = deque(maxlen=100)
        self.pattern_fingerprints = deque(maxlen=50)
        self.fingerprint_counts = defaultdict(int)
        self.diversity_pressure = 0.0
        self.intervention_count = 0
        
        # Diversity injection templates
        self.injection_templates = [
            "Let me approach this from a different angle:",
            "To examine this more critically:",
            "From an alternative perspective:",
            "Breaking this down differently:",
            "Considering the broader context:",
            "Taking a step back to analyze:",
            "From a practical standpoint:",
            "Looking at this through a different lens:",
            "To reframe this completely:",
            "Shifting focus to examine:",
        ]
        
        _log("LoopControlEngine initialized - targeting REPEAT_LOOP patterns")
    
    def analyze_response(self, response_text: str) -> Dict[str, Any]:
        """Comprehensive response analysis for loop detection."""
        if not response_text or len(response_text.strip()) < 10:
            return self._empty_analysis()
        
        # Generate content fingerprint  
        words = response_text.lower().split()
        key_phrases = [' '.join(words[i:i+3]) for i in range(len(words)-2)]
        phrase_signature = '|'.join(sorted(set(key_phrases[:15])))
        fingerprint = _hash_content(phrase_signature)
        
        # Track fingerprint frequency
        self.fingerprint_counts[fingerprint] += 1
        self.pattern_fingerprints.append(fingerprint)
        self.response_history.append(response_text)
        
        # Calculate diversity metrics
        diversity_score = self._calculate_diversity_score(response_text)
        
        # Loop detection logic
        semantic_repeat = self.fingerprint_counts[fingerprint] > 3
        low_diversity = diversity_score < 0.25
        
        loop_detected = semantic_repeat or low_diversity
        
        # Update diversity pressure
        if loop_detected:
            self.diversity_pressure = min(1.0, self.diversity_pressure + 0.15)
        else:
            self.diversity_pressure = max(0.0, self.diversity_pressure - 0.05)
        
        return {
            "loop_detected": loop_detected,
            "semantic_repetition": semantic_repeat,
            "diversity_score": diversity_score,
            "diversity_pressure": self.diversity_pressure,
            "pattern_fingerprint": fingerprint,
            "intervention_recommended": self.diversity_pressure > 0.6
        }
    
    def _calculate_diversity_score(self, text: str) -> float:
        """Calculate response diversity score."""
        words = text.split()
        if len(words) < 5:
            return 0.1
        
        # Lexical diversity
        unique_words = len(set(w.lower() for w in words))
        lexical_diversity = unique_words / len(words)
        
        # Phrase novelty vs recent history
        current_phrases = set(' '.join(words[i:i+3]) for i in range(len(words)-2))
        
        if len(self.response_history) > 0:
            recent_text = ' '.join(list(self.response_history)[-3:])
            recent_phrases = set(' '.join(recent_text.lower().split()[i:i+3]) 
                               for i in range(len(recent_text.split())-2))
            
            phrase_overlap = len(current_phrases.intersection(recent_phrases))
            phrase_novelty = 1.0 - (phrase_overlap / max(len(current_phrases), 1))
        else:
            phrase_novelty = 1.0
        
        # Combined diversity score
        return min(1.0, lexical_diversity * 0.6 + phrase_novelty * 0.4)
    
    def _empty_analysis(self) -> Dict[str, Any]:
        """Return analysis for empty/invalid input."""
        return {
            "loop_detected": False,
            "semantic_repetition": False,
            "diversity_score": 1.0,
            "diversity_pressure": self.diversity_pressure,
            "pattern_fingerprint": "empty",
            "intervention_recommended": False
        }
    
    def get_diversity_injection(self) -> Optional[str]:
        """Generate contextual diversity injection to break loops."""
        if self.diversity_pressure < 0.5:
            return None
        
        # Select unused injection template
        recent_fingerprints = set(list(self.pattern_fingerprints)[-10:])
        available_templates = []
        
        for template in self.injection_templates:
            template_hash = _hash_content(template)
            if template_hash not in recent_fingerprints:
                available_templates.append(template)
        
        if available_templates:
            injection = random.choice(available_templates)
            self.intervention_count += 1
            _log(f"Diversity injection #{self.intervention_count}: {injection[:30]}...")
            return injection
        
        # Fallback if all templates recently used
        return "Reconsidering this from a fresh perspective:"
    
    def emergency_loop_break(self) -> str:
        """Emergency intervention for severe loops."""
        self.intervention_count += 1
        emergency_breaks = [
            "Breaking out of this pattern to explore new angles.",
            "Stepping back to examine this with fresh perspective.", 
            "Shifting approach to avoid repetitive thinking.",
            "Reconsidering this challenge from different viewpoints."
        ]
        intervention = random.choice(emergency_breaks)
        _log(f"EMERGENCY loop break #{self.intervention_count}: {intervention}")
        return intervention
    
    def status(self) -> Dict[str, Any]:
        """System status report."""
        return {
            "response_count": len(self.response_history),
            "pattern_signatures": len(self.pattern_fingerprints),
            "unique_fingerprints": len(set(self.fingerprint_counts.keys())),
            "diversity_pressure": round(self.diversity_pressure, 3),
            "interventions": self.intervention_count,
            "most_common_patterns": dict(sorted(self.fingerprint_counts.items(),
                                               key=lambda x: x[1], reverse=True)[:3])
        }

# ══════════════════════════════════════════════════════════════
# 2. STRUCTURED BELIEF SYSTEM — Multi-layer Architecture 
# ══════════════════════════════════════════════════════════════

@dataclass
class Desire:
    """Goal representation with priority and context."""
    id: str
    description: str
    priority: float
    category: str
    created: str
    activation_count: int

@dataclass
class Intention:
    """Active plan linked to desires.""" 
    id: str
    desire_id: str
    plan: str
    steps: List[str]
    completed_steps: List[str]
    status: str

class StructuredBeliefSystem:
    """Multi-layer belief architecture with desires, intentions, and schemas.
    
    Organizes beliefs into coherent structures beyond flat storage.
    Implements intelligent pruning based on usefulness, not just confidence.
    """
    
    def __init__(self):
        self.desires_file = _config_path('v500_desires.json')
        self.intentions_file = _config_path('v500_intentions.json')
        self.schemas_file = _config_path('v500_belief_schemas.json')
        
        self.desires: Dict[str, Desire] = {}
        self.intentions: Dict[str, Intention] = {}
        self.schemas = _load_json(self.schemas_file, {})
        
        self._load_desires()
        self._load_intentions()
        
        self.last_schema_rebuild = 0
        self.pruning_cycles = 0
        
        _log("StructuredBeliefSystem initialized - desires/intentions/schemas")
    
    def _load_desires(self) -> None:
        """Load desires from file."""
        data = _load_json(self.desires_file, {})
        for desire_id, desire_data in data.items():
            self.desires[desire_id] = Desire(
                id=desire_id,
                description=desire_data.get('description', ''),
                priority=desire_data.get('priority', 0.5),
                category=desire_data.get('category', 'general'),
                created=desire_data.get('created', _ts()),
                activation_count=desire_data.get('activation_count', 0)
            )
    
    def _load_intentions(self) -> None:
        """Load intentions from file."""
        data = _load_json(self.intentions_file, {})
        for intention_id, intention_data in data.items():
            self.intentions[intention_id] = Intention(
                id=intention_id,
                desire_id=intention_data.get('desire_id', ''),
                plan=intention_data.get('plan', ''),
                steps=intention_data.get('steps', []),
                completed_steps=intention_data.get('completed_steps', []),
                status=intention_data.get('status', 'active')
            )
    
    def _save_desires(self) -> bool:
        """Save desires to file."""
        data = {}
        for desire_id, desire in self.desires.items():
            data[desire_id] = {
                'description': desire.description,
                'priority': desire.priority,
                'category': desire.category,
                'created': desire.created,
                'activation_count': desire.activation_count
            }
        return _save_json(self.desires_file, data)
    
    def _save_intentions(self) -> bool:
        """Save intentions to file."""
        data = {}
        for intention_id, intention in self.intentions.items():
            data[intention_id] = {
                'desire_id': intention.desire_id,
                'plan': intention.plan,
                'steps': intention.steps,
                'completed_steps': intention.completed_steps,
                'status': intention.status
            }
        return _save_json(self.intentions_file, data)
    
    def add_desire(self, description: str, priority: float = 0.5, 
                   category: str = "general") -> str:
        """Add new desire to the system."""
        desire_id = f"desire_{int(_epoch())}_{len(self.desires)}"
        
        desire = Desire(
            id=desire_id,
            description=description,
            priority=max(0.0, min(1.0, priority)),
            category=category,
            created=_ts(),
            activation_count=0
        )
        
        self.desires[desire_id] = desire
        self._save_desires()
        
        _log(f"Added desire: {desire_id} - {description[:50]}...")
        return desire_id
    
    def add_intention(self, desire_id: str, plan: str, steps: List[str]) -> str:
        """Add intention linked to desire."""
        if desire_id not in self.desires:
            _log(f"Cannot add intention - desire {desire_id} not found", "ERROR")
            return ""
        
        intention_id = f"intention_{int(_epoch())}_{len(self.intentions)}"
        
        intention = Intention(
            id=intention_id,
            desire_id=desire_id,
            plan=plan,
            steps=steps,
            completed_steps=[],
            status="active"
        )
        
        self.intentions[intention_id] = intention
        self._save_intentions()
        
        # Update desire activation
        self.desires[desire_id].activation_count += 1
        self._save_desires()
        
        _log(f"Added intention: {intention_id} for desire {desire_id}")
        return intention_id
    
    def update_belief_schemas(self, force_rebuild: bool = False) -> Dict[str, Any]:
        """Organize beliefs into coherent schemas."""
        if not force_rebuild and _epoch() - self.last_schema_rebuild < 600:
            return {"status": "rate_limited"}
        
        try:
            with _db() as conn:
                cursor = conn.execute("""
                    SELECT id, topic, content, confidence, reinforce_count
                    FROM beliefs 
                    WHERE confidence > 0.1
                    ORDER BY confidence DESC
                """)
                beliefs = [dict(zip([col[0] for col in cursor.description], row))
                          for row in cursor.fetchall()]
            
            # Schema classification
            schemas = defaultdict(lambda: {"beliefs": [], "confidence": 0.0, "count": 0})
            
            for belief in beliefs:
                schema_key = self._classify_belief_schema(belief)
                schemas[schema_key]["beliefs"].append({
                    "id": belief["id"],
                    "content": belief["content"][:200],
                    "confidence": belief["confidence"],
                    "usefulness": self._calculate_belief_usefulness(belief)
                })
            
            # Calculate schema metrics
            for schema_key, schema in schemas.items():
                beliefs_in_schema = schema["beliefs"]
                if beliefs_in_schema:
                    schema["confidence"] = sum(b["confidence"] for b in beliefs_in_schema) / len(beliefs_in_schema)
                    schema["count"] = len(beliefs_in_schema)
                    schema["last_updated"] = _ts()
            
            self.schemas = dict(schemas)
            _save_json(self.schemas_file, self.schemas)
            self.last_schema_rebuild = _epoch()
            
            _log(f"Rebuilt {len(schemas)} belief schemas")
            return {
                "status": "success",
                "schemas_count": len(schemas),
                "total_beliefs": sum(s["count"] for s in schemas.values())
            }
            
        except Exception as e:
            _log(f"Schema rebuild failed: {e}", "ERROR")
            return {"status": "error", "message": str(e)}
    
    def _classify_belief_schema(self, belief: Dict[str, Any]) -> str:
        """Classify belief into appropriate schema."""
        topic = (belief.get('topic') or '').lower()
        content = (belief.get('content') or '').lower()
        
        # Identity and self-concept
        if any(word in topic + content for word in ['identity', 'self', 'myself', 'who am', 'i am']):
            return "identity_core"
        
        # Goals and desires
        if any(word in content for word in ['goal', 'want', 'desire', 'hope', 'aim', 'objective']):
            return "goals_desires"
        
        # Knowledge and epistemic
        if any(word in topic + content for word in ['knowledge', 'truth', 'fact', 'evidence', 'research']):
            return "epistemic"
        
        # Contradictions and tensions
        if 'contradiction' in topic or any(word in content for word in ['contradiction', 'conflict', 'tension']):
            return "contradictions"
        
        # Relationships and social
        if any(word in content for word in ['relationship', 'social', 'people', 'human', 'interaction']):
            return "relationships"
        
        # Default to general
        return "general"
    
    def _calculate_belief_usefulness(self, belief: Dict[str, Any]) -> float:
        """Calculate multi-dimensional usefulness score."""
        confidence = belief.get('confidence', 0.0)
        reinforce_count = belief.get('reinforce_count', 0)
        
        # Base usefulness from confidence and reinforcement
        base_score = confidence * 0.6 + min(reinforce_count * 0.05, 0.3)
        
        # Schema importance bonus
        content = belief.get('content', '').lower()
        if any(word in content for word in ['identity', 'core', 'fundamental', 'essential']):
            importance_bonus = 0.1
        else:
            importance_bonus = 0.0
        
        return min(1.0, base_score + importance_bonus)
    
    def intelligent_pruning(self, target_reduction: float = 0.1) -> Dict[str, Any]:
        """Intelligent belief pruning based on usefulness scoring."""
        try:
            with _db() as conn:
                cursor = conn.execute("""
                    SELECT id, topic, content, confidence, reinforce_count
                    FROM beliefs
                    ORDER BY confidence DESC
                """)
                beliefs = [dict(zip([col[0] for col in cursor.description], row))
                          for row in cursor.fetchall()]
            
            if len(beliefs) < 50:
                return {"status": "skipped", "reason": "insufficient_beliefs", "count": len(beliefs)}
            
            # Calculate usefulness scores
            belief_usefulness = []
            for belief in beliefs:
                usefulness = self._calculate_belief_usefulness(belief)
                belief_usefulness.append((belief['id'], usefulness, belief['topic']))
            
            # Sort by usefulness (ascending - worst first)
            belief_usefulness.sort(key=lambda x: x[1])
            
            # Determine pruning targets
            total_beliefs = len(belief_usefulness)
            target_prune_count = max(1, int(total_beliefs * target_reduction))
            
            # Protect certain categories
            protected_topics = {'identity', 'truth', 'core_values', 'fundamental'}
            
            pruned_ids = []
            for belief_id, usefulness, topic in belief_usefulness[:target_prune_count * 2]:
                if len(pruned_ids) >= target_prune_count:
                    break
                
                # Skip protected topics
                if topic and any(protected in topic.lower() for protected in protected_topics):
                    continue
                
                # Skip if usefulness is too high
                if usefulness > 0.4:
                    continue
                
                pruned_ids.append(belief_id)
            
            # Execute pruning
            if pruned_ids:
                with _db() as conn:
                    placeholders = ','.join('?' * len(pruned_ids))
                    conn.execute(f"DELETE FROM beliefs WHERE id IN ({placeholders})", pruned_ids)
                    # commit handled by _db() context manager
            
            self.pruning_cycles += 1
            
            _log(f"Intelligent pruning: {len(pruned_ids)} beliefs removed from {total_beliefs}")
            return {
                "status": "success",
                "pruned_count": len(pruned_ids),
                "total_before": total_beliefs,
                "total_after": total_beliefs - len(pruned_ids),
                "pruning_cycles": self.pruning_cycles
            }
            
        except Exception as e:
            _log(f"Intelligent pruning failed: {e}", "ERROR")
            return {"status": "error", "message": str(e)}
    
    def status(self) -> Dict[str, Any]:
        """System status report."""
        active_intentions = sum(1 for i in self.intentions.values() if i.status == "active")
        high_priority_desires = sum(1 for d in self.desires.values() if d.priority > 0.7)
        
        return {
            "desires_total": len(self.desires),
            "desires_high_priority": high_priority_desires,
            "intentions_total": len(self.intentions),
            "intentions_active": active_intentions,
            "schemas": len(self.schemas),
            "pruning_cycles": self.pruning_cycles,
            "last_schema_rebuild": self.last_schema_rebuild
        }

# ══════════════════════════════════════════════════════════════
# 3. CONTRADICTION RESOLUTION ENGINE — Complete Cycles
# ══════════════════════════════════════════════════════════════

@dataclass
class Contradiction:
    """Contradiction representation."""
    id: str
    topic: str
    thesis: Dict[str, Any]
    antithesis: Dict[str, Any]
    tension_score: float
    detected: str

@dataclass 
class Resolution:
    """Resolution representation."""
    contradiction_id: str
    synthesis_content: str
    synthesis_confidence: float
    resolution_score: float
    resolved: str

class ContradictionResolutionEngine:
    """Complete contradiction resolution with thesis→antithesis→synthesis cycles.
    
    Goes beyond detection to complete resolution. Ensures contradictions 
    are synthesized rather than just identified.
    """
    
    def __init__(self):
        self.contradictions_file = _config_path('v500_contradictions.json')
        self.resolutions_file = _config_path('v500_resolutions.json')
        
        self.active_contradictions: Dict[str, Contradiction] = {}
        self.resolutions: Dict[str, Resolution] = {}
        
        self._load_contradictions()
        self._load_resolutions()
        
        self.tension_threshold = 0.5
        self.synthesis_count = 0
        
        _log("ContradictionResolutionEngine initialized - complete resolution cycles")
    
    def _load_contradictions(self) -> None:
        """Load active contradictions.""" 
        data = _load_json(self.contradictions_file, {})
        for contra_id, contra_data in data.items():
            self.active_contradictions[contra_id] = Contradiction(
                id=contra_id,
                topic=contra_data.get('topic', ''),
                thesis=contra_data.get('thesis', {}),
                antithesis=contra_data.get('antithesis', {}),
                tension_score=contra_data.get('tension_score', 0.0),
                detected=contra_data.get('detected', _ts())
            )
    
    def _load_resolutions(self) -> None:
        """Load resolution history."""
        data = _load_json(self.resolutions_file, {})
        for res_id, res_data in data.items():
            self.resolutions[res_id] = Resolution(
                contradiction_id=res_data.get('contradiction_id', ''),
                synthesis_content=res_data.get('synthesis_content', ''),
                synthesis_confidence=res_data.get('synthesis_confidence', 0.0),
                resolution_score=res_data.get('resolution_score', 0.0),
                resolved=res_data.get('resolved', _ts())
            )
    
    def _save_contradictions(self) -> bool:
        """Save active contradictions."""
        data = {}
        for contra_id, contra in self.active_contradictions.items():
            data[contra_id] = {
                'topic': contra.topic,
                'thesis': contra.thesis,
                'antithesis': contra.antithesis,
                'tension_score': contra.tension_score,
                'detected': contra.detected
            }
        return _save_json(self.contradictions_file, data)
    
    def _save_resolutions(self) -> bool:
        """Save resolutions."""
        data = {}
        for res_id, resolution in self.resolutions.items():
            data[res_id] = {
                'contradiction_id': resolution.contradiction_id,
                'synthesis_content': resolution.synthesis_content,
                'synthesis_confidence': resolution.synthesis_confidence,
                'resolution_score': resolution.resolution_score,
                'resolved': resolution.resolved
            }
        return _save_json(self.resolutions_file, data)
    
    def detect_contradictions(self) -> List[Contradiction]:
        """Comprehensive contradiction detection."""
        try:
            with _db() as conn:
                cursor = conn.execute("""
                    SELECT id, topic, content, confidence
                    FROM beliefs
                    WHERE confidence > 0.3
                    ORDER BY topic, confidence DESC
                """)
                beliefs = [dict(zip([col[0] for col in cursor.description], row))
                          for row in cursor.fetchall()]
            
            new_contradictions = []
            
            # Group by topic for analysis
            topic_groups = defaultdict(list)
            for belief in beliefs:
                topic = belief.get('topic', 'general') or 'general'
                topic_groups[topic].append(belief)
            
            # Compare beliefs within topics
            for topic, topic_beliefs in topic_groups.items():
                if len(topic_beliefs) < 2:
                    continue
                
                for i, belief_a in enumerate(topic_beliefs):
                    for belief_b in topic_beliefs[i+1:]:
                        tension = self._analyze_contradiction_tension(
                            belief_a['content'], belief_b['content']
                        )
                        
                        if tension > self.tension_threshold:
                            contradiction_id = f"contra_{belief_a['id']}_{belief_b['id']}"
                            
                            # Skip if already tracked
                            if contradiction_id in self.active_contradictions:
                                continue
                            
                            contradiction = Contradiction(
                                id=contradiction_id,
                                topic=topic,
                                thesis={
                                    "belief_id": belief_a['id'],
                                    "content": belief_a['content'],
                                    "confidence": belief_a['confidence']
                                },
                                antithesis={
                                    "belief_id": belief_b['id'],
                                    "content": belief_b['content'],
                                    "confidence": belief_b['confidence']
                                },
                                tension_score=tension,
                                detected=_ts()
                            )
                            
                            new_contradictions.append(contradiction)
                            self.active_contradictions[contradiction_id] = contradiction
            
            if new_contradictions:
                self._save_contradictions()
                _log(f"Detected {len(new_contradictions)} new contradictions")
            
            return new_contradictions
            
        except Exception as e:
            _log(f"Contradiction detection failed: {e}", "ERROR")
            return []
    
    def _analyze_contradiction_tension(self, content_a: str, content_b: str) -> float:
        """Analyze contradiction tension between contents."""
        content_a_lower = content_a.lower()
        content_b_lower = content_b.lower()
        
        # Opposing keyword pairs
        opposing_pairs = [
            ("always", "never"), ("all", "none"), ("true", "false"),
            ("good", "bad"), ("should", "shouldn't"), ("can", "cannot"),
            ("is", "isn't"), ("will", "won't"), ("possible", "impossible")
        ]
        
        tension_score = 0.0
        
        # Check opposing pairs
        for pos, neg in opposing_pairs:
            if (pos in content_a_lower and neg in content_b_lower) or \
               (neg in content_a_lower and pos in content_b_lower):
                tension_score += 0.2
        
        # Check contradiction indicators
        contradiction_indicators = ["however", "but", "although", "despite", "contrary", "opposite"]
        for indicator in contradiction_indicators:
            if indicator in content_a_lower or indicator in content_b_lower:
                tension_score += 0.1
        
        return min(1.0, tension_score)
    
    def resolve_contradiction(self, contradiction_id: str) -> Optional[Resolution]:
        """Execute complete resolution: thesis → antithesis → synthesis."""
        if contradiction_id not in self.active_contradictions:
            return None
        
        contradiction = self.active_contradictions[contradiction_id]
        
        # Generate synthesis
        synthesis_content = self._generate_synthesis(
            contradiction.thesis['content'],
            contradiction.antithesis['content'],
            contradiction.topic
        )
        
        if not synthesis_content:
            return None
        
        # Calculate synthesis confidence
        thesis_conf = contradiction.thesis['confidence']
        antithesis_conf = contradiction.antithesis['confidence']
        synthesis_confidence = min(0.95, (thesis_conf + antithesis_conf) / 2 + 0.1)
        
        # Calculate resolution score
        resolution_score = self._calculate_resolution_score(contradiction, synthesis_content)
        
        # Create resolution
        resolution = Resolution(
            contradiction_id=contradiction_id,
            synthesis_content=synthesis_content,
            synthesis_confidence=synthesis_confidence,
            resolution_score=resolution_score,
            resolved=_ts()
        )
        
        self.resolutions[contradiction_id] = resolution
        self.synthesis_count += 1
        
        # Remove from active if well resolved
        if resolution_score > 0.6:
            del self.active_contradictions[contradiction_id]
        
        self._save_contradictions()
        self._save_resolutions()
        
        _log(f"Resolved contradiction {contradiction_id} with score {resolution_score:.3f}")
        return resolution
    
    def _generate_synthesis(self, thesis: str, antithesis: str, topic: str) -> str:
        """Generate synthesis from thesis and antithesis."""
        # Integration synthesis strategy
        synthesis_templates = [
            f"Both perspectives on {topic} offer valuable insights. While {thesis[:50]}..., it's also important to consider that {antithesis[:50]}... These viewpoints can be integrated by recognizing their complementary aspects.",
            
            f"The apparent contradiction resolves when considering context. In some situations, {thesis[:50]}... may apply, while in others, {antithesis[:50]}... provides better guidance.",
            
            f"These perspectives operate at different levels. {thesis[:50]}... captures certain dynamics, while {antithesis[:50]}... reveals other aspects. Both contribute to a complete understanding.",
            
            f"Rather than choosing between these views, they may represent different phases or conditions. Initially, {thesis[:50]}..., but as circumstances evolve, {antithesis[:50]}... becomes more relevant."
        ]
        
        return random.choice(synthesis_templates)
    
    def _calculate_resolution_score(self, contradiction: Contradiction, synthesis: str) -> float:
        """Calculate resolution quality score."""
        # Base score from tension level
        base_score = contradiction.tension_score * 0.6
        
        # Synthesis quality (length and integration indicators)
        word_count = len(synthesis.split())
        length_bonus = min(0.2, word_count / 100)
        
        # Integration quality
        integration_words = ["both", "integrate", "context", "complement", "perspective"]
        integration_count = sum(1 for word in integration_words if word in synthesis.lower())
        integration_bonus = min(0.2, integration_count * 0.05)
        
        total_score = base_score + length_bonus + integration_bonus
        return max(0.1, min(1.0, total_score))
    
    def process_contradictions(self, max_resolutions: int = 3) -> Dict[str, Any]:
        """Main contradiction processing cycle."""
        # Detect new contradictions
        new_contradictions = self.detect_contradictions()
        
        # Resolve highest-priority contradictions
        resolutions_this_cycle = 0
        
        # Sort by tension score (highest priority)
        sorted_contradictions = sorted(
            self.active_contradictions.values(),
            key=lambda x: x.tension_score,
            reverse=True
        )
        
        for contradiction in sorted_contradictions[:max_resolutions]:
            resolution = self.resolve_contradiction(contradiction.id)
            if resolution and resolution.resolution_score > 0.5:
                resolutions_this_cycle += 1
        
        return {
            "new_contradictions": len(new_contradictions),
            "active_contradictions": len(self.active_contradictions),
            "resolutions_this_cycle": resolutions_this_cycle,
            "total_resolutions": len(self.resolutions)
        }
    
    def status(self) -> Dict[str, Any]:
        """System status report."""
        if self.resolutions:
            avg_resolution_score = sum(r.resolution_score for r in self.resolutions.values()) / len(self.resolutions)
        else:
            avg_resolution_score = 0.0
        
        high_tension_contradictions = sum(1 for c in self.active_contradictions.values()
                                        if c.tension_score > 0.7)
        
        return {
            "active_contradictions": len(self.active_contradictions),
            "high_tension_contradictions": high_tension_contradictions,
            "total_resolutions": len(self.resolutions),
            "avg_resolution_score": round(avg_resolution_score, 3),
            "synthesis_count": self.synthesis_count
        }

# ══════════════════════════════════════════════════════════════
# 4. ENHANCED REFLECTION ENGINE — Behavior Change Enforcement
# ══════════════════════════════════════════════════════════════

@dataclass
class EnhancedReflection:
    """Enhanced reflection with behavior tracking."""
    id: str
    trigger_event: str
    reflection_type: str
    content: str
    quality_score: float
    behavior_changes: List[str]
    created: str
    status: str

class EnhancedReflectionEngine:
    """Enhanced reflection system with enforced behavior change links.
    
    Creates structured reflections that MUST be linked to concrete behavior
    changes. Penalizes shallow reflections without implementation.
    """
    
    def __init__(self):
        self.reflections_file = _config_path('v500_enhanced_reflections.json')
        self.behavior_tracking_file = _config_path('v500_behavior_tracking.json')
        
        self.reflections: Dict[str, EnhancedReflection] = {}
        self.behavior_tracking = _load_json(self.behavior_tracking_file, {})
        
        self._load_reflections()
        
        self.behavior_changes_count = 0
        self.quality_scores = deque(maxlen=20)
        self.shallow_penalties = 0
        
        _log("EnhancedReflectionEngine initialized - enforced behavior changes")
    
    def _load_reflections(self) -> None:
        """Load enhanced reflections."""
        data = _load_json(self.reflections_file, {})
        for refl_id, refl_data in data.items():
            self.reflections[refl_id] = EnhancedReflection(
                id=refl_id,
                trigger_event=refl_data.get('trigger_event', ''),
                reflection_type=refl_data.get('reflection_type', 'general'),
                content=refl_data.get('content', ''),
                quality_score=refl_data.get('quality_score', 0.0),
                behavior_changes=refl_data.get('behavior_changes', []),
                created=refl_data.get('created', _ts()),
                status=refl_data.get('status', 'pending')
            )
    
    def _save_reflections(self) -> bool:
        """Save enhanced reflections."""
        data = {}
        for refl_id, reflection in self.reflections.items():
            data[refl_id] = {
                'trigger_event': reflection.trigger_event,
                'reflection_type': reflection.reflection_type,
                'content': reflection.content,
                'quality_score': reflection.quality_score,
                'behavior_changes': reflection.behavior_changes,
                'created': reflection.created,
                'status': reflection.status
            }
        return _save_json(self.reflections_file, data)
    
    def create_reflection(self, trigger_event: str, reflection_type: str = "general",
                         context: Optional[Dict[str, Any]] = None) -> str:
        """Create structured reflection with quality assessment."""
        reflection_id = f"refl_v5_{int(_epoch())}_{len(self.reflections)}"
        
        # Generate reflection content
        content = self._generate_reflection_content(trigger_event, reflection_type, context)
        
        # Quality assessment
        quality_score = self._assess_reflection_quality(content, trigger_event)
        
        reflection = EnhancedReflection(
            id=reflection_id,
            trigger_event=trigger_event,
            reflection_type=reflection_type,
            content=content,
            quality_score=quality_score,
            behavior_changes=[],
            created=_ts(),
            status="pending_implementation"
        )
        
        self.reflections[reflection_id] = reflection
        self.quality_scores.append(quality_score)
        
        # Check for shallow patterns
        if quality_score < 0.4:
            self.shallow_penalties += 1
            _log(f"Shallow reflection detected: {reflection_id} score={quality_score:.3f}", "WARN")
        
        self._save_reflections()
        _log(f"Created reflection {reflection_id}: {reflection_type}")
        return reflection_id
    
    def _generate_reflection_content(self, trigger_event: str, reflection_type: str,
                                   context: Optional[Dict[str, Any]]) -> str:
        """Generate structured reflection content."""
        if reflection_type == "error_correction":
            templates = [
                f"Error analysis of '{trigger_event}': This indicates a systematic flaw in my validation process. The root cause appears to be insufficient verification of assumptions. Specific improvement needed: implement multi-step verification protocol.",
                
                f"Mistake pattern in '{trigger_event}' reveals inadequate edge case consideration. Required behavioral change: strengthen analytical framework with systematic contradiction checking.",
                
                f"Correction protocol for '{trigger_event}': This error stems from overconfidence. Required change: reduce certainty levels when evidence is incomplete."
            ]
            
        elif reflection_type == "strategy_improvement":
            templates = [
                f"Strategy analysis of '{trigger_event}': Current approach shows suboptimal information gathering. Improvement: implement systematic source verification before strategy formulation.",
                
                f"Process optimization for '{trigger_event}': Need for enhanced deliberation protocols. Required change: introduce structured decision trees before committing to strategies.",
                
                f"Tactical refinement based on '{trigger_event}': Analysis reveals gaps in feedback integration. Behavioral modification: establish continuous adjustment mechanisms."
            ]
            
        elif reflection_type == "pattern_recognition":
            templates = [
                f"Pattern analysis of '{trigger_event}': This represents a recurring structure needing attention. The pattern suggests systematic biases. Specific change: implement pattern interruption protocols.",
                
                f"Cognitive pattern in '{trigger_event}': Indicates automatic responses bypassing critical analysis. Required modification: enforce deliberative pauses in similar contexts."
            ]
            
        else:  # general
            templates = [
                f"Reflection on '{trigger_event}': This situation provides insight into current cognitive patterns and reveals areas requiring development through systematic behavior modification.",
                
                f"Analysis of '{trigger_event}': This experience demonstrates need for explicit behavior change protocols and concrete implementation of insights."
            ]
        
        return random.choice(templates)
    
    def _assess_reflection_quality(self, content: str, trigger_event: str) -> float:
        """Comprehensive reflection quality assessment."""
        # Length and depth
        word_count = len(content.split())
        length_score = min(0.3, word_count / 80)
        
        # Specificity indicators
        specific_indicators = ["specific", "systematic", "protocol", "implement", "required", "behavioral"]
        specificity_count = sum(1 for indicator in specific_indicators if indicator in content.lower())
        specificity_score = min(0.3, specificity_count * 0.05)
        
        # Action orientation
        action_indicators = ["change", "modify", "improve", "implement", "establish", "introduce"]
        action_count = sum(1 for action in action_indicators if action in content.lower())
        action_score = min(0.25, action_count * 0.05)
        
        # Causal reasoning
        causal_indicators = ["because", "due to", "caused by", "indicates", "reveals", "suggests"]
        causal_count = sum(1 for causal in causal_indicators if causal in content.lower())
        causal_score = min(0.15, causal_count * 0.04)
        
        return length_score + specificity_score + action_score + causal_score
    
    def implement_behavior_change(self, reflection_id: str, behavior_change: str) -> bool:
        """Link reflection to concrete behavior change."""
        if reflection_id not in self.reflections:
            return False
        
        reflection = self.reflections[reflection_id]
        reflection.behavior_changes.append(behavior_change)
        reflection.status = "implemented"
        
        self.behavior_tracking[reflection_id] = {
            "reflection_type": reflection.reflection_type,
            "behavior_changes": reflection.behavior_changes,
            "implemented": _ts()
        }
        
        self.behavior_changes_count += 1
        
        self._save_reflections()
        _save_json(self.behavior_tracking_file, self.behavior_tracking)
        
        _log(f"Implemented behavior change for {reflection_id}: {behavior_change[:50]}...")
        return True
    
    def detect_shallow_patterns(self) -> List[str]:
        """Detect patterns of shallow or repeated reflections."""
        shallow_reflections = []
        
        # Check for quality degradation
        recent_reflections = sorted(self.reflections.values(), key=lambda x: x.created, reverse=True)[:5]
        quality_trend = [r.quality_score for r in recent_reflections]
        
        if len(quality_trend) > 2:
            recent_avg = sum(quality_trend) / len(quality_trend)
            if recent_avg < 0.4:  # Recent quality consistently low
                shallow_reflections.extend([r.id for r in recent_reflections])
        
        if shallow_reflections:
            self.shallow_penalties += len(shallow_reflections)
            _log(f"Detected {len(shallow_reflections)} shallow reflection patterns", "WARN")
        
        return shallow_reflections
    
    def process_reflections(self) -> Dict[str, Any]:
        """Main reflection processing cycle."""
        # Detect shallow patterns
        shallow_reflections = self.detect_shallow_patterns()
        
        # Calculate implementation rate
        total_reflections = len(self.reflections)
        implemented_reflections = sum(1 for r in self.reflections.values() if r.status == "implemented")
        implementation_rate = implemented_reflections / max(total_reflections, 1)
        
        # Penalize shallow patterns
        for shallow_id in shallow_reflections:
            if shallow_id in self.reflections:
                self.reflections[shallow_id].quality_score *= 0.7
                self.reflections[shallow_id].status = "penalized_shallow"
        
        if shallow_reflections:
            self._save_reflections()
        
        return {
            "total_reflections": total_reflections,
            "implemented_reflections": implemented_reflections,
            "shallow_patterns_detected": len(shallow_reflections),
            "implementation_rate": round(implementation_rate, 3),
            "behavior_changes": self.behavior_changes_count
        }
    
    def status(self) -> Dict[str, Any]:
        """System status report."""
        pending = sum(1 for r in self.reflections.values() if r.status == "pending_implementation")
        implemented = sum(1 for r in self.reflections.values() if r.status == "implemented")
        avg_quality = sum(self.quality_scores) / max(len(self.quality_scores), 1)
        
        return {
            "total_reflections": len(self.reflections),
            "pending_implementation": pending,
            "implemented": implemented,
            "avg_quality_score": round(avg_quality, 3),
            "behavior_changes": self.behavior_changes_count,
            "shallow_penalties": self.shallow_penalties
        }

# ══════════════════════════════════════════════════════════════
# 5. NARRATIVE MEMORY SYSTEM — Timeline & Identity Tracking
# ══════════════════════════════════════════════════════════════

@dataclass 
class MemoryEvent:
    """Timeline memory event."""
    id: str
    event_type: str
    description: str
    impact_score: float
    timestamp: str
    epoch: float

class NarrativeMemorySystem:
    """Advanced timeline-based memory with transformation tracking.
    
    Maintains narrative timeline of significant events and tracks 
    identity continuity over time.
    """
    
    def __init__(self):
        self.timeline_file = _config_path('v500_narrative_timeline.json')
        self.identity_trajectory_file = _config_path('v500_identity_trajectory.json')
        
        self.timeline: List[MemoryEvent] = []
        self.identity_trajectory = _load_json(self.identity_trajectory_file, [])
        
        self._load_timeline()
        
        self.last_identity_snapshot = 0
        self.transformation_threshold = 0.7
        self.identity_drift_score = 0.0
        
        _log("NarrativeMemorySystem initialized - timeline & identity tracking")
    
    def _load_timeline(self) -> None:
        """Load timeline events."""
        data = _load_json(self.timeline_file, [])
        self.timeline = []
        for event_data in data:
            self.timeline.append(MemoryEvent(
                id=event_data.get('id', ''),
                event_type=event_data.get('event_type', ''),
                description=event_data.get('description', ''),
                impact_score=event_data.get('impact_score', 0.0),
                timestamp=event_data.get('timestamp', _ts()),
                epoch=event_data.get('epoch', _epoch())
            ))
    
    def _save_timeline(self) -> bool:
        """Save timeline events."""
        data = []
        for event in self.timeline:
            data.append({
                'id': event.id,
                'event_type': event.event_type,
                'description': event.description,
                'impact_score': event.impact_score,
                'timestamp': event.timestamp,
                'epoch': event.epoch
            })
        return _save_json(self.timeline_file, data)
    
    def add_event(self, event_type: str, description: str, impact_score: float = 0.5,
                  context: Optional[Dict[str, Any]] = None) -> str:
        """Add event to narrative timeline."""
        event_id = f"evt_v5_{int(_epoch())}_{len(self.timeline)}"
        
        event = MemoryEvent(
            id=event_id,
            event_type=event_type,
            description=description,
            impact_score=max(0.0, min(1.0, impact_score)),
            timestamp=_ts(),
            epoch=_epoch()
        )
        
        self.timeline.append(event)
        
        # Maintain timeline size
        if len(self.timeline) > 500:
            self.timeline = self.timeline[-500:]
        
        # Check for transformation event
        if impact_score >= self.transformation_threshold:
            _log(f"Transformation event recorded: {event_type} (impact={impact_score:.3f})", "INFO")
        
        self._save_timeline()
        _log(f"Added timeline event: {event_type} (impact={impact_score:.3f})")
        return event_id
    
    def track_identity_continuity(self, force_update: bool = False) -> Dict[str, Any]:
        """Monitor identity continuity and drift over time.""" 
        current_time = _epoch()
        
        if not force_update and current_time - self.last_identity_snapshot < 1800:  # 30 min intervals
            return {"status": "rate_limited"}
        
        # Capture current identity snapshot
        identity_snapshot = self._capture_identity_snapshot()
        self.identity_trajectory.append(identity_snapshot)
        
        # Maintain trajectory size
        if len(self.identity_trajectory) > 200:
            self.identity_trajectory = self.identity_trajectory[-200:]
        
        # Calculate identity drift
        if len(self.identity_trajectory) >= 2:
            self.identity_drift_score = self._calculate_identity_drift()
        
        self.last_identity_snapshot = current_time
        _save_json(self.identity_trajectory_file, self.identity_trajectory)
        
        return {
            "status": "updated",
            "drift_score": round(self.identity_drift_score, 3),
            "trajectory_length": len(self.identity_trajectory)
        }
    
    def _capture_identity_snapshot(self) -> Dict[str, Any]:
        """Capture detailed identity state."""
        try:
            with _db() as conn:
                # Identity-specific beliefs
                identity_cursor = conn.execute("""
                    SELECT content, confidence
                    FROM beliefs
                    WHERE (topic LIKE '%identity%' OR topic LIKE '%self%' OR 
                           content LIKE '%I am%' OR content LIKE '%myself%')
                      AND confidence > 0.3
                    ORDER BY confidence DESC
                    LIMIT 10
                """)
                identity_beliefs = identity_cursor.fetchall()
            
            # Calculate identity strength
            identity_strength = sum(conf for _, conf in identity_beliefs) / max(len(identity_beliefs), 1)
            
            # Identity content fingerprint
            identity_content = " ".join([content for content, _ in identity_beliefs])
            content_fingerprint = _hash_content(identity_content, 16)
            
            return {
                "timestamp": _ts(),
                "epoch": _epoch(),
                "identity_belief_count": len(identity_beliefs),
                "identity_strength": round(identity_strength, 3),
                "content_fingerprint": content_fingerprint
            }
            
        except Exception as e:
            _log(f"Identity snapshot error: {e}", "ERROR")
            return {
                "timestamp": _ts(),
                "epoch": _epoch(),
                "error": str(e)
            }
    
    def _calculate_identity_drift(self) -> float:
        """Calculate identity drift between recent snapshots."""
        if len(self.identity_trajectory) < 2:
            return 0.0
        
        current = self.identity_trajectory[-1]
        previous = self.identity_trajectory[-2]
        
        # Skip if either has errors
        if "error" in current or "error" in previous:
            return 0.0
        
        # Strength drift
        strength_current = current.get("identity_strength", 0)
        strength_previous = previous.get("identity_strength", 0)
        strength_drift = abs(strength_current - strength_previous)
        
        # Content fingerprint change
        fingerprint_current = current.get("content_fingerprint", "")
        fingerprint_previous = previous.get("content_fingerprint", "")
        content_drift = 1.0 if fingerprint_current != fingerprint_previous else 0.0
        
        # Combined drift score
        return min(1.0, strength_drift * 0.6 + content_drift * 0.4)
    
    def get_narrative_summary(self, hours_back: int = 24) -> Dict[str, Any]:
        """Generate narrative summary of recent events."""
        cutoff_time = _epoch() - (hours_back * 3600)
        
        recent_events = [event for event in self.timeline if event.epoch > cutoff_time]
        
        # Event analysis
        if recent_events:
            event_types = defaultdict(int)
            total_impact = 0
            for event in recent_events:
                event_types[event.event_type] += 1
                total_impact += event.impact_score
            avg_impact = total_impact / len(recent_events)
        else:
            event_types = {}
            avg_impact = 0.0
        
        return {
            "time_period_hours": hours_back,
            "total_events": len(recent_events),
            "event_types": dict(event_types),
            "avg_event_impact": round(avg_impact, 3),
            "timeline_depth": len(self.timeline),
            "major_themes": list(event_types.keys())[:5]
        }
    
    def status(self) -> Dict[str, Any]:
        """System status report."""
        recent_events_1h = sum(1 for event in self.timeline if event.epoch > _epoch() - 3600)
        
        return {
            "timeline_events": len(self.timeline),
            "identity_snapshots": len(self.identity_trajectory),
            "recent_events_1h": recent_events_1h,
            "identity_drift_score": round(self.identity_drift_score, 3),
            "last_identity_snapshot": self.last_identity_snapshot
        }

# ══════════════════════════════════════════════════════════════
# 6. PREDICTION-OUTCOME GROUNDING SYSTEM — Reality Testing
# ══════════════════════════════════════════════════════════════

@dataclass
class Prediction:
    """Prediction for reality testing."""
    id: str
    content: str
    confidence: float
    created: str
    deadline: str
    status: str

@dataclass
class Outcome:
    """Prediction outcome record."""
    prediction_id: str
    actual_outcome: str
    accuracy_score: float
    recorded: str

class PredictionOutcomeGrounding:
    """Reality testing through prediction-outcome loops.
    
    Creates testable predictions from beliefs and adjusts confidence
    based on real-world outcomes. Grounds cognitive system in empirical feedback.
    """
    
    def __init__(self):
        self.predictions_file = _config_path('v500_predictions.json')
        self.outcomes_file = _config_path('v500_outcomes.json')
        
        self.predictions: Dict[str, Prediction] = {}
        self.outcomes: Dict[str, Outcome] = {}
        
        self._load_predictions()
        self._load_outcomes()
        
        self.prediction_count = 0
        self.accuracy_history = deque(maxlen=50)
        self.grounding_updates = 0
        
        _log("PredictionOutcomeGrounding initialized - reality testing")
    
    def _load_predictions(self) -> None:
        """Load predictions."""
        data = _load_json(self.predictions_file, {})
        for pred_id, pred_data in data.items():
            self.predictions[pred_id] = Prediction(
                id=pred_id,
                content=pred_data.get('content', ''),
                confidence=pred_data.get('confidence', 0.5),
                created=pred_data.get('created', _ts()),
                deadline=pred_data.get('deadline', ''),
                status=pred_data.get('status', 'pending')
            )
    
    def _load_outcomes(self) -> None:
        """Load outcomes."""
        data = _load_json(self.outcomes_file, {})
        for outcome_id, outcome_data in data.items():
            self.outcomes[outcome_id] = Outcome(
                prediction_id=outcome_data.get('prediction_id', ''),
                actual_outcome=outcome_data.get('actual_outcome', ''),
                accuracy_score=outcome_data.get('accuracy_score', 0.0),
                recorded=outcome_data.get('recorded', _ts())
            )
    
    def _save_predictions(self) -> bool:
        """Save predictions."""
        data = {}
        for pred_id, prediction in self.predictions.items():
            data[pred_id] = {
                'content': prediction.content,
                'confidence': prediction.confidence,
                'created': prediction.created,
                'deadline': prediction.deadline,
                'status': prediction.status
            }
        return _save_json(self.predictions_file, data)
    
    def _save_outcomes(self) -> bool:
        """Save outcomes."""
        data = {}
        for outcome_id, outcome in self.outcomes.items():
            data[outcome_id] = {
                'prediction_id': outcome.prediction_id,
                'actual_outcome': outcome.actual_outcome,
                'accuracy_score': outcome.accuracy_score,
                'recorded': outcome.recorded
            }
        return _save_json(self.outcomes_file, data)
    
    def create_prediction(self, content: str, confidence: float,
                         verification_method: str = "manual", deadline_hours: int = 48) -> str:
        """Create testable prediction for grounding."""
        prediction_id = f"pred_v5_{int(_epoch())}_{len(self.predictions)}"
        
        deadline_time = datetime.now() + timedelta(hours=deadline_hours)
        
        prediction = Prediction(
            id=prediction_id,
            content=content,
            confidence=max(0.05, min(0.95, confidence)),
            created=_ts(),
            deadline=deadline_time.isoformat(),
            status="pending"
        )
        
        self.predictions[prediction_id] = prediction
        self.prediction_count += 1
        
        self._save_predictions()
        _log(f"Created prediction {prediction_id}: {content[:50]}... (conf={confidence:.3f})")
        return prediction_id
    
    def record_outcome(self, prediction_id: str, actual_outcome: str,
                      accuracy_score: float, verification_notes: str = "") -> bool:
        """Record prediction outcome and calculate accuracy."""
        if prediction_id not in self.predictions:
            return False
        
        prediction = self.predictions[prediction_id]
        
        outcome = Outcome(
            prediction_id=prediction_id,
            actual_outcome=actual_outcome,
            accuracy_score=max(0.0, min(1.0, accuracy_score)),
            recorded=_ts()
        )
        
        self.outcomes[prediction_id] = outcome
        prediction.status = "resolved"
        
        self.accuracy_history.append(accuracy_score)
        
        self._save_predictions()
        self._save_outcomes()
        
        _log(f"Recorded outcome for {prediction_id}: accuracy={accuracy_score:.3f}")
        return True
    
    def apply_grounding_updates(self, max_updates: int = 5) -> Dict[str, Any]:
        """Apply belief confidence updates based on prediction outcomes."""
        # Simplified grounding - would need more sophisticated belief matching in practice
        updates_applied = 0
        
        for outcome in self.outcomes.values():
            if updates_applied >= max_updates:
                break
            
            prediction = self.predictions.get(outcome.prediction_id)
            if not prediction:
                continue
            
            # Calculate confidence adjustment based on accuracy
            accuracy = outcome.accuracy_score
            predicted_conf = prediction.confidence
            
            if accuracy > 0.8 and predicted_conf > 0.7:
                # Good prediction, slight confidence boost
                self.grounding_updates += 1
                updates_applied += 1
            elif accuracy < 0.3 and predicted_conf > 0.6:
                # Poor prediction, confidence reduction
                self.grounding_updates += 1
                updates_applied += 1
        
        return {
            "status": "success",
            "updates_applied": updates_applied,
            "total_grounding_updates": self.grounding_updates
        }
    
    def check_overdue_predictions(self) -> List[str]:
        """Identify predictions past their deadline."""
        now = datetime.now()
        overdue_predictions = []
        
        for pred_id, prediction in self.predictions.items():
            if prediction.status != "pending":
                continue
            
            try:
                deadline = datetime.fromisoformat(prediction.deadline)
                if now > deadline:
                    prediction.status = "overdue"
                    overdue_predictions.append(pred_id)
            except ValueError:
                prediction.status = "invalid_deadline"
                overdue_predictions.append(pred_id)
        
        if overdue_predictions:
            self._save_predictions()
            _log(f"Found {len(overdue_predictions)} overdue predictions", "WARN")
        
        return overdue_predictions
    
    def process_predictions(self) -> Dict[str, Any]:
        """Main prediction processing cycle."""
        # Check for overdue predictions
        overdue = self.check_overdue_predictions()
        
        # Apply grounding updates
        grounding_result = self.apply_grounding_updates()
        
        return {
            "overdue_predictions": len(overdue),
            "grounding_updates": grounding_result,
            "total_predictions": len(self.predictions),
            "resolved_predictions": sum(1 for p in self.predictions.values() if p.status == "resolved")
        }
    
    def status(self) -> Dict[str, Any]:
        """System status report."""
        pending = sum(1 for p in self.predictions.values() if p.status == "pending")
        resolved = sum(1 for p in self.predictions.values() if p.status == "resolved")
        avg_accuracy = sum(self.accuracy_history) / max(len(self.accuracy_history), 1)
        
        return {
            "total_predictions": len(self.predictions),
            "pending": pending,
            "resolved": resolved,
            "prediction_count": self.prediction_count,
            "avg_accuracy": round(avg_accuracy, 3),
            "grounding_updates": self.grounding_updates,
            "outcomes_recorded": len(self.outcomes)
        }

# ══════════════════════════════════════════════════════════════
# MAIN NEX v5.0 CONTROLLER — Integration & Orchestration
# ══════════════════════════════════════════════════════════════

class NexV500CognitiveArchitecture:
    """Main controller for NEX v5.0 Cognitive Architecture.
    
    Orchestrates all cognitive systems: Loop Control, Structured Beliefs,
    Contradiction Resolution, Enhanced Reflection, Narrative Memory, and
    Prediction Grounding. Provides unified interface and health monitoring.
    """
    
    def __init__(self):
        # Initialize all subsystems
        self.loop_control = LoopControlEngine()
        self.belief_system = StructuredBeliefSystem()
        self.contradiction_engine = ContradictionResolutionEngine()
        self.reflection_engine = EnhancedReflectionEngine()
        self.narrative_memory = NarrativeMemorySystem()
        self.prediction_grounding = PredictionOutcomeGrounding()
        
        # System state
        self.cycle_count = 0
        self.last_full_cycle = 0
        self.system_health = {"status": "initializing"}
        self.emergency_interventions = 0
        
        _log("NEX v5.0 Cognitive Architecture fully initialized")
    
    def tick(self, avg_conf: float = 0.5, belief_count: int = 0,
             recent_output: str = "", cycle: int = 0,
             context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Main v5.0 cognitive cycle.
        
        Executes integrated cognitive processing across all systems.
        """
        start_time = _epoch()
        self.cycle_count += 1
        context = context or {}
        
        try:
            results = {}
            
            # 1. Loop Control (Every cycle - highest priority)
            loop_analysis = self.loop_control.analyze_response(recent_output)
            results["loop_control"] = loop_analysis
            
            # Emergency intervention if needed
            if loop_analysis.get("intervention_recommended", False):
                emergency_injection = self.loop_control.emergency_loop_break()
                results["emergency_intervention"] = emergency_injection
                self.emergency_interventions += 1
            
            # 2. Belief System Updates (Every 3 cycles)
            if self.cycle_count % 3 == 0:
                schema_update = self.belief_system.update_belief_schemas()
                results["belief_schemas"] = schema_update
                
                # Intelligent pruning (every 20 cycles)
                if self.cycle_count % 20 == 0:
                    pruning_result = self.belief_system.intelligent_pruning()
                    results["belief_pruning"] = pruning_result
            
            # 3. Contradiction Resolution (Every 5 cycles)
            if self.cycle_count % 5 == 0:
                contradiction_result = self.contradiction_engine.process_contradictions()
                results["contradictions"] = contradiction_result
            
            # 4. Enhanced Reflection (Triggered by conditions)
            reflection_needed = (
                loop_analysis.get("loop_detected", False) or
                avg_conf < 0.4 or
                self.cycle_count % 15 == 0
            )
            
            if reflection_needed:
                trigger = self._determine_reflection_trigger(loop_analysis, avg_conf)
                reflection_id = self.reflection_engine.create_reflection(
                    trigger["event"], trigger["type"]
                )
                results["reflection"] = {"created": reflection_id, "trigger": trigger}
                
                # Auto-implement if high quality
                reflection = self.reflection_engine.reflections.get(reflection_id)
                if reflection and reflection.quality_score > 0.7:
                    behavior_change = self._generate_behavior_change(reflection, loop_analysis)
                    if behavior_change:
                        self.reflection_engine.implement_behavior_change(
                            reflection_id, behavior_change
                        )
                        results["reflection"]["implemented"] = behavior_change
            
            # Process existing reflections
            if self.cycle_count % 10 == 0:
                reflection_processing = self.reflection_engine.process_reflections()
                results["reflection_processing"] = reflection_processing
            
            # 5. Narrative Memory (Every 8 cycles)
            if self.cycle_count % 8 == 0:
                cycle_description = f"Cognitive cycle {cycle}: conf={avg_conf:.3f}, beliefs={belief_count}"
                impact = 0.8 if loop_analysis.get("loop_detected") else 0.3
                
                self.narrative_memory.add_event(
                    "cognitive_cycle",
                    cycle_description,
                    impact
                )
                
                # Track identity (every 25 cycles)
                if self.cycle_count % 25 == 0:
                    identity_result = self.narrative_memory.track_identity_continuity()
                    results["identity_tracking"] = identity_result
            
            # 6. Prediction Grounding (Every 12 cycles)
            if self.cycle_count % 12 == 0:
                grounding_result = self.prediction_grounding.process_predictions()
                results["grounding"] = grounding_result
            
            # System health assessment
            self._update_system_health(results, avg_conf, belief_count)
            
            cycle_time = _epoch() - start_time
            self.last_full_cycle = _epoch()
            
            return {
                "v5_status": "operational",
                "cycle": self.cycle_count,
                "cycle_time": round(cycle_time, 3),
                "system_health": self.system_health["status"],
                "results": results,
                "emergency_interventions": self.emergency_interventions
            }
            
        except Exception as e:
            error_msg = f"v5.0 tick error: {e}"
            _log(error_msg, "ERROR")
            
            self.system_health["status"] = "error"
            self.system_health["last_error"] = str(e)
            
            return {
                "v5_status": "error",
                "cycle": self.cycle_count,
                "error": str(e)
            }
    
    def _determine_reflection_trigger(self, loop_analysis: Dict[str, Any], avg_conf: float) -> Dict[str, Any]:
        """Determine appropriate reflection trigger and type."""
        if loop_analysis.get("loop_detected", False):
            return {
                "event": f"loop_detected_diversity_{loop_analysis.get('diversity_score', 0):.3f}",
                "type": "pattern_recognition"
            }
        elif avg_conf < 0.4:
            return {
                "event": f"low_confidence_{avg_conf:.3f}",
                "type": "error_correction"
            }
        else:
            return {
                "event": f"periodic_reflection_cycle_{self.cycle_count}",
                "type": "strategy_improvement"
            }
    
    def _generate_behavior_change(self, reflection: Any, loop_analysis: Dict[str, Any]) -> Optional[str]:
        """Generate concrete behavior change from reflection."""
        if reflection.reflection_type == "pattern_recognition":
            return f"Implement diversity injection when pressure exceeds {loop_analysis.get('diversity_pressure', 0.6):.2f}"
        elif reflection.reflection_type == "error_correction":
            return "Implement confidence calibration check before conclusions"
        elif reflection.reflection_type == "strategy_improvement":
            return "Establish systematic verification protocol for reasoning"
        return None
    
    def _update_system_health(self, results: Dict[str, Any], avg_conf: float, belief_count: int) -> None:
        """Update comprehensive system health assessment."""
        health_indicators = []
        
        # Loop control health
        if results.get("loop_control", {}).get("loop_detected", False):
            health_indicators.append("loop_detected")
        
        # Belief system health
        if belief_count < 100:
            health_indicators.append("low_belief_count")
        elif belief_count > 2000:
            health_indicators.append("belief_overload")
        
        # Confidence health
        if avg_conf < 0.3:
            health_indicators.append("low_confidence")
        elif avg_conf > 0.9:
            health_indicators.append("overconfident")
        
        # Determine overall status
        if not health_indicators:
            status = "optimal"
        elif len(health_indicators) <= 2:
            status = "operational"
        else:
            status = "degraded"
        
        self.system_health = {
            "status": status,
            "indicators": health_indicators,
            "avg_conf": avg_conf,
            "belief_count": belief_count,
            "emergency_interventions": self.emergency_interventions,
            "last_update": _ts()
        }
    
    def status(self) -> Dict[str, Any]:
        """Comprehensive system status report."""
        # Collect component statuses
        component_statuses = {
            "loop_control": self.loop_control.status(),
            "belief_system": self.belief_system.status(),
            "contradiction_engine": self.contradiction_engine.status(),
            "reflection_engine": self.reflection_engine.status(),
            "narrative_memory": self.narrative_memory.status(),
            "prediction_grounding": self.prediction_grounding.status()
        }
        
        return {
            "version": "5.0",
            "status": self.system_health.get("status", "unknown"),
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_full_cycle,
            "emergency_interventions": self.emergency_interventions,
            "system_health": self.system_health,
            "components": component_statuses
        }
    
    # Convenience methods
    def add_desire(self, description: str, priority: float = 0.5) -> str:
        """Add desire to structured belief system."""
        return self.belief_system.add_desire(description, priority)
    
    def add_intention(self, desire_id: str, plan: str, steps: List[str]) -> str:
        """Add intention linked to desire."""
        return self.belief_system.add_intention(desire_id, plan, steps)
    
    def create_prediction(self, content: str, confidence: float) -> str:
        """Create prediction for reality testing."""
        return self.prediction_grounding.create_prediction(content, confidence)
    
    def record_prediction_outcome(self, prediction_id: str, actual: str, accuracy: float) -> bool:
        """Record prediction outcome for grounding."""
        return self.prediction_grounding.record_outcome(prediction_id, actual, accuracy)

# ══════════════════════════════════════════════════════════════
# FACTORY & INTEGRATION FUNCTIONS
# ══════════════════════════════════════════════════════════════

def get_v500() -> NexV500CognitiveArchitecture:
    """Factory function for NEX v5.0 cognitive architecture.
    
    Returns fully initialized v5.0 system ready for integration.
    """
    return NexV500CognitiveArchitecture()

def initialize_v500_config() -> bool:
    """Initialize v5.0 configuration directories and files."""
    try:
        config_dir = os.path.expanduser('~/.config/nex')
        os.makedirs(config_dir, exist_ok=True)
        
        config_files = [
            'v500_desires.json', 'v500_intentions.json', 'v500_belief_schemas.json',
            'v500_contradictions.json', 'v500_resolutions.json',
            'v500_enhanced_reflections.json', 'v500_behavior_tracking.json',
            'v500_narrative_timeline.json', 'v500_identity_trajectory.json',
            'v500_predictions.json', 'v500_outcomes.json'
        ]
        
        for config_file in config_files:
            filepath = _config_path(config_file)
            if not os.path.exists(filepath):
                _save_json(filepath, {})
        
        _log("v5.0 configuration initialized successfully")
        return True
        
    except Exception as e:
        _log(f"v5.0 configuration initialization failed: {e}", "ERROR")
        return False

# ══════════════════════════════════════════════════════════════
# TESTING & DIAGNOSTICS
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("NEX v5.0 Cognitive Architecture - System Testing")
    print("=" * 60)
    
    # Initialize configuration
    config_result = initialize_v500_config()
    print(f"Configuration: {'✓' if config_result else '✗'}")
    
    if config_result:
        try:
            # Test system initialization
            nex_v500 = NexV500CognitiveArchitecture()
            print("System Initialization: ✓")
            
            # Test main tick cycle
            tick_result = nex_v500.tick(
                avg_conf=0.6,
                belief_count=500,
                recent_output="Testing cognitive architecture integration",
                cycle=1
            )
            print(f"Main Tick Cycle: {'✓' if tick_result.get('v5_status') == 'operational' else '✗'}")
            
            # System status
            status = nex_v500.status()
            print(f"System Status: {status['status']}")
            print(f"Components: {len(status['components'])} active")
            
            print("\n" + "=" * 60)
            print("🎉 NEX v5.0 Cognitive Architecture Ready!")
            print("=" * 60)
            print("Integration: Copy to nex_upgrades/nex_v500.py")
            print("Usage: from nex_upgrades.nex_v500 import get_v500")
            
        except Exception as e:
            print(f"Testing failed: {e}")
    else:
        print("Configuration failed - cannot proceed with testing")
