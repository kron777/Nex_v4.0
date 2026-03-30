import subprocess

class CharacterEngine:
    """Refined Character Engine: No hardcoded templates. Direct LLM Control."""
    
    def respond(self, query):
        # We call Ollama directly to get raw, intelligent responses
        # instead of wrapping them in broken "bridge" templates.
        try:
            cmd = ["ollama", "run", "mistral", query] # Or your preferred model
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return result.stdout.strip()
        except Exception as e:
            return f"I am experiencing a cognitive block: {str(e)}"

    def think(self, trigger):
        # The 'Internal Monologue' or System 2 audit
        return self.respond(f"Analyze this deeply: {trigger}")
