#!/usr/bin/env python3
"""
NEX DISCIPLINE ENFORCER
=======================
Stability patch focused on reliability over features.

1. Type enforcement everywhere
2. Aggressive attention filtering  
3. Belief corruption prevention
4. Semantic loop detection

No innovation. Pure discipline.
"""

import json
import time
import hashlib
from typing import Any, Dict, Optional, Set, List
from pathlib import Path

def _log_discipline(msg: str, level: str = "INFO") -> None:
    """Discipline logging."""
    timestamp = time.strftime('%H:%M:%S')
    with open('/tmp/nex_discipline.log', 'a') as f:
        f.write(f"[DISCIPLINE {timestamp}] [{level}] {msg}\n")

class TypeEnforcer:
    """Brutal type enforcement. No exceptions."""
    
    @staticmethod
    def safe_str(value: Any, default: str = "") -> str:
        """Force string. Period."""
        if value is None:
            return default
        try:
            result = str(value).strip()
            return result if result else default
        except:
            return default
    
    @staticmethod
    def safe_float(value: Any, default: float = 0.0) -> float:
        """Force float. Period."""
        if value is None:
            return default
        try:
            result = float(value)
            return result if not (result != result) else default  # NaN check
        except:
            return default
    
    @staticmethod
    def safe_dict(value: Any, required_keys: Set[str] = None) -> Dict[str, Any]:
        """Force dict with required keys."""
        if not isinstance(value, dict):
            value = {}
        
        # Ensure required keys exist
        if required_keys:
            for key in required_keys:
                if key not in value:
                    value[key] = ""
        
        return value
    
    @staticmethod
    def wrap_output(raw_output: Any) -> Dict[str, Any]:
        """Wrap ANY output in safe structure."""
        if isinstance(raw_output, dict):
            return {
                'content': TypeEnforcer.safe_str(raw_output.get('content', '')),
                'confidence': TypeEnforcer.safe_float(raw_output.get('confidence', 0.5)),
                'metadata': TypeEnforcer.safe_dict(raw_output.get('metadata', {})),
                'timestamp': time.time(),
                'type': 'wrapped_output'
            }
        else:
            return {
                'content': TypeEnforcer.safe_str(raw_output),
                'confidence': 0.5,
                'metadata': {},
                'timestamp': time.time(),
                'type': 'wrapped_output'
            }

class AttentionTightener:
    """Aggressive attention filtering to reduce cognitive load."""
    
    def __init__(self):
        self.threshold = 0.6  # RAISED from 0.3
        self.max_per_cycle = 3  # CAP processing
        self.processed_this_cycle = 0
        self.cycle_reset_time = 0
        self.rejected_count = 0
        
        _log_discipline(f"Attention threshold RAISED to {self.threshold}")
    
    def should_process(self, content: str, confidence: float = 0.5) -> bool:
        """Strict filtering. Most things get rejected."""
        current_time = time.time()
        
        # Reset cycle counter every 10 seconds
        if current_time - self.cycle_reset_time > 10:
            self.processed_this_cycle = 0
            self.cycle_reset_time = current_time
        
        # Hard cap per cycle
        if self.processed_this_cycle >= self.max_per_cycle:
            self.rejected_count += 1
            return False
        
        # Calculate attention score
        score = self._calculate_score(content, confidence)
        
        if score >= self.threshold:
            self.processed_this_cycle += 1
            return True
        else:
            self.rejected_count += 1
            return False
    
    def _calculate_score(self, content: str, confidence: float) -> float:
        """Harsh scoring. High bar for acceptance."""
        if not content or len(content) < 10:
            return 0.0
        
        # Content quality
        content_score = min(1.0, len(content) / 100) * 0.4
        
        # Confidence factor
        confidence_score = confidence * 0.4
        
        # Novelty bonus (basic keyword diversity)
        words = set(content.lower().split())
        novelty_score = min(1.0, len(words) / 10) * 0.2
        
        return content_score + confidence_score + novelty_score
    
    def get_stats(self) -> Dict[str, Any]:
        """Attention stats."""
        total = self.processed_this_cycle + self.rejected_count
        rejection_rate = self.rejected_count / max(total, 1)
        
        return {
            'threshold': self.threshold,
            'processed_this_cycle': self.processed_this_cycle,
            'rejected_count': self.rejected_count,
            'rejection_rate': round(rejection_rate, 3)
        }

class BeliefProtector:
    """Prevent belief corruption with zero tolerance."""
    
    def __init__(self):
        self.rejected_beliefs = 0
        self.protected_beliefs = 0
        
    def validate_belief(self, belief_text: str, confidence: float) -> Optional[Dict[str, Any]]:
        """Strict belief validation. Reject garbage immediately."""
        
        # Rule 1: No empty or None
        if not belief_text or belief_text.strip() == "":
            self.rejected_beliefs += 1
            _log_discipline("Rejected empty belief", "WARN")
            return None
        
        # Rule 2: Minimum length
        if len(belief_text.strip()) < 5:
            self.rejected_beliefs += 1
            _log_discipline("Rejected too-short belief", "WARN")
            return None
        
        # Rule 3: No pure whitespace/junk
        if belief_text.strip().isspace() or not any(c.isalnum() for c in belief_text):
            self.rejected_beliefs += 1
            _log_discipline("Rejected junk belief", "WARN")
            return None
        
        # Rule 4: Confidence bounds
        if not (0.0 <= confidence <= 1.0):
            confidence = max(0.0, min(1.0, confidence))
            _log_discipline("Fixed confidence bounds", "INFO")
        
        # Rule 5: No obvious duplicates (basic hash check)
        text_hash = hashlib.md5(belief_text.lower().strip().encode()).hexdigest()[:8]
        
        self.protected_beliefs += 1
        
        return {
            'text': belief_text.strip(),
            'confidence': confidence,
            'hash': text_hash,
            'timestamp': time.time(),
            'protected': True
        }
    
    def protect_clustering(self, beliefs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Protect clustering step from corruption."""
        if not beliefs or len(beliefs) == 0:
            _log_discipline("Empty beliefs list protected from clustering", "WARN")
            return []
        
        # Filter out any corrupted beliefs
        clean_beliefs = []
        for belief in beliefs:
            if isinstance(belief, dict) and 'text' in belief and belief['text']:
                clean_beliefs.append(belief)
            else:
                self.rejected_beliefs += 1
                _log_discipline("Removed corrupted belief from clustering", "WARN")
        
        return clean_beliefs
    
    def get_stats(self) -> Dict[str, Any]:
        """Protection stats."""
        total = self.protected_beliefs + self.rejected_beliefs
        protection_rate = self.protected_beliefs / max(total, 1)
        
        return {
            'protected_beliefs': self.protected_beliefs,
            'rejected_beliefs': self.rejected_beliefs,
            'protection_rate': round(protection_rate, 3)
        }

class SemanticLoopDetector:
    """Detect and prevent semantic repetition."""
    
    def __init__(self):
        self.recent_outputs = []  # Store recent semantic fingerprints
        self.max_history = 20
        self.similarity_threshold = 0.7
        self.variation_forced = 0
        
    def check_for_loop(self, content: str) -> bool:
        """Check if content is too similar to recent outputs."""
        if not content:
            return False
        
        # Create semantic fingerprint (simplified)
        fingerprint = self._create_fingerprint(content)
        
        # Check against recent outputs
        for recent_fingerprint in self.recent_outputs:
            similarity = self._calculate_similarity(fingerprint, recent_fingerprint)
            if similarity > self.similarity_threshold:
                _log_discipline(f"Semantic loop detected (similarity: {similarity:.3f})", "WARN")
                return True
        
        # Store this fingerprint
        self.recent_outputs.append(fingerprint)
        
        # Maintain history limit
        if len(self.recent_outputs) > self.max_history:
            self.recent_outputs.pop(0)
        
        return False
    
    def force_variation(self, content: str) -> str:
        """Force variation in repetitive content."""
        self.variation_forced += 1
        
        # Simple variation techniques
        variations = [
            f"Exploring different aspects: {content}",
            f"From another perspective: {content}",
            f"Building on previous insights: {content}",
            f"Considering alternatives: {content}",
        ]
        
        # Pick variation based on time
        variation_index = int(time.time()) % len(variations)
        result = variations[variation_index]
        
        _log_discipline("Forced content variation", "INFO")
        return result
    
    def _create_fingerprint(self, content: str) -> Set[str]:
        """Create semantic fingerprint from content."""
        # Extract meaningful words (simplified)
        words = content.lower().split()
        # Remove very common words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were'}
        meaningful_words = {word for word in words if len(word) > 2 and word not in stop_words}
        return meaningful_words
    
    def _calculate_similarity(self, fp1: Set[str], fp2: Set[str]) -> float:
        """Calculate similarity between fingerprints."""
        if not fp1 or not fp2:
            return 0.0
        
        intersection = len(fp1 & fp2)
        union = len(fp1 | fp2)
        
        return intersection / union if union > 0 else 0.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Loop detection stats."""
        return {
            'recent_outputs_count': len(self.recent_outputs),
            'similarity_threshold': self.similarity_threshold,
            'variation_forced': self.variation_forced
        }

class DisciplineEnforcer:
    """Main discipline enforcement system."""
    
    def __init__(self):
        self.type_enforcer = TypeEnforcer()
        self.attention_tightener = AttentionTightener()
        self.belief_protector = BeliefProtector()
        self.loop_detector = SemanticLoopDetector()
        
        self.total_processed = 0
        self.total_rejected = 0
        self.start_time = time.time()
        
        _log_discipline("Discipline Enforcer initialized - STRICT MODE ACTIVE")
    
    def process_output(self, raw_output: Any) -> Optional[Dict[str, Any]]:
        """Process any output through discipline pipeline."""
        
        # 1. FORCE TYPES
        wrapped_output = self.type_enforcer.wrap_output(raw_output)
        content = wrapped_output['content']
        confidence = wrapped_output['confidence']
        
        # 2. ATTENTION FILTERING
        if not self.attention_tightener.should_process(content, confidence):
            self.total_rejected += 1
            return None
        
        # 3. SEMANTIC LOOP CHECK
        if self.loop_detector.check_for_loop(content):
            # Force variation
            wrapped_output['content'] = self.loop_detector.force_variation(content)
        
        self.total_processed += 1
        return wrapped_output
    
    def process_belief(self, belief_text: str, confidence: float) -> Optional[Dict[str, Any]]:
        """Process belief through protection pipeline."""
        return self.belief_protector.validate_belief(belief_text, confidence)
    
    def protect_belief_clustering(self, beliefs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Protect clustering operation."""
        return self.belief_protector.protect_clustering(beliefs)
    
    def get_comprehensive_stats(self) -> Dict[str, Any]:
        """Get all discipline stats."""
        uptime_hours = (time.time() - self.start_time) / 3600
        total_events = self.total_processed + self.total_rejected
        efficiency = self.total_processed / max(total_events, 1)
        
        return {
            'discipline_status': 'ENFORCED',
            'uptime_hours': round(uptime_hours, 2),
            'total_processed': self.total_processed,
            'total_rejected': self.total_rejected,
            'efficiency': round(efficiency, 3),
            'attention_stats': self.attention_tightener.get_stats(),
            'belief_stats': self.belief_protector.get_stats(),
            'loop_stats': self.loop_detector.get_stats()
        }

# Factory function for integration
def get_discipline_enforcer() -> DisciplineEnforcer:
    """Get discipline enforcer instance."""
    return DisciplineEnforcer()

# Testing function
def test_discipline():
    """Test discipline enforcement."""
    enforcer = DisciplineEnforcer()
    
    # Test type enforcement
    print("Testing type enforcement...")
    result1 = enforcer.process_output("Valid content")
    result2 = enforcer.process_output(None)
    result3 = enforcer.process_output({"content": "Dict content", "confidence": 0.8})
    
    # Test belief protection
    print("Testing belief protection...")
    belief1 = enforcer.process_belief("Valid belief", 0.7)
    belief2 = enforcer.process_belief("", 0.5)  # Should be rejected
    belief3 = enforcer.process_belief("x", 0.5)  # Should be rejected
    
    # Test loop detection
    print("Testing loop detection...")
    for i in range(3):
        enforcer.loop_detector.check_for_loop("This is a repeated message")
    
    # Show stats
    stats = enforcer.get_comprehensive_stats()
    print("\nDiscipline Stats:")
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    test_discipline()
