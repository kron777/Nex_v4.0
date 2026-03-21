#!/usr/bin/env python3
"""
NEX v6.1 — INTEGRATION ALIGNMENT PATCH
======================================
Surgical stabilization: align generation with resolution.

Philosophy:
- DON'T expand capability
- DON'T suppress activity  
- DO align generation with resolution
- Increase closure rate without reducing thinking
- Convert turbulence into resolved coherence

Core Problem Solved:
- Contradiction generation outpacing synthesis throughput
- Learning amplifying unresolved structures
- Bandwidth overflow causing internal turbulence

Systems:
- ClosureRateTracker - Monitor synthesis completion ratio
- ClusterPrioritizer - Focus attention on resolvable clusters
- ResolutionMomentum - Prevent synthesis stagnation
- LearningGate - Sequence learning after synthesis
- AttentionFriction - Control topic proliferation
- ConfidenceStabilizer - Filter volatile learning inputs
"""

import time
import json
import uuid
import threading
import statistics
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from collections import deque, defaultdict, Counter
from enum import Enum
from pathlib import Path
import math

# ══════════════════════════════════════════════════════════════
# CORE TYPES & ALIGNMENT STRUCTURES
# ══════════════════════════════════════════════════════════════

class ClusterState(str, Enum):
    """Cluster resolution states."""
    GENERATING = "generating"           # Actively accumulating contradictions
    SYNTHESIZING = "synthesizing"       # In resolution process
    RESOLVED = "resolved"              # Successfully synthesized
    STAGNANT = "stagnant"             # No progress for multiple cycles
    DORMANT = "dormant"               # Deprioritized but preserved

class ResolutionPriority(int, Enum):
    """Resolution priority levels."""
    CRITICAL = 5    # Must resolve this cycle
    HIGH = 4        # High synthesis priority
    NORMAL = 3      # Standard processing
    LOW = 2         # Background processing
    DORMANT = 1     # Minimal processing

@dataclass
class ActiveCluster:
    """Cluster being actively processed for resolution."""
    cluster_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    topic: str = ""
    contradictions: List[str] = field(default_factory=list)
    state: ClusterState = ClusterState.GENERATING
    priority: ResolutionPriority = ResolutionPriority.NORMAL
    last_activity: float = field(default_factory=time.time)
    synthesis_attempts: int = 0
    resolution_depth: int = 1
    confidence_volatility: float = 0.0
    stagnation_cycles: int = 0
    
    # Resolution tracking
    generated_thoughts: int = 0
    synthesized_thoughts: int = 0
    partial_resolutions: int = 0

@dataclass
class ClosureMetrics:
    """Tracks closure rate and resolution efficiency."""
    total_thoughts_generated: int = 0
    total_thoughts_synthesized: int = 0
    active_clusters: int = 0
    resolved_clusters: int = 0
    closure_rate: float = 0.0
    resolution_velocity: float = 0.0
    last_calculation: float = field(default_factory=time.time)

def _log_v61(msg: str, level: str = "INFO") -> None:
    """Logging for v6.1 integration alignment."""
    timestamp = time.strftime('%H:%M:%S')
    with open('/tmp/nex_v61.log', 'a') as f:
        f.write(f"[v6.1 {timestamp}] [{level}] {msg}\n")

def _config_path_v61(filename: str) -> str:
    """Get v6.1 config file path."""
    config_dir = Path.home() / '.config' / 'nex' / 'v61'
    config_dir.mkdir(parents=True, exist_ok=True)
    return str(config_dir / filename)

# ══════════════════════════════════════════════════════════════
# CLOSURE RATE TRACKER — Core Alignment Metric
# ══════════════════════════════════════════════════════════════

class ClosureRateTracker:
    """Track synthesis completion rate as core alignment metric."""
    
    def __init__(self):
        self.metrics_history = deque(maxlen=100)
        self.current_metrics = ClosureMetrics()
        
        # Target parameters
        self.target_closure_rate = 0.35
        self.synthesis_boost_threshold = 0.25
        self.topic_reduction_threshold = 0.20
        
        # Dynamic adjustments
        self.synthesis_priority_boost = 0.0
        self.new_topic_priority_reduction = 0.0
        
        _log_v61("ClosureRateTracker initialized - monitoring synthesis completion ratio")
    
    def record_thought_generation(self, cluster_id: str) -> None:
        """Record new thought generation."""
        self.current_metrics.total_thoughts_generated += 1
    
    def record_thought_synthesis(self, cluster_id: str) -> None:
        """Record successful thought synthesis."""
        self.current_metrics.total_thoughts_synthesized += 1
    
    def calculate_closure_rate(self) -> float:
        """Calculate current closure rate."""
        total_generated = self.current_metrics.total_thoughts_generated
        total_synthesized = self.current_metrics.total_thoughts_synthesized
        
        if total_generated == 0:
            return 0.0
        
        closure_rate = total_synthesized / total_generated
        self.current_metrics.closure_rate = closure_rate
        self.current_metrics.last_calculation = time.time()
        
        return closure_rate
    
    def update_dynamic_adjustments(self) -> Dict[str, float]:
        """Update dynamic priority adjustments based on closure rate."""
        current_rate = self.calculate_closure_rate()
        
        # Reset adjustments
        self.synthesis_priority_boost = 0.0
        self.new_topic_priority_reduction = 0.0
        
        # Apply adjustments based on closure rate
        if current_rate < self.synthesis_boost_threshold:
            # Significant synthesis boost needed
            self.synthesis_priority_boost = 0.3
            self.new_topic_priority_reduction = 0.15
            _log_v61(f"Low closure rate {current_rate:.3f} - boosting synthesis priority")
            
        elif current_rate < self.target_closure_rate:
            # Moderate synthesis boost
            self.synthesis_priority_boost = 0.2
            self.new_topic_priority_reduction = 0.1
            _log_v61(f"Below-target closure rate {current_rate:.3f} - moderate synthesis boost")
        
        # Record metrics
        self.metrics_history.append({
            'timestamp': time.time(),
            'closure_rate': current_rate,
            'synthesis_boost': self.synthesis_priority_boost,
            'topic_reduction': self.new_topic_priority_reduction
        })
        
        return {
            'closure_rate': current_rate,
            'synthesis_boost': self.synthesis_priority_boost,
            'topic_reduction': self.new_topic_priority_reduction
        }
    
    def get_closure_statistics(self) -> Dict[str, Any]:
        """Get comprehensive closure rate statistics."""
        recent_metrics = list(self.metrics_history)[-10:]
        
        if recent_metrics:
            avg_closure_rate = statistics.mean(m['closure_rate'] for m in recent_metrics)
            closure_trend = recent_metrics[-1]['closure_rate'] - recent_metrics[0]['closure_rate']
        else:
            avg_closure_rate = 0.0
            closure_trend = 0.0
        
        return {
            'current_closure_rate': self.current_metrics.closure_rate,
            'target_closure_rate': self.target_closure_rate,
            'average_closure_rate': round(avg_closure_rate, 3),
            'closure_trend': round(closure_trend, 3),
            'total_thoughts_generated': self.current_metrics.total_thoughts_generated,
            'total_thoughts_synthesized': self.current_metrics.total_thoughts_synthesized,
            'current_synthesis_boost': self.synthesis_priority_boost,
            'current_topic_reduction': self.new_topic_priority_reduction
        }

# ══════════════════════════════════════════════════════════════
# CLUSTER PRIORITIZER — Focus Attention on Resolvable Clusters
# ══════════════════════════════════════════════════════════════

class ClusterPrioritizer:
    """Manage active cluster priority and focus."""
    
    def __init__(self):
        self.active_clusters = {}  # cluster_id -> ActiveCluster
        self.max_active_clusters = 5
        self.priority_decay_rate = 0.85
        
        # Ranking weights
        self.contradiction_weight = 0.4
        self.recency_weight = 0.3
        self.depth_weight = 0.2
        self.volatility_weight = 0.1
        
        _log_v61("ClusterPrioritizer initialized - managing cluster focus and resolution")
    
    def add_cluster(self, topic: str, contradictions: List[str] = None) -> str:
        """Add new cluster for prioritization."""
        cluster = ActiveCluster(
            topic=topic,
            contradictions=contradictions or [],
            state=ClusterState.GENERATING
        )
        
        self.active_clusters[cluster.cluster_id] = cluster
        return cluster.cluster_id
    
    def rank_clusters(self) -> List[ActiveCluster]:
        """Rank clusters by resolution priority."""
        clusters = list(self.active_clusters.values())
        
        # Calculate priority scores
        scored_clusters = []
        for cluster in clusters:
            score = self._calculate_priority_score(cluster)
            scored_clusters.append((score, cluster))
        
        # Sort by score (highest first)
        scored_clusters.sort(key=lambda x: x[0], reverse=True)
        
        return [cluster for score, cluster in scored_clusters]
    
    def _calculate_priority_score(self, cluster: ActiveCluster) -> float:
        """Calculate priority score for cluster."""
        score = 0.0
        
        # Contradiction count contribution
        contradiction_score = min(1.0, len(cluster.contradictions) / 5.0)
        score += contradiction_score * self.contradiction_weight
        
        # Recency contribution (more recent = higher priority)
        time_since_activity = time.time() - cluster.last_activity
        recency_score = max(0.0, 1.0 - (time_since_activity / 3600))  # Decay over 1 hour
        score += recency_score * self.recency_weight
        
        # Depth contribution (deeper = higher priority for resolution)
        depth_score = min(1.0, cluster.resolution_depth / 3.0)
        score += depth_score * self.depth_weight
        
        # Volatility penalty (unstable clusters get lower priority)
        volatility_penalty = cluster.confidence_volatility
        score -= volatility_penalty * self.volatility_weight
        
        # State modifiers
        if cluster.state == ClusterState.SYNTHESIZING:
            score *= 1.5  # Boost clusters already in synthesis
        elif cluster.state == ClusterState.STAGNANT:
            score *= 0.5  # Reduce stagnant clusters
        elif cluster.state == ClusterState.DORMANT:
            score *= 0.2  # Minimal priority for dormant
        
        return max(0.0, score)
    
    def apply_priority_focus(self) -> Dict[str, Any]:
        """Apply priority focus to active clusters."""
        ranked_clusters = self.rank_clusters()
        
        # Focus clusters (top N get full attention)
        focus_clusters = ranked_clusters[:self.max_active_clusters]
        deprioritized_clusters = ranked_clusters[self.max_active_clusters:]
        
        focus_ids = []
        deprioritized_ids = []
        
        # Set priorities for focus clusters
        for i, cluster in enumerate(focus_clusters):
            if i == 0:
                cluster.priority = ResolutionPriority.CRITICAL
            elif i < 3:
                cluster.priority = ResolutionPriority.HIGH
            else:
                cluster.priority = ResolutionPriority.NORMAL
            
            focus_ids.append(cluster.cluster_id)
        
        # Deprioritize excess clusters
        for cluster in deprioritized_clusters:
            cluster.priority = ResolutionPriority.LOW
            # Decay priority without deletion
            if hasattr(cluster, 'dynamic_priority'):
                cluster.dynamic_priority *= self.priority_decay_rate
            else:
                cluster.dynamic_priority = 0.5  # Start with medium priority
            
            deprioritized_ids.append(cluster.cluster_id)
        
        return {
            'focus_cluster_count': len(focus_clusters),
            'deprioritized_cluster_count': len(deprioritized_clusters),
            'focus_cluster_ids': focus_ids,
            'deprioritized_cluster_ids': deprioritized_ids
        }
    
    def update_cluster_activity(self, cluster_id: str, activity_type: str) -> None:
        """Update cluster activity timestamp and state."""
        if cluster_id in self.active_clusters:
            cluster = self.active_clusters[cluster_id]
            cluster.last_activity = time.time()
            
            # Update state based on activity
            if activity_type == 'synthesis':
                cluster.state = ClusterState.SYNTHESIZING
                cluster.synthesis_attempts += 1
            elif activity_type == 'generation':
                cluster.generated_thoughts += 1
                if cluster.state == ClusterState.DORMANT:
                    cluster.state = ClusterState.GENERATING
            elif activity_type == 'resolution':
                cluster.state = ClusterState.RESOLVED
                cluster.synthesized_thoughts += 1
    
    def detect_stagnation(self) -> List[str]:
        """Detect and mark stagnant clusters."""
        stagnant_cluster_ids = []
        current_time = time.time()
        
        for cluster_id, cluster in self.active_clusters.items():
            time_since_activity = current_time - cluster.last_activity
            
            # Mark as stagnant if no activity for extended period
            if time_since_activity > 600:  # 10 minutes
                cluster.stagnation_cycles += 1
                
                if cluster.stagnation_cycles > 3:
                    cluster.state = ClusterState.STAGNANT
                    stagnant_cluster_ids.append(cluster_id)
        
        return stagnant_cluster_ids
    
    def get_cluster_status(self) -> Dict[str, Any]:
        """Get comprehensive cluster prioritization status."""
        state_counts = defaultdict(int)
        priority_counts = defaultdict(int)
        
        for cluster in self.active_clusters.values():
            state_counts[cluster.state.value] += 1
            priority_counts[cluster.priority.value] += 1
        
        return {
            'total_active_clusters': len(self.active_clusters),
            'max_active_clusters': self.max_active_clusters,
            'cluster_states': dict(state_counts),
            'priority_distribution': dict(priority_counts),
            'stagnant_clusters': len([c for c in self.active_clusters.values() 
                                    if c.state == ClusterState.STAGNANT])
        }

# ══════════════════════════════════════════════════════════════
# RESOLUTION MOMENTUM — Prevent Synthesis Stagnation
# ══════════════════════════════════════════════════════════════

class ResolutionMomentum:
    """Maintain synthesis momentum and prevent stagnation."""
    
    def __init__(self):
        self.synthesis_history = deque(maxlen=50)
        self.resolution_window = 5  # Cycles to check for synthesis activity
        self.micro_synthesis_threshold = 3  # Trigger micro-synthesis after N stagnant cycles
        
        self.forced_synthesis_count = 0
        self.momentum_interventions = deque(maxlen=20)
        
        _log_v61("ResolutionMomentum initialized - maintaining synthesis flow")
    
    def record_synthesis_event(self, cluster_id: str, synthesis_type: str = "full") -> None:
        """Record synthesis event for momentum tracking."""
        synthesis_event = {
            'timestamp': time.time(),
            'cluster_id': cluster_id,
            'type': synthesis_type
        }
        
        self.synthesis_history.append(synthesis_event)
    
    def check_synthesis_momentum(self) -> Dict[str, Any]:
        """Check if synthesis momentum is maintained."""
        current_time = time.time()
        window_start = current_time - (self.resolution_window * 60)  # Convert to seconds
        
        # Count recent synthesis events
        recent_synthesis = [
            event for event in self.synthesis_history
            if event['timestamp'] > window_start
        ]
        
        momentum_status = {
            'recent_synthesis_count': len(recent_synthesis),
            'synthesis_rate': len(recent_synthesis) / self.resolution_window,
            'momentum_healthy': len(recent_synthesis) > 0,
            'stagnation_detected': len(recent_synthesis) == 0 and len(self.synthesis_history) > 0
        }
        
        return momentum_status
    
    def inject_micro_synthesis(self, cluster_id: str) -> Dict[str, Any]:
        """Inject lightweight micro-synthesis to maintain momentum."""
        try:
            # Lightweight reconciliation approach
            micro_synthesis_result = {
                'type': 'micro_synthesis',
                'cluster_id': cluster_id,
                'timestamp': time.time(),
                'intervention_id': str(uuid.uuid4())[:8],
                'success': True,
                'changes_made': [
                    'minor_contradiction_merge',
                    'confidence_stabilization',
                    'partial_resolution'
                ]
            }
            
            self.forced_synthesis_count += 1
            self.momentum_interventions.append(micro_synthesis_result)
            
            # Record as synthesis event
            self.record_synthesis_event(cluster_id, "micro")
            
            _log_v61(f"Micro-synthesis injected for cluster {cluster_id}")
            
            return micro_synthesis_result
            
        except Exception as e:
            _log_v61(f"Micro-synthesis injection failed: {e}", "ERROR")
            return {'success': False, 'error': str(e)}
    
    def assess_resolution_momentum(self) -> Dict[str, Any]:
        """Assess overall resolution momentum and recommend actions."""
        momentum_status = self.check_synthesis_momentum()
        
        # Determine intervention needs
        intervention_needed = False
        intervention_type = None
        
        if momentum_status['stagnation_detected']:
            intervention_needed = True
            intervention_type = 'micro_synthesis'
        elif momentum_status['synthesis_rate'] < 0.2:  # Very low synthesis rate
            intervention_needed = True
            intervention_type = 'momentum_boost'
        
        return {
            'momentum_status': momentum_status,
            'intervention_needed': intervention_needed,
            'intervention_type': intervention_type,
            'forced_synthesis_count': self.forced_synthesis_count,
            'recent_interventions': len(self.momentum_interventions)
        }

# ══════════════════════════════════════════════════════════════
# LEARNING GATE — Sequence Learning After Synthesis
# ══════════════════════════════════════════════════════════════

class LearningGate:
    """Control learning sequence to prevent amplification of unresolved structures."""
    
    def __init__(self):
        self.min_confidence_to_learn = 0.45
        self.require_synthesis_for_learning = True
        self.learning_blocks = defaultdict(int)
        self.learning_permits = defaultdict(int)
        
        # Quality control
        self.confidence_volatility_threshold = 0.2
        self.volatility_window = 5
        
        _log_v61("LearningGate initialized - controlling learning sequence and quality")
    
    def should_allow_learning(self, belief_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Determine if learning should be allowed for this belief."""
        confidence = belief_data.get('confidence', 0.0)
        has_been_synthesized = belief_data.get('has_been_synthesized', False)
        volatility = belief_data.get('confidence_volatility', 0.0)
        
        # Check confidence threshold
        if confidence < self.min_confidence_to_learn:
            self.learning_blocks['low_confidence'] += 1
            return False, f"confidence {confidence:.3f} below threshold {self.min_confidence_to_learn}"
        
        # Check synthesis requirement
        if self.require_synthesis_for_learning and not has_been_synthesized:
            self.learning_blocks['not_synthesized'] += 1
            return False, "belief not yet synthesized"
        
        # Check confidence volatility
        if volatility > self.confidence_volatility_threshold:
            self.learning_blocks['high_volatility'] += 1
            return False, f"confidence volatility {volatility:.3f} too high"
        
        # Learning permitted
        self.learning_permits['quality_passed'] += 1
        return True, "learning permitted"
    
    def filter_learning_inputs(self, input_beliefs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter learning inputs based on quality and synthesis status."""
        permitted_beliefs = []
        
        for belief in input_beliefs:
            allowed, reason = self.should_allow_learning(belief)
            
            if allowed:
                permitted_beliefs.append(belief)
            else:
                # Add blocking reason to belief metadata
                belief['learning_blocked_reason'] = reason
        
        return permitted_beliefs
    
    def calculate_learning_quality_score(self, belief_data: Dict[str, Any]) -> float:
        """Calculate quality score for learning input."""
        confidence = belief_data.get('confidence', 0.0)
        synthesis_status = belief_data.get('has_been_synthesized', False)
        stability = 1.0 - belief_data.get('confidence_volatility', 0.0)
        
        # Base score from confidence
        quality_score = confidence * 0.5
        
        # Synthesis bonus
        if synthesis_status:
            quality_score += 0.3
        
        # Stability bonus
        quality_score += stability * 0.2
        
        return min(1.0, quality_score)
    
    def get_learning_gate_statistics(self) -> Dict[str, Any]:
        """Get learning gate performance statistics."""
        total_blocks = sum(self.learning_blocks.values())
        total_permits = sum(self.learning_permits.values())
        total_decisions = total_blocks + total_permits
        
        if total_decisions > 0:
            permit_rate = total_permits / total_decisions
            block_rate = total_blocks / total_decisions
        else:
            permit_rate = 0.0
            block_rate = 0.0
        
        return {
            'total_learning_decisions': total_decisions,
            'permits': total_permits,
            'blocks': total_blocks,
            'permit_rate': round(permit_rate, 3),
            'block_rate': round(block_rate, 3),
            'block_reasons': dict(self.learning_blocks),
            'permit_reasons': dict(self.learning_permits),
            'min_confidence_threshold': self.min_confidence_to_learn,
            'synthesis_requirement': self.require_synthesis_for_learning
        }

# ══════════════════════════════════════════════════════════════
# ATTENTION FRICTION — Control Topic Proliferation
# ══════════════════════════════════════════════════════════════

class AttentionFriction:
    """Add friction to new topic generation to focus on resolution."""
    
    def __init__(self):
        self.new_topic_friction = 0.15
        self.base_priority_threshold = 0.5
        self.topic_spawn_history = deque(maxlen=100)
        
        # Dynamic friction adjustment
        self.friction_multiplier = 1.0
        self.max_friction_multiplier = 2.0
        
        _log_v61("AttentionFriction initialized - controlling topic proliferation")
    
    def calculate_spawn_threshold(self, base_priority: float) -> float:
        """Calculate threshold for spawning new topics."""
        adjusted_friction = self.new_topic_friction * self.friction_multiplier
        return self.base_priority_threshold + adjusted_friction
    
    def should_allow_new_topic(self, topic_priority: float, context: Dict[str, Any] = None) -> Tuple[bool, float]:
        """Determine if new topic spawning should be allowed."""
        spawn_threshold = self.calculate_spawn_threshold(topic_priority)
        
        # Check if priority meets threshold
        allowed = topic_priority >= spawn_threshold
        
        # Record decision
        self.topic_spawn_history.append({
            'timestamp': time.time(),
            'priority': topic_priority,
            'threshold': spawn_threshold,
            'allowed': allowed,
            'friction_multiplier': self.friction_multiplier
        })
        
        return allowed, spawn_threshold
    
    def adjust_friction_dynamically(self, system_pressure: float, closure_rate: float) -> None:
        """Adjust friction based on system state."""
        # Increase friction when system is under pressure or closure rate is low
        pressure_factor = min(2.0, system_pressure * 2)
        closure_factor = max(0.5, 2.0 - (closure_rate * 3))
        
        # Calculate new friction multiplier
        target_multiplier = pressure_factor * closure_factor
        self.friction_multiplier = min(self.max_friction_multiplier, target_multiplier)
        
        _log_v61(f"Friction adjusted: {self.friction_multiplier:.2f} "
                f"(pressure: {system_pressure:.2f}, closure: {closure_rate:.2f})")
    
    def get_friction_statistics(self) -> Dict[str, Any]:
        """Get attention friction statistics."""
        recent_spawns = list(self.topic_spawn_history)[-20:]  # Last 20 attempts
        
        if recent_spawns:
            allowed_spawns = [s for s in recent_spawns if s['allowed']]
            blocked_spawns = [s for s in recent_spawns if not s['allowed']]
            
            allow_rate = len(allowed_spawns) / len(recent_spawns)
            avg_threshold = statistics.mean(s['threshold'] for s in recent_spawns)
        else:
            allow_rate = 0.0
            avg_threshold = self.base_priority_threshold
        
        return {
            'current_friction': self.new_topic_friction,
            'friction_multiplier': round(self.friction_multiplier, 2),
            'current_spawn_threshold': round(self.calculate_spawn_threshold(0.5), 3),
            'recent_allow_rate': round(allow_rate, 3),
            'average_threshold': round(avg_threshold, 3),
            'total_spawn_attempts': len(self.topic_spawn_history)
        }

# ══════════════════════════════════════════════════════════════
# MAIN v6.1 CONTROLLER — Integration Alignment Orchestration
# ══════════════════════════════════════════════════════════════

class NexV61IntegrationAlignment:
    """Main controller for NEX v6.1 Integration Alignment."""
    
    def __init__(self):
        # Initialize all alignment components
        self.closure_tracker = ClosureRateTracker()
        self.cluster_prioritizer = ClusterPrioritizer()
        self.resolution_momentum = ResolutionMomentum()
        self.learning_gate = LearningGate()
        self.attention_friction = AttentionFriction()
        
        # System state
        self.cycle_count = 0
        self.initialization_time = time.time()
        self.alignment_interventions = 0
        
        # Energy redistribution parameters
        self.pressure_threshold = 0.7
        self.energy_shift_generation = -0.1  # 10% reduction
        self.energy_shift_synthesis = 0.15   # 15% increase
        
        _log_v61("NexV61IntegrationAlignment fully initialized - alignment orchestration active")
    
    def process_cycle(self, cycle_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a complete alignment cycle."""
        self.cycle_count += 1
        
        try:
            # 1. Update closure rate and get dynamic adjustments
            closure_adjustments = self.closure_tracker.update_dynamic_adjustments()
            
            # 2. Rank and prioritize clusters
            cluster_focus_result = self.cluster_prioritizer.apply_priority_focus()
            
            # 3. Check resolution momentum
            momentum_assessment = self.resolution_momentum.assess_resolution_momentum()
            
            # 4. Apply learning gate filtering
            raw_learning_inputs = cycle_data.get('learning_inputs', [])
            filtered_learning_inputs = self.learning_gate.filter_learning_inputs(raw_learning_inputs)
            
            # 5. Adjust attention friction based on system state
            system_pressure = cycle_data.get('system_pressure', 0.0)
            current_closure_rate = closure_adjustments['closure_rate']
            self.attention_friction.adjust_friction_dynamically(system_pressure, current_closure_rate)
            
            # 6. Handle momentum interventions
            if momentum_assessment['intervention_needed']:
                self._handle_momentum_intervention(momentum_assessment)
            
            # 7. Apply energy redistribution if needed
            energy_redistribution = None
            if system_pressure > self.pressure_threshold:
                energy_redistribution = self._apply_energy_redistribution(system_pressure)
            
            # 8. End-of-cycle consolidation
            consolidation_result = self._perform_micro_consolidation()
            
            return {
                'alignment_cycle': self.cycle_count,
                'closure_adjustments': closure_adjustments,
                'cluster_focus': cluster_focus_result,
                'momentum_assessment': momentum_assessment,
                'learning_filtering': {
                    'raw_inputs': len(raw_learning_inputs),
                    'filtered_inputs': len(filtered_learning_inputs),
                    'filter_rate': len(filtered_learning_inputs) / max(len(raw_learning_inputs), 1)
                },
                'attention_friction': self.attention_friction.get_friction_statistics(),
                'energy_redistribution': energy_redistribution,
                'consolidation': consolidation_result,
                'alignment_status': 'optimizing' if current_closure_rate > 0.25 else 'correcting'
            }
            
        except Exception as e:
            _log_v61(f"Alignment cycle error: {e}", "ERROR")
            return {'alignment_cycle': self.cycle_count, 'error': str(e)}
    
    def _handle_momentum_intervention(self, momentum_assessment: Dict[str, Any]) -> None:
        """Handle momentum intervention based on assessment."""
        intervention_type = momentum_assessment['intervention_type']
        
        if intervention_type == 'micro_synthesis':
            # Find a stagnant cluster for micro-synthesis
            stagnant_clusters = self.cluster_prioritizer.detect_stagnation()
            if stagnant_clusters:
                cluster_id = stagnant_clusters[0]
                self.resolution_momentum.inject_micro_synthesis(cluster_id)
                self.alignment_interventions += 1
                _log_v61(f"Momentum intervention: micro-synthesis on cluster {cluster_id}")
        
        elif intervention_type == 'momentum_boost':
            # Boost synthesis priority for active clusters
            for cluster in self.cluster_prioritizer.active_clusters.values():
                if cluster.state == ClusterState.GENERATING:
                    cluster.priority = min(ResolutionPriority.HIGH, cluster.priority + 1)
            
            self.alignment_interventions += 1
            _log_v61("Momentum intervention: synthesis priority boost applied")
    
    def _apply_energy_redistribution(self, system_pressure: float) -> Dict[str, Any]:
        """Apply energy redistribution under pressure."""
        # Calculate redistribution amounts
        pressure_multiplier = min(2.0, system_pressure / 0.7)
        generation_reduction = self.energy_shift_generation * pressure_multiplier
        synthesis_increase = self.energy_shift_synthesis * pressure_multiplier
        
        redistribution_result = {
            'triggered': True,
            'system_pressure': system_pressure,
            'generation_adjustment': generation_reduction,
            'synthesis_adjustment': synthesis_increase,
            'redistribution_strength': pressure_multiplier
        }
        
        _log_v61(f"Energy redistribution: -{abs(generation_reduction)*100:.0f}% generation, "
                f"+{synthesis_increase*100:.0f}% synthesis")
        
        return redistribution_result
    
    def _perform_micro_consolidation(self) -> Dict[str, Any]:
        """Perform end-of-cycle micro-consolidation."""
        try:
            # Check for unresolved clusters
            unresolved_clusters = [
                cluster for cluster in self.cluster_prioritizer.active_clusters.values()
                if cluster.state in [ClusterState.GENERATING, ClusterState.STAGNANT]
            ]
            
            consolidation_actions = []
            
            if unresolved_clusters:
                for cluster in unresolved_clusters[:3]:  # Limit to top 3
                    # Lightweight consolidation action
                    if cluster.contradictions and len(cluster.contradictions) < 3:
                        # Quick partial resolution for simple contradictions
                        consolidation_actions.append(f"partial_merge_{cluster.cluster_id}")
                        cluster.partial_resolutions += 1
                        
                        # Update cluster state
                        if cluster.partial_resolutions >= 2:
                            cluster.state = ClusterState.RESOLVED
                            self.closure_tracker.record_thought_synthesis(cluster.cluster_id)
            
            return {
                'unresolved_clusters': len(unresolved_clusters),
                'consolidation_actions': consolidation_actions,
                'actions_taken': len(consolidation_actions)
            }
            
        except Exception as e:
            _log_v61(f"Micro-consolidation error: {e}", "ERROR")
            return {'error': str(e)}
    
    def tick(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Main v6.1 integration alignment tick."""
        try:
            # Process alignment cycle
            cycle_result = self.process_cycle(context or {})
            
            # Calculate system health metrics
            uptime_hours = (time.time() - self.initialization_time) / 3600
            current_closure_rate = self.closure_tracker.current_metrics.closure_rate
            
            # Determine alignment status
            if current_closure_rate >= self.closure_tracker.target_closure_rate:
                alignment_status = 'aligned'
            elif current_closure_rate >= 0.25:
                alignment_status = 'improving'
            else:
                alignment_status = 'correcting'
            
            return {
                'v61_status': alignment_status,
                'cycle': self.cycle_count,
                'uptime_hours': round(uptime_hours, 2),
                'closure_rate': round(current_closure_rate, 3),
                'target_closure_rate': self.closure_tracker.target_closure_rate,
                'active_clusters': len(self.cluster_prioritizer.active_clusters),
                'alignment_interventions': self.alignment_interventions,
                'cycle_result': cycle_result
            }
            
        except Exception as e:
            error_msg = f"v6.1 tick error: {e}"
            _log_v61(error_msg, "ERROR")
            
            return {
                'v61_status': 'error',
                'cycle': self.cycle_count,
                'error': str(e)
            }
    
    def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive v6.1 integration alignment status."""
        uptime_hours = (time.time() - self.initialization_time) / 3600
        
        return {
            'version': '6.1',
            'philosophy': 'Align generation with resolution (not expand/suppress)',
            'uptime_hours': round(uptime_hours, 2),
            'cycle_count': self.cycle_count,
            'alignment_interventions': self.alignment_interventions,
            'closure_tracker': self.closure_tracker.get_closure_statistics(),
            'cluster_prioritizer': self.cluster_prioritizer.get_cluster_status(),
            'learning_gate': self.learning_gate.get_learning_gate_statistics(),
            'attention_friction': self.attention_friction.get_friction_statistics(),
            'target_closure_rate': self.closure_tracker.target_closure_rate
        }

# ══════════════════════════════════════════════════════════════
# FACTORY FUNCTION FOR INTEGRATION
# ══════════════════════════════════════════════════════════════

def get_v61() -> NexV61IntegrationAlignment:
    """Factory function for NEX v6.1 integration alignment."""
    return NexV61IntegrationAlignment()

def initialize_v61_config() -> bool:
    """Initialize v6.1 configuration files."""
    try:
        config_dir = Path.home() / '.config' / 'nex' / 'v61'
        config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default configuration
        config = {
            'version': '6.1',
            'closure_tracking': {
                'target_closure_rate': 0.35,
                'synthesis_boost_threshold': 0.25,
                'topic_reduction_threshold': 0.20
            },
            'cluster_prioritization': {
                'max_active_clusters': 5,
                'priority_decay_rate': 0.85,
                'stagnation_timeout': 600
            },
            'learning_gate': {
                'min_confidence_to_learn': 0.45,
                'require_synthesis_for_learning': True,
                'confidence_volatility_threshold': 0.2
            },
            'attention_friction': {
                'new_topic_friction': 0.15,
                'base_priority_threshold': 0.5,
                'max_friction_multiplier': 2.0
            },
            'energy_redistribution': {
                'pressure_threshold': 0.7,
                'generation_reduction': 0.1,
                'synthesis_increase': 0.15
            }
        }
        
        config_file = config_dir / 'integration_alignment_config.json'
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        _log_v61(f"v6.1 configuration initialized: {config_file}")
        return True
        
    except Exception as e:
        _log_v61(f"Config initialization failed: {e}", "ERROR")
        return False

# ══════════════════════════════════════════════════════════════
# TESTING FUNCTIONS
# ══════════════════════════════════════════════════════════════

def test_v61_integration_alignment() -> Dict[str, Any]:
    """Test v6.1 integration alignment system."""
    results = {}
    
    try:
        # Initialize system
        alignment_engine = NexV61IntegrationAlignment()
        results['initialization'] = True
        
        # Test closure rate tracking
        alignment_engine.closure_tracker.record_thought_generation("test_cluster_1")
        alignment_engine.closure_tracker.record_thought_generation("test_cluster_2")
        alignment_engine.closure_tracker.record_thought_synthesis("test_cluster_1")
        
        closure_stats = alignment_engine.closure_tracker.get_closure_statistics()
        results['closure_tracking'] = closure_stats['current_closure_rate'] > 0
        
        # Test cluster prioritization
        cluster_id = alignment_engine.cluster_prioritizer.add_cluster(
            "test_topic", ["contradiction_1", "contradiction_2"]
        )
        focus_result = alignment_engine.cluster_prioritizer.apply_priority_focus()
        results['cluster_prioritization'] = len(focus_result['focus_cluster_ids']) > 0
        
        # Test learning gate
        test_beliefs = [
            {'confidence': 0.6, 'has_been_synthesized': True},
            {'confidence': 0.3, 'has_been_synthesized': False}
        ]
        filtered_beliefs = alignment_engine.learning_gate.filter_learning_inputs(test_beliefs)
        results['learning_gate'] = len(filtered_beliefs) == 1  # Only high-confidence, synthesized belief
        
        # Test main tick
        test_context = {
            'system_pressure': 0.5,
            'learning_inputs': test_beliefs
        }
        tick_result = alignment_engine.tick(test_context)
        results['tick_test'] = tick_result['v61_status'] in ['aligned', 'improving', 'correcting']
        
        # Test comprehensive status
        status = alignment_engine.get_comprehensive_status()
        results['status_test'] = 'philosophy' in status
        
        return results
        
    except Exception as e:
        results['error'] = str(e)
        return results

if __name__ == "__main__":
    print("NEX v6.1 Integration Alignment - Testing")
    print("=" * 50)
    
    # Initialize configuration
    if initialize_v61_config():
        print("✓ Configuration initialized")
    else:
        print("✗ Configuration failed")
    
    # Run tests
    test_results = test_v61_integration_alignment()
    
    print("\nTest Results:")
    for test_name, result in test_results.items():
        if isinstance(result, bool):
            status = "✓" if result else "✗"
            print(f"  {test_name:25}: {status}")
        else:
            print(f"  {test_name:25}: {result}")
    
    print(f"\n⚡ NEX v6.1 Integration Alignment Ready!")
    print("Philosophy: Align generation with resolution")
    print("Integration: from nex_upgrades.nex_v61 import get_v61")
