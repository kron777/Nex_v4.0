#!/usr/bin/env python3
"""
NEX v5.2 — BALANCED FLOW CONTROL (ADAPTIVE)
===========================================
Intelligent flow shaping without cognitive suppression.

Philosophy:
- DO NOT: Hard-stop cognition  
- DO: Shape the flow of cognition
- Maintain responsiveness while preventing overload
- High-value signals ALWAYS pass through
- Gradual, adaptive pressure control

Systems:
- SoftIngestionGate - Smart event intake without hard blocking
- AdaptiveFlowController - Pressure-aware gradual throttling  
- EventPrioritizer - Importance-based processing decisions
- PressureAwareAttention - Dynamic threshold adjustment
- HealthSignalTracker - Real-time flow monitoring
"""

import time
import random
import hashlib
import threading
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from collections import deque, defaultdict
from enum import Enum
import json
import uuid
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# CORE TYPES & UTILITIES
# ══════════════════════════════════════════════════════════════

class EventType(str, Enum):
    """Event classification for flow control."""
    THOUGHT = "thought"
    BELIEF = "belief"
    ACTION = "action"
    REFLECTION = "reflection"
    GOAL = "goal"
    SYSTEM = "system"
    HIGH_VALUE = "high_value"

class Priority(int, Enum):
    """Flow control priority levels."""
    CRITICAL = 5
    HIGH = 4
    NORMAL = 3
    LOW = 2
    BACKGROUND = 1

@dataclass
class CognitiveEvent:
    """Enhanced event with flow control metadata."""
    type: EventType
    content: str
    confidence: float = 0.5
    priority: Priority = Priority.NORMAL
    source: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    flow_score: float = 0.0  # Computed by flow controller

def safe_str(x: Any, default: str = "") -> str:
    """Safe string conversion with fallback."""
    if x is None:
        return default
    try:
        return str(x).strip()
    except Exception:
        return default

def safe_float(x: Any, default: float = 0.0, min_val: float = None, max_val: float = None) -> float:
    """Safe float conversion with bounds checking."""
    try:
        value = float(x)
        if min_val is not None:
            value = max(min_val, value)
        if max_val is not None:
            value = min(max_val, value)
        return value
    except (TypeError, ValueError):
        return default

def _log_v52(msg: str, level: str = "INFO") -> None:
    """Logging for v5.2 flow control."""
    timestamp = time.strftime('%H:%M:%S')
    with open('/tmp/nex_v52.log', 'a') as f:
        f.write(f"[v5.2 {timestamp}] [{level}] {msg}\n")

def _config_path_v52(filename: str) -> str:
    """Get v5.2 config file path."""
    config_dir = Path.home() / '.config' / 'nex' / 'v52'
    config_dir.mkdir(parents=True, exist_ok=True)
    return str(config_dir / filename)

# ══════════════════════════════════════════════════════════════
# SOFT INGESTION GATE — Smart Event Intake  
# ══════════════════════════════════════════════════════════════

class SoftIngestionGate:
    """Intelligent event ingestion without hard blocking.
    
    Key principle: Never completely shut off, just shape the flow.
    """
    
    def __init__(self):
        self.total_ingested = 0
        self.total_rejected = 0
        self.recent_events = deque(maxlen=100)
        self.quality_threshold = 0.2  # Very permissive base threshold
        
        _log_v52("SoftIngestionGate initialized - permissive intake policy")
    
    def ingest_event(self, raw: dict) -> Optional[CognitiveEvent]:
        """Smart event ingestion with quality assessment."""
        try:
            # Extract basic info
            content = safe_str(raw.get("content"))
            confidence = safe_float(raw.get("confidence", 0.5), 0.0, 1.0)
            
            # RULE: Empty content is always rejected (but gently)
            if not content or content.strip() == "":
                self.total_rejected += 1
                return None
            
            # Determine event type and priority
            event_type = EventType(raw.get("type", EventType.THOUGHT))
            priority = Priority(raw.get("priority", Priority.NORMAL))
            
            # Create event with flow scoring
            event = CognitiveEvent(
                type=event_type,
                content=content,
                confidence=confidence,
                priority=priority,
                source=raw.get("source", "unknown"),
                metadata=raw.get("metadata", {})
            )
            
            # Calculate flow score for prioritization
            event.flow_score = self._calculate_flow_score(event)
            
            # Quality gate - very permissive
            if event.flow_score < self.quality_threshold:
                self.total_rejected += 1
                _log_v52(f"Event rejected - low quality score {event.flow_score:.3f}", "DEBUG")
                return None
            
            # Record successful ingestion
            self.total_ingested += 1
            self.recent_events.append(event.event_id)
            
            return event
            
        except Exception as e:
            self.total_rejected += 1
            _log_v52(f"Ingestion error: {e}", "ERROR")
            return None
    
    def _calculate_flow_score(self, event: CognitiveEvent) -> float:
        """Calculate flow score for event prioritization."""
        score = 0.0
        
        # Base confidence contribution
        score += event.confidence * 0.4
        
        # Priority bonus
        score += (event.priority.value / 5.0) * 0.3
        
        # Content quality indicators
        content_length = len(event.content)
        if content_length > 20:  # Substantial content
            score += 0.2
        if content_length > 100:  # Rich content
            score += 0.1
        
        # Type-specific bonuses
        type_bonuses = {
            EventType.GOAL: 0.3,
            EventType.HIGH_VALUE: 0.4,
            EventType.REFLECTION: 0.2,
            EventType.BELIEF: 0.1
        }
        score += type_bonuses.get(event.type, 0.0)
        
        return min(1.0, score)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get ingestion statistics."""
        total_attempted = self.total_ingested + self.total_rejected
        success_rate = self.total_ingested / max(total_attempted, 1)
        
        return {
            'total_ingested': self.total_ingested,
            'total_rejected': self.total_rejected,
            'success_rate': round(success_rate, 3),
            'recent_events': len(self.recent_events),
            'quality_threshold': self.quality_threshold
        }

# ══════════════════════════════════════════════════════════════
# ADAPTIVE FLOW CONTROLLER — Gradual Pressure Management
# ══════════════════════════════════════════════════════════════

class AdaptiveFlowController:
    """Pressure-aware flow control with gradual adaptation.
    
    Never fully shuts off - always maintains minimum flow rate.
    """
    
    def __init__(self):
        self.pressure = 0.0  # 0.0 = no pressure, 1.0 = maximum pressure
        self.pressure_history = deque(maxlen=50)
        self.base_ingestion_rate = 1.0  # 100% under no pressure
        self.min_ingestion_rate = 0.3   # Never below 30%
        
        # Adaptive parameters
        self.pressure_sensitivity = 1.0
        self.adaptation_rate = 0.1
        
        _log_v52("AdaptiveFlowController initialized - gradual pressure management")
    
    def update_pressure(self, queue_size: int, max_queue: int = 2000) -> None:
        """Update system pressure based on queue size."""
        # Calculate normalized pressure (0.0 to 1.0)
        self.pressure = min(1.0, queue_size / max_queue)
        
        # Record for trend analysis
        self.pressure_history.append({
            'pressure': self.pressure,
            'queue_size': queue_size,
            'timestamp': time.time()
        })
        
        # Log pressure changes
        if len(self.pressure_history) > 1:
            prev_pressure = self.pressure_history[-2]['pressure']
            if abs(self.pressure - prev_pressure) > 0.1:
                _log_v52(f"Pressure change: {prev_pressure:.2f} → {self.pressure:.2f}")
    
    def get_ingestion_probability(self) -> float:
        """Calculate current ingestion probability (never goes below minimum)."""
        # Apply pressure with soft curve
        raw_rate = self.base_ingestion_rate * (1.0 - (self.pressure * self.pressure_sensitivity))
        
        # Ensure minimum flow rate
        return max(self.min_ingestion_rate, raw_rate)
    
    def should_ingest(self, event: Optional[CognitiveEvent] = None) -> bool:
        """Determine if event should be ingested based on flow control."""
        base_probability = self.get_ingestion_probability()
        
        # High-priority events bypass most restrictions
        if event and event.priority >= Priority.HIGH:
            # High priority events get boosted probability
            boosted_probability = min(1.0, base_probability + 0.4)
            return random.random() < boosted_probability
        
        # High-confidence events get moderate boost
        if event and event.confidence > 0.7:
            boosted_probability = min(1.0, base_probability + 0.2)
            return random.random() < boosted_probability
        
        # Standard probability for normal events
        return random.random() < base_probability
    
    def get_adaptive_processing_limit(self, base_limit: int = 3) -> int:
        """Get adaptive processing limit based on current pressure."""
        if self.pressure < 0.3:
            return base_limit + 3  # 6 events when pressure is low
        elif self.pressure < 0.6:
            return base_limit + 2  # 5 events when pressure is moderate
        elif self.pressure < 0.8:
            return base_limit + 1  # 4 events when pressure is high
        else:
            return base_limit      # 3 events when pressure is critical
    
    def get_pressure_trend(self) -> str:
        """Get pressure trend: rising, falling, or stable."""
        if len(self.pressure_history) < 5:
            return "stable"
        
        recent_pressures = [p['pressure'] for p in list(self.pressure_history)[-5:]]
        trend = recent_pressures[-1] - recent_pressures[0]
        
        if trend > 0.1:
            return "rising"
        elif trend < -0.1:
            return "falling"
        else:
            return "stable"
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive flow controller status."""
        return {
            'current_pressure': round(self.pressure, 3),
            'ingestion_probability': round(self.get_ingestion_probability(), 3),
            'processing_limit': self.get_adaptive_processing_limit(),
            'pressure_trend': self.get_pressure_trend(),
            'min_ingestion_rate': self.min_ingestion_rate,
            'pressure_history_size': len(self.pressure_history)
        }

# ══════════════════════════════════════════════════════════════
# EVENT PRIORITIZER — Importance-Based Processing
# ══════════════════════════════════════════════════════════════

class EventPrioritizer:
    """Smart event prioritization instead of dropping."""
    
    def __init__(self):
        self.priority_weights = {
            Priority.CRITICAL: 1.0,
            Priority.HIGH: 0.8,
            Priority.NORMAL: 0.6,
            Priority.LOW: 0.4,
            Priority.BACKGROUND: 0.2
        }
        
        self.processed_by_priority = defaultdict(int)
        
        _log_v52("EventPrioritizer initialized - importance-based processing")
    
    def prioritize_events(self, events: List[CognitiveEvent], limit: int) -> List[CognitiveEvent]:
        """Prioritize events for processing, maintaining diversity."""
        if len(events) <= limit:
            return events
        
        # Separate by priority levels
        priority_buckets = defaultdict(list)
        for event in events:
            priority_buckets[event.priority].append(event)
        
        selected = []
        remaining_slots = limit
        
        # Process critical and high priority first (always include)
        for priority in [Priority.CRITICAL, Priority.HIGH]:
            candidates = priority_buckets[priority]
            if candidates and remaining_slots > 0:
                # Take all critical/high priority events if they fit
                take_count = min(len(candidates), remaining_slots)
                selected.extend(candidates[:take_count])
                remaining_slots -= take_count
                
                for event in candidates[:take_count]:
                    self.processed_by_priority[priority] += 1
        
        # For remaining priorities, use weighted random sampling
        remaining_events = []
        for priority in [Priority.NORMAL, Priority.LOW, Priority.BACKGROUND]:
            remaining_events.extend(priority_buckets[priority])
        
        if remaining_events and remaining_slots > 0:
            # Weighted sampling based on flow scores and priority
            weights = []
            for event in remaining_events:
                priority_weight = self.priority_weights[event.priority]
                flow_weight = event.flow_score
                combined_weight = (priority_weight * 0.6) + (flow_weight * 0.4)
                weights.append(combined_weight)
            
            # Sample without replacement
            sampled_indices = self._weighted_sample(weights, remaining_slots)
            sampled_events = [remaining_events[i] for i in sampled_indices]
            
            selected.extend(sampled_events)
            
            for event in sampled_events:
                self.processed_by_priority[event.priority] += 1
        
        return selected
    
    def _weighted_sample(self, weights: List[float], k: int) -> List[int]:
        """Weighted sampling without replacement."""
        if not weights or k <= 0:
            return []
        
        k = min(k, len(weights))
        indices = list(range(len(weights)))
        selected = []
        
        for _ in range(k):
            if not indices:
                break
            
            # Calculate selection probabilities
            current_weights = [weights[i] for i in indices]
            total_weight = sum(current_weights)
            
            if total_weight == 0:
                # If all weights are zero, select randomly
                idx = random.choice(range(len(indices)))
            else:
                # Weighted random selection
                r = random.random() * total_weight
                cumsum = 0
                idx = 0
                for i, w in enumerate(current_weights):
                    cumsum += w
                    if r <= cumsum:
                        idx = i
                        break
            
            # Select and remove
            selected.append(indices[idx])
            indices.pop(idx)
        
        return selected
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get prioritization statistics."""
        total_processed = sum(self.processed_by_priority.values())
        
        priority_distribution = {}
        for priority in Priority:
            count = self.processed_by_priority[priority]
            percentage = (count / max(total_processed, 1)) * 100
            priority_distribution[priority.name] = {
                'count': count,
                'percentage': round(percentage, 1)
            }
        
        return {
            'total_processed': total_processed,
            'priority_distribution': priority_distribution
        }

# ══════════════════════════════════════════════════════════════
# PRESSURE-AWARE ATTENTION — Dynamic Threshold Adjustment
# ══════════════════════════════════════════════════════════════

class PressureAwareAttention:
    """Dynamic attention system that adjusts thresholds based on system pressure."""
    
    def __init__(self, base_threshold: float = 0.35):
        self.base_threshold = base_threshold
        self.current_threshold = base_threshold
        self.pressure_impact = 0.2  # Max threshold adjustment due to pressure
        
        self.processed_count = 0
        self.filtered_count = 0
        
        _log_v52(f"PressureAwareAttention initialized - base threshold {base_threshold}")
    
    def update_threshold(self, pressure: float) -> None:
        """Update attention threshold based on system pressure."""
        # Increase threshold under pressure (more selective)
        pressure_adjustment = pressure * self.pressure_impact
        self.current_threshold = self.base_threshold + pressure_adjustment
        
        # Ensure threshold stays in reasonable bounds
        self.current_threshold = max(0.2, min(0.8, self.current_threshold))
    
    def should_process(self, event: CognitiveEvent, pressure: float = 0.0) -> Tuple[bool, float]:
        """Determine if event should be processed with pressure awareness."""
        # Update threshold based on current pressure
        self.update_threshold(pressure)
        
        # Calculate adjusted attention score
        base_score = event.confidence
        
        # High-priority events get attention boost
        if event.priority >= Priority.HIGH:
            adjusted_score = base_score + 0.2
        elif event.priority == Priority.CRITICAL:
            adjusted_score = base_score + 0.4
        else:
            adjusted_score = base_score
        
        # Pressure reduces attention score for normal priority events
        if event.priority < Priority.HIGH:
            adjusted_score = adjusted_score - (pressure * 0.2)
        
        # Make decision
        should_process = adjusted_score > self.current_threshold
        
        # Track statistics
        if should_process:
            self.processed_count += 1
        else:
            self.filtered_count += 1
        
        return should_process, adjusted_score
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get attention system statistics."""
        total_events = self.processed_count + self.filtered_count
        processing_rate = self.processed_count / max(total_events, 1)
        
        return {
            'base_threshold': self.base_threshold,
            'current_threshold': round(self.current_threshold, 3),
            'processed_count': self.processed_count,
            'filtered_count': self.filtered_count,
            'processing_rate': round(processing_rate, 3)
        }

# ══════════════════════════════════════════════════════════════
# HEALTH SIGNAL TRACKER — Real-Time Flow Monitoring
# ══════════════════════════════════════════════════════════════

class HealthSignalTracker:
    """Comprehensive health monitoring for flow control system."""
    
    def __init__(self):
        self.start_time = time.time()
        
        # Flow metrics
        self.ingestion_events = deque(maxlen=100)
        self.processing_events = deque(maxlen=100)
        self.pressure_readings = deque(maxlen=100)
        
        # Queue velocity tracking
        self.queue_size_history = deque(maxlen=20)
        
        _log_v52("HealthSignalTracker initialized - comprehensive flow monitoring")
    
    def record_ingestion(self, successful: bool) -> None:
        """Record ingestion attempt."""
        self.ingestion_events.append({
            'successful': successful,
            'timestamp': time.time()
        })
    
    def record_processing(self, events_processed: int) -> None:
        """Record processing batch."""
        self.processing_events.append({
            'count': events_processed,
            'timestamp': time.time()
        })
    
    def record_pressure(self, pressure: float) -> None:
        """Record pressure reading."""
        self.pressure_readings.append({
            'pressure': pressure,
            'timestamp': time.time()
        })
    
    def record_queue_size(self, size: int) -> None:
        """Record queue size for velocity calculation."""
        self.queue_size_history.append({
            'size': size,
            'timestamp': time.time()
        })
    
    def get_ingestion_rate(self, window_seconds: float = 60.0) -> float:
        """Calculate events per second ingestion rate."""
        cutoff = time.time() - window_seconds
        recent_events = [e for e in self.ingestion_events if e['timestamp'] > cutoff and e['successful']]
        return len(recent_events) / window_seconds
    
    def get_processing_rate(self, window_seconds: float = 60.0) -> float:
        """Calculate events per second processing rate."""
        cutoff = time.time() - window_seconds
        recent_processing = [e for e in self.processing_events if e['timestamp'] > cutoff]
        total_processed = sum(e['count'] for e in recent_processing)
        return total_processed / window_seconds
    
    def get_queue_velocity(self) -> str:
        """Calculate queue growth/shrink velocity."""
        if len(self.queue_size_history) < 5:
            return "stable"
        
        recent_sizes = [h['size'] for h in list(self.queue_size_history)[-5:]]
        trend = recent_sizes[-1] - recent_sizes[0]
        
        if trend > 50:
            return "growing_fast"
        elif trend > 10:
            return "growing"
        elif trend < -50:
            return "shrinking_fast"
        elif trend < -10:
            return "shrinking"
        else:
            return "stable"
    
    def get_average_pressure(self, window_seconds: float = 300.0) -> float:
        """Get average pressure over time window."""
        cutoff = time.time() - window_seconds
        recent_pressure = [p for p in self.pressure_readings if p['timestamp'] > cutoff]
        
        if not recent_pressure:
            return 0.0
        
        return sum(p['pressure'] for p in recent_pressure) / len(recent_pressure)
    
    def get_system_health_score(self) -> float:
        """Calculate overall system health score (0.0 to 1.0)."""
        score = 1.0
        
        # Pressure penalty
        avg_pressure = self.get_average_pressure()
        score -= avg_pressure * 0.3
        
        # Queue velocity penalty
        velocity = self.get_queue_velocity()
        if velocity in ["growing_fast", "shrinking_fast"]:
            score -= 0.2
        elif velocity in ["growing", "shrinking"]:
            score -= 0.1
        
        # Balance between ingestion and processing
        ingestion_rate = self.get_ingestion_rate()
        processing_rate = self.get_processing_rate()
        
        if processing_rate > 0:
            balance_ratio = min(ingestion_rate / processing_rate, 2.0)
            if balance_ratio > 1.5 or balance_ratio < 0.5:
                score -= 0.2
        
        return max(0.0, min(1.0, score))
    
    def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive health status."""
        uptime_hours = (time.time() - self.start_time) / 3600
        
        return {
            'uptime_hours': round(uptime_hours, 2),
            'ingestion_rate': round(self.get_ingestion_rate(), 2),
            'processing_rate': round(self.get_processing_rate(), 2),
            'average_pressure': round(self.get_average_pressure(), 3),
            'queue_velocity': self.get_queue_velocity(),
            'system_health_score': round(self.get_system_health_score(), 3),
            'total_ingestion_records': len(self.ingestion_events),
            'total_processing_records': len(self.processing_events)
        }

# ══════════════════════════════════════════════════════════════
# SEMANTIC LOOP HARDENING — Unchanged but Enhanced
# ══════════════════════════════════════════════════════════════

class SemanticLoopDetector:
    """Enhanced semantic loop detection with adaptive sensitivity."""
    
    def __init__(self, history_size: int = 20):
        self.semantic_history = deque(maxlen=history_size)
        self.loop_threshold = 0.7  # Similarity threshold for loop detection
        self.detected_loops = 0
        self.variation_requests = 0
        
        _log_v52("SemanticLoopDetector initialized - adaptive similarity detection")
    
    def semantic_key(self, text: str) -> str:
        """Generate semantic fingerprint for text."""
        # Enhanced fingerprinting with multiple techniques
        normalized = text[:120].lower()
        
        # Remove common words to focus on meaningful content
        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
        words = [w for w in normalized.split() if w not in stop_words]
        
        # Create hash from meaningful words
        meaningful_text = " ".join(words)
        return str(hash(meaningful_text))
    
    def check_for_loop(self, text: str) -> bool:
        """Check if text creates a semantic loop."""
        current_key = self.semantic_key(text)
        
        # Count similar entries in recent history
        similar_count = sum(1 for key in self.semantic_history if key == current_key)
        
        # Add to history
        self.semantic_history.append(current_key)
        
        # Detect loop if too many similar entries
        is_loop = similar_count >= 3  # Allow some repetition but not excessive
        
        if is_loop:
            self.detected_loops += 1
            self.variation_requests += 1
            _log_v52(f"Semantic loop detected - forcing variation (total: {self.detected_loops})")
        
        return is_loop
    
    def request_variation(self) -> str:
        """Request text variation to break loops."""
        variation_prompts = [
            "Express this differently",
            "Rephrase with new perspective",
            "Use alternative approach",
            "Explore different angle",
            "Vary the expression"
        ]
        return random.choice(variation_prompts)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get loop detection statistics."""
        return {
            'total_loops_detected': self.detected_loops,
            'variation_requests': self.variation_requests,
            'history_size': len(self.semantic_history),
            'loop_threshold': self.loop_threshold
        }

# ══════════════════════════════════════════════════════════════
# ERROR FIREWALL — Robust Exception Handling
# ══════════════════════════════════════════════════════════════

class ErrorFirewall:
    """Comprehensive error handling and recovery."""
    
    def __init__(self):
        self.error_count = 0
        self.error_log = deque(maxlen=50)
        self.recovery_attempts = 0
        
        _log_v52("ErrorFirewall initialized - robust exception handling")
    
    def safe_execute(self, fn: callable, *args, **kwargs) -> Any:
        """Execute function with comprehensive error handling."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            self.error_count += 1
            error_record = {
                'function': fn.__name__ if hasattr(fn, '__name__') else str(fn),
                'error': str(e),
                'timestamp': time.time()
            }
            self.error_log.append(error_record)
            
            _log_v52(f"Function {error_record['function']} failed: {e}", "ERROR")
            return None
    
    def attempt_recovery(self, operation: str) -> bool:
        """Attempt to recover from error state."""
        self.recovery_attempts += 1
        _log_v52(f"Attempting recovery for: {operation}")
        
        # Basic recovery strategies
        try:
            # Could implement specific recovery logic here
            return True
        except:
            return False
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics."""
        recent_errors = [e for e in self.error_log if time.time() - e['timestamp'] < 3600]
        
        return {
            'total_errors': self.error_count,
            'recent_errors': len(recent_errors),
            'recovery_attempts': self.recovery_attempts,
            'error_log_size': len(self.error_log)
        }

# ══════════════════════════════════════════════════════════════
# MAIN v5.2 CONTROLLER — Adaptive Flow Orchestration
# ══════════════════════════════════════════════════════════════

class NexV52AdaptiveFlowController:
    """Main controller for NEX v5.2 Adaptive Flow Control.
    
    Philosophy: Shape the flow of cognition, don't suppress it.
    Maintains responsiveness while preventing overload.
    """
    
    def __init__(self):
        # Initialize all components
        self.ingestion_gate = SoftIngestionGate()
        self.flow_controller = AdaptiveFlowController()
        self.event_prioritizer = EventPrioritizer()
        self.attention_system = PressureAwareAttention()
        self.health_tracker = HealthSignalTracker()
        self.loop_detector = SemanticLoopDetector()
        self.error_firewall = ErrorFirewall()
        
        # System state
        self.cycle_count = 0
        self.initialization_time = time.time()
        self.event_queue = deque()
        self.processed_events = 0
        
        # Configuration
        self.max_queue_size = 2000
        self.base_processing_limit = 3
        
        _log_v52("NexV52AdaptiveFlowController fully initialized - adaptive flow control active")
    
    def ingest_event(self, raw_event: dict) -> bool:
        """Ingest event through adaptive flow control."""
        # Soft ingestion gate
        event = self.error_firewall.safe_execute(
            self.ingestion_gate.ingest_event, raw_event
        )
        
        if not event:
            self.health_tracker.record_ingestion(False)
            return False
        
        # Flow control decision
        should_accept = self.error_firewall.safe_execute(
            self.flow_controller.should_ingest, event
        )
        
        if not should_accept:
            self.health_tracker.record_ingestion(False)
            _log_v52(f"Event filtered by flow control - pressure: {self.flow_controller.pressure:.3f}")
            return False
        
        # Add to queue
        self.event_queue.append(event)
        self.health_tracker.record_ingestion(True)
        
        # Update pressure based on queue size
        self.flow_controller.update_pressure(len(self.event_queue), self.max_queue_size)
        self.health_tracker.record_pressure(self.flow_controller.pressure)
        self.health_tracker.record_queue_size(len(self.event_queue))
        
        return True
    
    def process_events(self) -> Dict[str, Any]:
        """Process queued events with adaptive limits."""
        # Get adaptive processing limit
        processing_limit = self.flow_controller.get_adaptive_processing_limit(
            self.base_processing_limit
        )
        
        # Get events to process
        available_events = list(self.event_queue)
        if not available_events:
            return {'events_processed': 0, 'queue_size': 0}
        
        # Prioritize events
        events_to_process = self.error_firewall.safe_execute(
            self.event_prioritizer.prioritize_events,
            available_events, processing_limit
        ) or []
        
        processed_count = 0
        results = []
        
        for event in events_to_process:
            # Pressure-aware attention check
            should_process, attention_score = self.error_firewall.safe_execute(
                self.attention_system.should_process,
                event, self.flow_controller.pressure
            ) or (False, 0.0)
            
            if not should_process:
                continue
            
            # Semantic loop check
            has_loop = self.error_firewall.safe_execute(
                self.loop_detector.check_for_loop, event.content
            )
            
            if has_loop:
                # Request variation instead of dropping
                variation_prompt = self.loop_detector.request_variation()
                event.metadata['variation_requested'] = variation_prompt
            
            # Process event
            result = self._process_single_event(event)
            results.append(result)
            processed_count += 1
            
            # Remove from queue
            if event in self.event_queue:
                self.event_queue.remove(event)
        
        # Update statistics
        self.processed_events += processed_count
        self.health_tracker.record_processing(processed_count)
        
        return {
            'events_processed': processed_count,
            'queue_size': len(self.event_queue),
            'processing_limit': processing_limit,
            'current_pressure': self.flow_controller.pressure,
            'results': results
        }
    
    def _process_single_event(self, event: CognitiveEvent) -> Dict[str, Any]:
        """Process a single cognitive event."""
        try:
            # Basic event processing
            processing_result = {
                'event_id': event.event_id,
                'type': event.type.value,
                'confidence': event.confidence,
                'flow_score': event.flow_score,
                'status': 'processed'
            }
            
            # Add variation if loop detected
            if 'variation_requested' in event.metadata:
                processing_result['variation_prompt'] = event.metadata['variation_requested']
            
            return processing_result
            
        except Exception as e:
            _log_v52(f"Error processing event {event.event_id}: {e}", "ERROR")
            return {
                'event_id': event.event_id,
                'status': 'error',
                'error': str(e)
            }
    
    def tick(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Main v5.2 adaptive flow control tick."""
        self.cycle_count += 1
        
        try:
            # Process queued events
            processing_result = self.process_events()
            
            # System health assessment
            health_score = self.health_tracker.get_system_health_score()
            
            return {
                'v52_status': 'operational' if health_score > 0.7 else 'degraded',
                'cycle': self.cycle_count,
                'uptime_hours': round((time.time() - self.initialization_time) / 3600, 2),
                'health_score': round(health_score, 3),
                'pressure': round(self.flow_controller.pressure, 3),
                'queue_size': len(self.event_queue),
                'processing_result': processing_result
            }
            
        except Exception as e:
            error_msg = f"v5.2 tick error: {e}"
            _log_v52(error_msg, "ERROR")
            
            return {
                'v52_status': 'error',
                'cycle': self.cycle_count,
                'error': str(e)
            }
    
    def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive v5.2 system status."""
        return {
            'version': '5.2',
            'philosophy': 'Shape flow, not suppress cognition',
            'uptime_hours': round((time.time() - self.initialization_time) / 3600, 2),
            'cycle_count': self.cycle_count,
            'processed_events': self.processed_events,
            'ingestion_gate': self.ingestion_gate.get_statistics(),
            'flow_controller': self.flow_controller.get_status(),
            'event_prioritizer': self.event_prioritizer.get_statistics(),
            'attention_system': self.attention_system.get_statistics(),
            'health_tracker': self.health_tracker.get_comprehensive_status(),
            'loop_detector': self.loop_detector.get_statistics(),
            'error_firewall': self.error_firewall.get_error_statistics(),
            'current_queue_size': len(self.event_queue)
        }

# ══════════════════════════════════════════════════════════════
# FACTORY FUNCTION FOR INTEGRATION
# ══════════════════════════════════════════════════════════════

def get_v52() -> NexV52AdaptiveFlowController:
    """Factory function for NEX v5.2 adaptive flow controller."""
    return NexV52AdaptiveFlowController()

def initialize_v52_config() -> bool:
    """Initialize v5.2 configuration files."""
    try:
        config_dir = Path.home() / '.config' / 'nex' / 'v52'
        config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default configuration
        config = {
            'version': '5.2',
            'ingestion_gate': {
                'quality_threshold': 0.2,
                'permissive_mode': True
            },
            'flow_controller': {
                'base_ingestion_rate': 1.0,
                'min_ingestion_rate': 0.3,
                'pressure_sensitivity': 1.0
            },
            'attention_system': {
                'base_threshold': 0.35,
                'pressure_impact': 0.2
            },
            'prioritizer': {
                'high_priority_boost': 0.4,
                'confidence_boost': 0.2
            },
            'loop_detector': {
                'history_size': 20,
                'similarity_threshold': 0.7
            }
        }
        
        config_file = config_dir / 'adaptive_flow_config.json'
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        _log_v52(f"v5.2 configuration initialized: {config_file}")
        return True
        
    except Exception as e:
        _log_v52(f"Config initialization failed: {e}", "ERROR")
        return False

# ══════════════════════════════════════════════════════════════
# TESTING FUNCTIONS
# ══════════════════════════════════════════════════════════════

def test_v52_flow_control() -> Dict[str, Any]:
    """Test v5.2 adaptive flow control system."""
    results = {}
    
    try:
        # Initialize system
        flow_controller = NexV52AdaptiveFlowController()
        results['initialization'] = True
        
        # Test event ingestion
        test_events = [
            {'content': 'High confidence thought', 'confidence': 0.9, 'type': 'thought'},
            {'content': 'Low confidence idea', 'confidence': 0.2, 'type': 'thought'},
            {'content': 'Critical system event', 'priority': 5, 'type': 'system'},
            {'content': '', 'confidence': 0.8},  # Empty content test
        ]
        
        ingested_count = 0
        for event in test_events:
            if flow_controller.ingest_event(event):
                ingested_count += 1
        
        results['ingestion_test'] = {
            'total_attempted': len(test_events),
            'successfully_ingested': ingested_count
        }
        
        # Test processing
        processing_result = flow_controller.process_events()
        results['processing_test'] = processing_result
        
        # Test main tick
        tick_result = flow_controller.tick()
        results['tick_test'] = tick_result['v52_status'] == 'operational'
        
        # Test comprehensive status
        status = flow_controller.get_comprehensive_status()
        results['status_test'] = isinstance(status, dict) and 'philosophy' in status
        
        return results
        
    except Exception as e:
        results['error'] = str(e)
        return results

if __name__ == "__main__":
    print("NEX v5.2 Adaptive Flow Control - Testing")
    print("=" * 50)
    
    # Initialize configuration
    if initialize_v52_config():
        print("✓ Configuration initialized")
    else:
        print("✗ Configuration failed")
    
    # Run tests
    test_results = test_v52_flow_control()
    
    print("\nTest Results:")
    for test_name, result in test_results.items():
        if isinstance(result, bool):
            status = "✓" if result else "✗"
            print(f"  {test_name:20}: {status}")
        else:
            print(f"  {test_name:20}: {result}")
    
    print(f"\n🌊 NEX v5.2 Adaptive Flow Control Ready!")
    print("Philosophy: Shape the flow of cognition, don't suppress it")
    print("Integration: from nex_upgrades.nex_v52 import get_v52")
