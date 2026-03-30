class FactDistiller:
    """Extracts symbolic beliefs from raw neural strings."""
    def distill(self, text):
        # Simplified symbolic extractor
        concepts = [w for w in text.split() if len(w) > 5]
        return [{"subject": "user_intent", "predicate": "discusses", "object": c} for c in concepts[:3]]
