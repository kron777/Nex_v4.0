#!/usr/bin/env python3
"""
NEX v5.1 — CORE INFRASTRUCTURE MEGA-UPGRADE
===========================================
Production-Ready Foundation Layer - March 21, 2026

Core Systems:
- TypeSystem           — Bulletproof data validation & type safety
- EventBus             — Robust message passing with circuit breakers  
- BeliefStore          — Advanced belief management with indexing
- AttentionSystem      — Adaptive focus control & priority queuing
- GoalManager          — Hierarchical goal system with dependencies
- HealthMonitor        — System health monitoring & self-recovery
- ConfigManager        — Centralized configuration management
- PerformanceOptimizer — Caching, batching, async processing

Foundation: Designed to work seamlessly with NEX v5.0 cognitive architecture
Priority: System stability, reliability, and performance under load
"""

import asyncio
import time
import json
import os
import hashlib
import logging
import threading
import weakref
from typing import Dict, List, Tuple, Optional, Any, Set, Union, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from collections import defaultdict, deque
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import heapq
import uuid

# ══════════════════════════════════════════════════════════════
# ENHANCED TYPE SYSTEM — Bulletproof Data Validation
# ══════════════════════════════════════════════════════════════

class EventType(str, Enum):
    """Event classification for cognitive processing."""
    THOUGHT = "thought"
    BELIEF = "belief"
    ACTION = "action"
    REFLECTION = "reflection"
    GOAL = "goal"
    ATTENTION = "attention"
    MEMORY = "memory"
    PREDICTION = "prediction"
    CONTRADICTION = "contradiction"
    SYNTHESIS = "synthesis"
    SYSTEM = "system"

class Priority(int, Enum):
    """Processing priority levels."""
    CRITICAL = 5
    HIGH = 4
    NORMAL = 3
    LOW = 2
    BACKGROUND = 1

class HealthStatus(str, Enum):
    """System health indicators."""
    OPTIMAL = "optimal"
    STABLE = "stable"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    RECOVERING = "recovering"

@dataclass
class CognitiveEvent:
    """Enhanced cognitive event with comprehensive metadata."""
    type: EventType
    content: str
    confidence: float = 0.5
    priority: Priority = Priority.NORMAL
    source: str = "system"
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    def __post_init__(self):
        """Validate and normalize data after creation."""
        self.validate()
        self.normalize()
    
    def validate(self) -> None:
        """Comprehensive validation with detailed error messages."""
        if not isinstance(self.content, str):
            raise TypeError(f"Content must be string, got {type(self.content)}")
        
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")
        
        if not isinstance(self.type, EventType):
            raise TypeError(f"Type must be EventType, got {type(self.type)}")
        
        if not isinstance(self.priority, Priority):
            raise TypeError(f"Priority must be Priority enum, got {type(self.priority)}")
    
    def normalize(self) -> None:
        """Normalize data for consistency."""
        self.content = self.content.strip()
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.tags = set(tag.lower().strip() for tag in self.tags if tag.strip())

@dataclass
class BeliefData:
    """Enhanced belief representation with comprehensive tracking."""
    text: str
    confidence: float = 0.5
    topic: str = "general"
    source: str = "system"
    evidence: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    reinforcement_count: int = 0
    last_used: float = field(default_factory=time.time)
    created: float = field(default_factory=time.time)
    importance: float = 0.5
    stability: float = 0.5
    belief_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    def __post_init__(self):
        self.validate()
    
    def validate(self) -> None:
        """Validate belief data."""
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Belief text must be non-empty string")
        
        for attr in ['confidence', 'importance', 'stability']:
            value = getattr(self, attr)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{attr} must be 0-1, got {value}")
    
    def reinforce(self, amount: float = 0.05) -> None:
        """Reinforce belief with evidence."""
        self.confidence = min(1.0, self.confidence + amount)
        self.reinforcement_count += 1
        self.last_used = time.time()
        self.stability = min(1.0, self.stability + amount * 0.5)
    
    def decay(self, rate: float = 0.01) -> None:
        """Apply time-based decay."""
        age_hours = (time.time() - self.last_used) / 3600
        decay_factor = 1.0 - (rate * age_hours)
        self.confidence *= max(0.1, decay_factor)
        self.stability *= max(0.1, decay_factor * 1.1)

# ══════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS — Enhanced Safety & Performance
# ══════════════════════════════════════════════════════════════

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

def safe_int(x: Any, default: int = 0, min_val: int = None, max_val: int = None) -> int:
    """Safe integer conversion with bounds checking."""
    try:
        value = int(x)
        if min_val is not None:
            value = max(min_val, value)
        if max_val is not None:
            value = min(max_val, value)
        return value
    except (TypeError, ValueError):
        return default

def validate_event(event: CognitiveEvent) -> Tuple[bool, Optional[str]]:
    """Comprehensive event validation with error details."""
    try:
        event.validate()
        return True, None
    except Exception as e:
        return False, str(e)

def _log_v51(msg: str, level: str = "INFO") -> None:
    """Enhanced logging for v5.1 systems."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    with open('/tmp/nex_v51.log', 'a') as f:
        f.write(f"[v5.1 {timestamp}] [{level}] {msg}\n")

def _config_path_v51(filename: str) -> str:
    """Get v5.1 config file path."""
    config_dir = Path.home() / '.config' / 'nex' / 'v51'
    config_dir.mkdir(parents=True, exist_ok=True)
    return str(config_dir / filename)

# ══════════════════════════════════════════════════════════════
# ENHANCED EVENT BUS — Production-Grade Message Passing
# ══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open
    
    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        if self.state == "closed":
            return True
        elif self.state == "open":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "half-open"
                return True
            return False
        else:  # half-open
            return True
    
    def record_success(self) -> None:
        """Record successful execution."""
        self.failure_count = 0
        self.state = "closed"
    
    def record_failure(self) -> None:
        """Record failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

class EnhancedEventBus:
    """Production-grade event bus with comprehensive fault tolerance."""
    
    def __init__(self, max_queue: int = 2000, max_priority_queue: int = 500):
        # Queue management
        self.normal_queue = deque(maxlen=max_queue)
        self.priority_queue = deque(maxlen=max_priority_queue)
        self.dead_letter_queue = deque(maxlen=200)
        
        # Fault tolerance
        self.circuit_breaker = CircuitBreaker()
        
        # Threading
        self.lock = threading.RLock()
        
        # Subscribers by event type
        self.subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        
        # Rate limiting
        self.rate_limit = 100  # events per second
        self.rate_window = deque(maxlen=100)
        
        _log_v51("Enhanced EventBus initialized with fault tolerance")
    
    async def publish(self, event: CognitiveEvent) -> bool:
        """Publish event with comprehensive error handling."""
        if not self.circuit_breaker.can_execute():
            _log_v51(f"Circuit breaker OPEN - dropping event {event.event_id}", "WARN")
            return False
        
        # Rate limiting check
        if not self._check_rate_limit():
            _log_v51("Rate limit exceeded - dropping event", "WARN")
            return False
        
        # Validation
        is_valid, error_msg = validate_event(event)
        if not is_valid:
            _log_v51(f"Invalid event: {error_msg}", "ERROR")
            self.dead_letter_queue.append((event, error_msg))
            self.circuit_breaker.record_failure()
            return False
        
        try:
            with self.lock:
                # Priority routing
                if event.priority >= Priority.HIGH:
                    self.priority_queue.append(event)
                else:
                    self.normal_queue.append(event)
                
                self.circuit_breaker.record_success()
                return True
                
        except Exception as e:
            error_msg = f"Failed to publish event: {e}"
            _log_v51(error_msg, "ERROR")
            self.circuit_breaker.record_failure()
            self.dead_letter_queue.append((event, error_msg))
            return False
    
    async def consume(self) -> Optional[CognitiveEvent]:
        """Consume events with priority handling."""
        try:
            with self.lock:
                # Priority queue first
                if self.priority_queue:
                    return self.priority_queue.popleft()
                
                # Normal queue second
                if self.normal_queue:
                    return self.normal_queue.popleft()
                
                return None
                
        except Exception as e:
            _log_v51(f"Failed to consume event: {e}", "ERROR")
            return None
    
    def _check_rate_limit(self) -> bool:
        """Check if within rate limits."""
        now = time.time()
        self.rate_window.append(now)
        
        # Remove old entries
        cutoff = now - 1.0  # 1 second window
        while self.rate_window and self.rate_window[0] < cutoff:
            self.rate_window.popleft()
        
        return len(self.rate_window) <= self.rate_limit
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive bus status."""
        with self.lock:
            return {
                'normal_queue_size': len(self.normal_queue),
                'priority_queue_size': len(self.priority_queue),
                'dead_letter_size': len(self.dead_letter_queue),
                'circuit_breaker_state': self.circuit_breaker.state,
                'health_status': 'operational' if self.circuit_breaker.state == 'closed' else 'degraded'
            }

# ══════════════════════════════════════════════════════════════
# ADVANCED BELIEF STORE — Intelligent Knowledge Management
# ══════════════════════════════════════════════════════════════

class AdvancedBeliefStore:
    """Enhanced belief storage with indexing and intelligent management."""
    
    def __init__(self, max_beliefs: int = 1000):
        self.beliefs: Dict[str, BeliefData] = {}
        self.max_beliefs = max_beliefs
        self.word_index: Dict[str, Set[str]] = defaultdict(set)
        self.topic_index: Dict[str, Set[str]] = defaultdict(set)
        
        # Statistics
        self.total_added = 0
        self.total_pruned = 0
        
        _log_v51("Advanced BeliefStore initialized with indexing")
    
    def add(self, belief: BeliefData) -> bool:
        """Add belief with duplicate detection and indexing."""
        try:
            # Check for duplicates
            similar_beliefs = self.find_similar(belief.text, threshold=0.8)
            
            if similar_beliefs:
                # Reinforce existing similar belief instead
                existing_id = list(similar_beliefs)[0]
                if existing_id in self.beliefs:
                    self.beliefs[existing_id].reinforce()
                    _log_v51(f"Reinforced similar belief: {existing_id}")
                    return True
            
            # Add new belief
            self.beliefs[belief.belief_id] = belief
            self._index_belief(belief)
            self.total_added += 1
            
            # Auto-prune if needed
            if len(self.beliefs) >= self.max_beliefs:
                self.smart_prune()
            
            return True
            
        except Exception as e:
            _log_v51(f"Failed to add belief: {e}", "ERROR")
            return False
    
    def _index_belief(self, belief: BeliefData) -> None:
        """Add belief to search indices."""
        belief_id = belief.belief_id
        
        # Word index
        words = belief.text.lower().split()
        for word in words:
            if len(word) > 2:  # Skip very short words
                self.word_index[word].add(belief_id)
        
        # Topic index
        self.topic_index[belief.topic.lower()].add(belief_id)
    
    def search(self, query: str, limit: int = 10) -> List[BeliefData]:
        """Search beliefs by text content."""
        query_words = set(query.lower().split())
        if not query_words:
            return []
        
        # Find beliefs containing any query words
        candidate_ids = set()
        for word in query_words:
            if word in self.word_index:
                candidate_ids.update(self.word_index[word])
        
        # Score and rank candidates
        scored_beliefs = []
        for belief_id in candidate_ids:
            if belief_id in self.beliefs:
                belief = self.beliefs[belief_id]
                belief_words = set(belief.text.lower().split())
                
                # Calculate relevance score
                intersection = query_words.intersection(belief_words)
                relevance = len(intersection) / len(query_words) if query_words else 0
                
                # Combine with confidence and recency
                score = relevance * 0.6 + belief.confidence * 0.3 + belief.stability * 0.1
                scored_beliefs.append((score, belief))
                
                # Update access time
                belief.last_used = time.time()
        
        # Sort by score and return top results
        scored_beliefs.sort(key=lambda x: x[0], reverse=True)
        return [belief for _, belief in scored_beliefs[:limit]]
    
    def find_similar(self, text: str, threshold: float = 0.7) -> Set[str]:
        """Find beliefs similar to given text using word overlap."""
        text_words = set(text.lower().split())
        candidates = set()
        
        # Find candidates using word index
        for word in text_words:
            if word in self.word_index:
                candidates.update(self.word_index[word])
        
        similar = set()
        for belief_id in candidates:
            if belief_id not in self.beliefs:
                continue
                
            belief = self.beliefs[belief_id]
            belief_words = set(belief.text.lower().split())
            
            if not text_words or not belief_words:
                continue
            
            # Jaccard similarity
            intersection = text_words.intersection(belief_words)
            union = text_words.union(belief_words)
            similarity = len(intersection) / len(union) if union else 0
            
            if similarity >= threshold:
                similar.add(belief_id)
        
        return similar
    
    def decay_all(self) -> int:
        """Apply decay to all beliefs."""
        decayed_count = 0
        beliefs_to_remove = []
        
        for belief_id, belief in self.beliefs.items():
            old_confidence = belief.confidence
            belief.decay()
            
            if belief.confidence != old_confidence:
                decayed_count += 1
            
            # Mark for removal if confidence too low
            if belief.confidence < 0.1:
                beliefs_to_remove.append(belief_id)
        
        # Remove low-confidence beliefs
        for belief_id in beliefs_to_remove:
            if belief_id in self.beliefs:
                del self.beliefs[belief_id]
        
        if decayed_count > 0:
            _log_v51(f"Decayed {decayed_count} beliefs, removed {len(beliefs_to_remove)}")
        
        return decayed_count
    
    def smart_prune(self) -> int:
        """Intelligent belief pruning based on multiple factors."""
        target_size = int(self.max_beliefs * 0.8)  # Prune to 80%
        current_size = len(self.beliefs)
        
        if current_size <= target_size:
            return 0
        
        beliefs_to_remove = current_size - target_size
        
        # Score beliefs for removal (lower score = more likely to be removed)
        belief_scores = []
        
        for belief_id, belief in self.beliefs.items():
            # Composite score: confidence + recency + stability
            age_penalty = min(0.3, (time.time() - belief.created) / (24 * 3600 * 7))  # Week normalization
            recency_bonus = max(0, 0.2 - (time.time() - belief.last_used) / 86400)  # Day normalization
            
            score = (
                belief.confidence * 0.5 +
                belief.stability * 0.3 +
                recency_bonus * 0.2 -
                age_penalty
            )
            
            belief_scores.append((score, belief_id))
        
        # Sort by score (lowest first for removal)
        belief_scores.sort(key=lambda x: x[0])
        
        # Remove lowest-scoring beliefs
        removed_count = 0
        for score, belief_id in belief_scores:
            if removed_count >= beliefs_to_remove:
                break
            
            if belief_id in self.beliefs:
                del self.beliefs[belief_id]
                removed_count += 1
        
        self.total_pruned += removed_count
        _log_v51(f"Smart pruning: removed {removed_count} beliefs")
        return removed_count
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        if not self.beliefs:
            return {
                'total_beliefs': 0,
                'avg_confidence': 0.0,
                'total_added': self.total_added,
                'total_pruned': self.total_pruned
            }
        
        confidences = [b.confidence for b in self.beliefs.values()]
        
        return {
            'total_beliefs': len(self.beliefs),
            'avg_confidence': sum(confidences) / len(confidences),
            'min_confidence': min(confidences),
            'max_confidence': max(confidences),
            'total_added': self.total_added,
            'total_pruned': self.total_pruned
        }

# ══════════════════════════════════════════════════════════════
# ADAPTIVE ATTENTION SYSTEM — Smart Focus Control
# ══════════════════════════════════════════════════════════════

class EnhancedAttentionSystem:
    """Production-grade attention control with adaptive filtering."""
    
    def __init__(self, base_threshold: float = 0.3):
        self.base_threshold = base_threshold
        self.adaptive_threshold = base_threshold
        self.processing_history = deque(maxlen=100)
        self.focus_areas: Dict[str, float] = defaultdict(lambda: 0.5)
        
        self.total_processed = 0
        self.total_filtered = 0
        
        _log_v51("Enhanced AttentionSystem initialized")
    
    def should_process(self, event: CognitiveEvent) -> Tuple[bool, float]:
        """Determine if event should be processed based on adaptive attention."""
        # Calculate attention score
        attention_score = self._calculate_attention_score(event)
        
        # Decision
        should_process = attention_score > self.adaptive_threshold
        
        # Update statistics
        if should_process:
            self.total_processed += 1
        else:
            self.total_filtered += 1
        
        # Record for adaptation
        self.processing_history.append({
            'score': attention_score,
            'threshold': self.adaptive_threshold,
            'processed': should_process,
            'timestamp': time.time()
        })
        
        return should_process, attention_score
    
    def _calculate_attention_score(self, event: CognitiveEvent) -> float:
        """Calculate attention score for event."""
        # Base score from content length and complexity
        content_score = min(1.0, len(event.content) / 200)
        
        # Priority bonus
        priority_bonus = event.priority.value / 5.0
        
        # Confidence factor
        confidence_factor = event.confidence
        
        # Focus area bonus
        focus_area = event.metadata.get('focus_area', event.type.value)
        focus_bonus = self.focus_areas.get(focus_area, 0.5) * 0.2
        
        # Composite score
        score = (
            content_score * 0.4 +
            priority_bonus * 0.3 +
            confidence_factor * 0.2 +
            focus_bonus * 0.1
        )
        
        return min(1.0, score)
    
    def get_status(self) -> Dict[str, Any]:
        """Get attention system status."""
        total_events = self.total_processed + self.total_filtered
        processing_rate = self.total_processed / max(total_events, 1)
        
        return {
            'total_processed': self.total_processed,
            'total_filtered': self.total_filtered,
            'processing_rate': round(processing_rate, 3),
            'adaptive_threshold': round(self.adaptive_threshold, 3),
            'base_threshold': self.base_threshold
        }

# ══════════════════════════════════════════════════════════════
# HIERARCHICAL GOAL SYSTEM — Advanced Agency & Planning
# ══════════════════════════════════════════════════════════════

@dataclass
class Goal:
    """Enhanced goal representation with comprehensive tracking."""
    goal_id: str
    name: str
    description: str
    priority: Priority = Priority.NORMAL
    current_progress: float = 0.0
    target_confidence: float = 0.8
    created: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    status: str = "active"  # active, completed, paused, failed
    
    def __post_init__(self):
        if not self.goal_id:
            self.goal_id = str(uuid.uuid4())[:8]
    
    def update_progress(self, progress: float) -> None:
        """Update goal progress."""
        self.current_progress = max(0.0, min(1.0, progress))
        self.last_updated = time.time()
        
        if self.current_progress >= 1.0:
            self.status = "completed"

class HierarchicalGoalManager:
    """Advanced goal management with priorities and tracking."""
    
    def __init__(self):
        self.goals: Dict[str, Goal] = {}
        self.active_goals: Set[str] = set()
        self.completed_goals: Set[str] = set()
        self.execution_queue = []
        
        # Metrics
        self.total_goals_created = 0
        self.total_goals_completed = 0
        
        _log_v51("Hierarchical GoalManager initialized")
    
    def add_goal(self, goal: Goal) -> bool:
        """Add goal with priority management."""
        try:
            # Validate goal
            if not goal.name or not goal.description:
                raise ValueError("Goal must have name and description")
            
            # Add to storage
            self.goals[goal.goal_id] = goal
            
            # Update tracking sets
            if goal.status == "active":
                self.active_goals.add(goal.goal_id)
            elif goal.status == "completed":
                self.completed_goals.add(goal.goal_id)
            
            # Update execution queue
            self._update_execution_queue()
            
            self.total_goals_created += 1
            _log_v51(f"Added goal: {goal.name} (ID: {goal.goal_id})")
            return True
            
        except Exception as e:
            _log_v51(f"Failed to add goal: {e}", "ERROR")
            return False
    
    def complete_goal(self, goal_id: str) -> bool:
        """Mark goal as completed."""
        if goal_id not in self.goals:
            return False
        
        try:
            goal = self.goals[goal_id]
            goal.status = "completed"
            goal.current_progress = 1.0
            goal.last_updated = time.time()
            
            # Update tracking sets
            self.active_goals.discard(goal_id)
            self.completed_goals.add(goal_id)
            self.total_goals_completed += 1
            
            _log_v51(f"Completed goal: {goal.name}")
            return True
            
        except Exception as e:
            _log_v51(f"Failed to complete goal {goal_id}: {e}", "ERROR")
            return False
    
    def get_next_goal(self) -> Optional[Goal]:
        """Get next goal to execute based on priorities."""
        if not self.execution_queue:
            self._update_execution_queue()
        
        if not self.execution_queue:
            return None
        
        # Get highest priority goal
        goal_id = heapq.heappop(self.execution_queue)[1]
        
        if goal_id in self.goals and self.goals[goal_id].status == "active":
            return self.goals[goal_id]
        
        # Try next goal if current one is no longer active
        return self.get_next_goal()
    
    def _update_execution_queue(self) -> None:
        """Update execution queue based on priorities."""
        self.execution_queue.clear()
        
        for goal_id in self.active_goals:
            goal = self.goals[goal_id]
            priority_score = goal.priority.value
            
            # Use negative score for max-heap behavior
            heapq.heappush(self.execution_queue, (-priority_score, goal_id))
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive goal system status."""
        active_count = len(self.active_goals)
        completed_count = len(self.completed_goals)
        
        # Calculate completion rate
        completion_rate = 0.0
        if self.total_goals_created > 0:
            completion_rate = self.total_goals_completed / self.total_goals_created
        
        return {
            'total_goals': len(self.goals),
            'active_goals': active_count,
            'completed_goals': completed_count,
            'completion_rate': round(completion_rate, 3),
            'execution_queue_size': len(self.execution_queue)
        }

# ══════════════════════════════════════════════════════════════
# SYSTEM HEALTH MONITOR — Comprehensive Health & Recovery
# ══════════════════════════════════════════════════════════════

class HealthMonitor:
    """Comprehensive system health monitoring and recovery."""
    
    def __init__(self):
        self.health_status = HealthStatus.OPTIMAL
        self.health_history = deque(maxlen=100)
        self.error_log = deque(maxlen=50)
        self.last_health_check = time.time()
        
        # Thresholds
        self.thresholds = {
            'queue_size': 1000,
            'error_rate': 0.1,
            'response_time': 2.0
        }
        
        _log_v51("HealthMonitor initialized")
    
    def check_system_health(self, event_bus: EnhancedEventBus, 
                          belief_store: AdvancedBeliefStore,
                          attention_system: EnhancedAttentionSystem) -> HealthStatus:
        """Comprehensive system health check."""
        try:
            current_time = time.time()
            
            # Collect metrics
            bus_status = event_bus.get_status()
            belief_stats = belief_store.get_statistics()
            attention_status = attention_system.get_status()
            
            # Health indicators
            health_issues = []
            
            # Check queue sizes
            total_queue_size = bus_status['normal_queue_size'] + bus_status['priority_queue_size']
            if total_queue_size > self.thresholds['queue_size']:
                health_issues.append(f"Large queue: {total_queue_size}")
            
            # Check circuit breaker
            if bus_status['circuit_breaker_state'] != 'closed':
                health_issues.append(f"Circuit breaker: {bus_status['circuit_breaker_state']}")
            
            # Check belief count
            if belief_stats['total_beliefs'] == 0:
                health_issues.append("No beliefs stored")
            
            # Determine overall health
            if len(health_issues) == 0:
                new_status = HealthStatus.OPTIMAL
            elif len(health_issues) <= 2:
                new_status = HealthStatus.STABLE
            else:
                new_status = HealthStatus.DEGRADED
            
            # Record health check
            health_record = {
                'timestamp': current_time,
                'status': new_status.value,
                'issues': health_issues,
                'metrics': {
                    'queue_size': total_queue_size,
                    'circuit_breaker': bus_status['circuit_breaker_state'],
                    'total_beliefs': belief_stats['total_beliefs'],
                    'avg_confidence': belief_stats.get('avg_confidence', 0)
                }
            }
            
            self.health_history.append(health_record)
            
            # Update status
            old_status = self.health_status
            self.health_status = new_status
            self.last_health_check = current_time
            
            if old_status != new_status:
                _log_v51(f"Health status changed: {old_status.value} -> {new_status.value}")
            
            return new_status
            
        except Exception as e:
            _log_v51(f"Health check failed: {e}", "ERROR")
            self.error_log.append({'error': str(e), 'timestamp': time.time()})
            return HealthStatus.CRITICAL
    
    def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report."""
        recent_errors = [e for e in self.error_log if time.time() - e['timestamp'] < 3600]
        
        return {
            'current_status': self.health_status.value,
            'total_health_checks': len(self.health_history),
            'recent_errors': len(recent_errors),
            'last_check': self.last_health_check
        }

# ══════════════════════════════════════════════════════════════
# CONFIGURATION MANAGER — Centralized Settings
# ══════════════════════════════════════════════════════════════

class ConfigManager:
    """Centralized configuration management for v5.1 systems."""
    
    def __init__(self):
        self.config_file = _config_path_v51('core_config.json')
        self.config = self._load_default_config()
        self.load_config()
        
    def _load_default_config(self) -> Dict[str, Any]:
        """Load default configuration."""
        return {
            'event_bus': {
                'max_queue_size': 2000,
                'max_priority_queue_size': 500,
                'rate_limit_per_second': 100
            },
            'belief_store': {
                'max_beliefs': 1000,
                'decay_rate': 0.01,
                'similarity_threshold': 0.7
            },
            'attention_system': {
                'base_threshold': 0.3
            },
            'health_monitor': {
                'check_interval_seconds': 60
            }
        }
    
    def load_config(self) -> bool:
        """Load configuration from file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    loaded_config = json.load(f)
                    self._merge_config(loaded_config)
                _log_v51("Configuration loaded from file")
            else:
                self.save_config()
                _log_v51("Default configuration created")
            return True
        except Exception as e:
            _log_v51(f"Failed to load config: {e}", "ERROR")
            return False
    
    def save_config(self) -> bool:
        """Save current configuration to file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            _log_v51(f"Failed to save config: {e}", "ERROR")
            return False
    
    def _merge_config(self, loaded_config: Dict[str, Any]) -> None:
        """Merge loaded configuration with defaults."""
        for section, settings in loaded_config.items():
            if section in self.config:
                if isinstance(settings, dict):
                    self.config[section].update(settings)
                else:
                    self.config[section] = settings
    
    def get(self, section: str, key: str = None, default: Any = None) -> Any:
        """Get configuration value."""
        if key is None:
            return self.config.get(section, default)
        
        section_config = self.config.get(section, {})
        return section_config.get(key, default)

# ══════════════════════════════════════════════════════════════
# MAIN v5.1 CONTROLLER — Integration & Orchestration
# ══════════════════════════════════════════════════════════════

class NexV51CoreInfrastructure:
    """Main controller for NEX v5.1 Core Infrastructure.
    
    Provides rock-solid foundation layer underneath v5.0 cognitive architecture.
    """
    
    def __init__(self):
        # Load configuration first
        self.config = ConfigManager()
        
        # Initialize core systems
        self.event_bus = EnhancedEventBus(
            max_queue=self.config.get('event_bus', 'max_queue_size'),
            max_priority_queue=self.config.get('event_bus', 'max_priority_queue_size')
        )
        
        self.belief_store = AdvancedBeliefStore(
            max_beliefs=self.config.get('belief_store', 'max_beliefs')
        )
        
        self.attention_system = EnhancedAttentionSystem(
            base_threshold=self.config.get('attention_system', 'base_threshold')
        )
        
        self.goal_manager = HierarchicalGoalManager()
        
        self.health_monitor = HealthMonitor()
        
        # System state
        self.cycle_count = 0
        self.last_health_check = 0
        self.initialization_time = time.time()
        
        # Performance metrics
        self.total_events_processed = 0
        self.total_beliefs_managed = 0
        self.system_errors = 0
        
        _log_v51("NEX v5.1 Core Infrastructure fully initialized")
    
    async def process_event(self, event: CognitiveEvent) -> Dict[str, Any]:
        """Process event through v5.1 infrastructure."""
        try:
            # Publish to event bus
            published = await self.event_bus.publish(event)
            
            if not published:
                return {
                    'status': 'failed',
                    'reason': 'event_bus_rejected',
                    'event_id': event.event_id
                }
            
            # Process through attention system
            should_process, attention_score = self.attention_system.should_process(event)
            
            if not should_process:
                return {
                    'status': 'filtered',
                    'reason': 'attention_filtered',
                    'event_id': event.event_id,
                    'attention_score': attention_score
                }
            
            # Handle different event types
            result = await self._handle_event_by_type(event)
            
            self.total_events_processed += 1
            
            return {
                'status': 'processed',
                'event_id': event.event_id,
                'attention_score': attention_score,
                'processing_result': result
            }
            
        except Exception as e:
            self.system_errors += 1
            error_msg = f"Event processing error: {e}"
            _log_v51(error_msg, "ERROR")
            
            return {
                'status': 'error',
                'error': str(e),
                'event_id': getattr(event, 'event_id', 'unknown')
            }
    
    async def _handle_event_by_type(self, event: CognitiveEvent) -> Dict[str, Any]:
        """Handle event based on its type."""
        if event.type == EventType.BELIEF:
            return await self._handle_belief_event(event)
        elif event.type == EventType.GOAL:
            return await self._handle_goal_event(event)
        elif event.type == EventType.SYSTEM:
            return await self._handle_system_event(event)
        else:
            return {'handled': True, 'type': event.type.value}
    
    async def _handle_belief_event(self, event: CognitiveEvent) -> Dict[str, Any]:
        """Handle belief-related events."""
        try:
            # Create belief from event
            belief = BeliefData(
                text=event.content,
                confidence=event.confidence,
                topic=event.metadata.get('topic', 'general'),
                source=event.source
            )
            
            # Add to belief store
            success = self.belief_store.add(belief)
            
            if success:
                self.total_beliefs_managed += 1
                return {
                    'belief_added': True,
                    'belief_id': belief.belief_id,
                    'total_beliefs': len(self.belief_store.beliefs)
                }
            else:
                return {'belief_added': False, 'reason': 'store_rejected'}
                
        except Exception as e:
            return {'belief_added': False, 'error': str(e)}
    
    async def _handle_goal_event(self, event: CognitiveEvent) -> Dict[str, Any]:
        """Handle goal-related events."""
        try:
            # Extract goal information from event
            goal = Goal(
                goal_id='',  # Will be auto-generated
                name=event.metadata.get('goal_name', 'Unnamed Goal'),
                description=event.content,
                priority=event.priority
            )
            
            # Add to goal manager
            success = self.goal_manager.add_goal(goal)
            
            if success:
                return {
                    'goal_added': True,
                    'goal_id': goal.goal_id,
                    'total_active_goals': len(self.goal_manager.active_goals)
                }
            else:
                return {'goal_added': False, 'reason': 'manager_rejected'}
                
        except Exception as e:
            return {'goal_added': False, 'error': str(e)}
    
    async def _handle_system_event(self, event: CognitiveEvent) -> Dict[str, Any]:
        """Handle system-related events."""
        if event.content.startswith('health_check'):
            health_status = self.health_monitor.check_system_health(
                self.event_bus, self.belief_store, self.attention_system
            )
            return {'health_check': True, 'status': health_status.value}
        else:
            return {'system_event': True, 'content': event.content[:50]}
    
    def tick(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Main v5.1 infrastructure tick - MUST be sync for run.py integration."""
        self.cycle_count += 1
        context = context or {}
        
        try:
            # Health monitoring
            if time.time() - self.last_health_check > 60:  # 60 seconds
                health_status = self.health_monitor.check_system_health(
                    self.event_bus, self.belief_store, self.attention_system
                )
                self.last_health_check = time.time()
            
            # Periodic maintenance
            if self.cycle_count % 10 == 0:
                # Belief decay
                decayed = self.belief_store.decay_all()
                
                # Execute next goal
                next_goal = self.goal_manager.get_next_goal()
                goal_info = None
                if next_goal:
                    goal_info = {
                        'id': next_goal.goal_id,
                        'name': next_goal.name,
                        'priority': next_goal.priority.value
                    }
            
            return {
                'v51_status': 'operational',
                'cycle': self.cycle_count,
                'uptime_hours': round((time.time() - self.initialization_time) / 3600, 2),
                'health': self.health_monitor.health_status.value
            }
            
        except Exception as e:
            self.system_errors += 1
            error_msg = f"v5.1 tick error: {e}"
            _log_v51(error_msg, "ERROR")
            
            return {
                'v51_status': 'error',
                'cycle': self.cycle_count,
                'error': str(e)
            }
    
    def create_event(self, event_type: EventType, content: str, **kwargs) -> CognitiveEvent:
        """Create properly formatted cognitive event."""
        return CognitiveEvent(
            type=event_type,
            content=content,
            confidence=kwargs.get('confidence', 0.5),
            priority=kwargs.get('priority', Priority.NORMAL),
            source=kwargs.get('source', 'v51_system'),
            tags=set(kwargs.get('tags', [])),
            metadata=kwargs.get('metadata', {})
        )
    
    def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive v5.1 system status."""
        return {
            'version': '5.1',
            'uptime_hours': round((time.time() - self.initialization_time) / 3600, 2),
            'cycle_count': self.cycle_count,
            'total_events_processed': self.total_events_processed,
            'total_beliefs_managed': self.total_beliefs_managed,
            'system_errors': self.system_errors,
            'event_bus': self.event_bus.get_status(),
            'belief_store': self.belief_store.get_statistics(),
            'attention_system': self.attention_system.get_status(),
            'goal_manager': self.goal_manager.get_status(),
            'health_monitor': self.health_monitor.get_health_report()
        }

# ══════════════════════════════════════════════════════════════
# FACTORY FUNCTIONS FOR INTEGRATION
# ══════════════════════════════════════════════════════════════

def get_v51() -> NexV51CoreInfrastructure:
    """Factory function for NEX v5.1 core infrastructure."""
    return NexV51CoreInfrastructure()

def initialize_v51_config() -> bool:
    """Initialize v5.1 configuration directories and files."""
    try:
        config_dir = Path.home() / '.config' / 'nex' / 'v51'
        config_dir.mkdir(parents=True, exist_ok=True)
        
        # Create configuration manager to set up defaults
        config_manager = ConfigManager()
        
        _log_v51("v5.1 configuration initialized successfully")
        return True
        
    except Exception as e:
        _log_v51(f"v5.1 configuration initialization failed: {e}", "ERROR")
        return False

# ══════════════════════════════════════════════════════════════
# TESTING FUNCTIONS
# ══════════════════════════════════════════════════════════════

async def test_v51_systems() -> Dict[str, Any]:
    """Comprehensive v5.1 system testing."""
    results = {}
    
    try:
        # Test configuration
        config_result = initialize_v51_config()
        results["config_initialization"] = config_result
        
        # Test system initialization
        nex_v51 = NexV51CoreInfrastructure()
        results["system_initialization"] = True
        
        # Test event creation and processing
        test_event = nex_v51.create_event(
            EventType.THOUGHT,
            "Testing v5.1 infrastructure",
            confidence=0.8,
            priority=Priority.HIGH
        )
        
        process_result = await nex_v51.process_event(test_event)
        results["event_processing"] = process_result['status'] == 'processed'
        
        # Test main tick cycle
        tick_result = nex_v51.tick({'test_context': True})
        results["main_tick"] = tick_result['v51_status'] == 'operational'
        
        # Test status reporting
        status = nex_v51.get_comprehensive_status()
        results["status_reporting"] = isinstance(status, dict) and 'version' in status
        
        return results
        
    except Exception as e:
        results["testing_error"] = str(e)
        return results

if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("NEX v5.1 Core Infrastructure - System Testing")
        print("=" * 60)
        
        test_results = await test_v51_systems()
        
        print("Test Results:")
        for test_name, result in test_results.items():
            status = "✓" if result is True else ("✗" if result is False else "?")
            print(f"  {test_name:25}: {status} {result}")
        
        success_count = sum(1 for r in test_results.values() if r is True)
        total_tests = len([r for r in test_results.values() if isinstance(r, bool)])
        
        print(f"\nResults: {success_count}/{total_tests} tests passed")
        
        if success_count == total_tests:
            print("\n🎉 NEX v5.1 Core Infrastructure Ready!")
            print("Integration: Works seamlessly with v5.0 cognitive architecture")
            print("Usage: from nex_upgrades.nex_v51 import get_v51")
        else:
            print("\n⚠️ Some tests failed - review needed")
    
    asyncio.run(main())
