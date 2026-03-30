class SourceRouter:
    """Simplistic Router: Only separates high-logic from standard chat."""
    def route(self, text):
        t = text.lower().strip()
        if any(w in t for w in ["why", "how", "logic", "conflict", "audit"]):
            return "DEEP_THINK"
        return "CHAT"
