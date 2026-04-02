"""
nex_world_model.py
Lightweight dynamic world model for NEX.
Tracks entities and their properties from conversations.
Grounds factual claims against belief graph.
"""
import sqlite3, json, time, logging
from pathlib import Path

log     = logging.getLogger("nex.world")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

class WorldModel:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS world_state (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entity     TEXT NOT NULL,
            property   TEXT NOT NULL,
            value      TEXT NOT NULL,
            confidence REAL DEFAULT 0.7,
            source     TEXT DEFAULT 'conversation',
            timestamp  REAL,
            UNIQUE(entity, property)
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS 
            idx_world_entity ON world_state(entity)""")
        self.db.commit()

    def update(self, entity: str, property: str, value: str,
               confidence=0.7, source="conversation"):
        """Insert or update an entity property."""
        entity   = entity.lower().strip()
        property = property.lower().strip()
        existing = self.db.execute(
            "SELECT confidence FROM world_state WHERE entity=? AND property=?",
            (entity, property)).fetchone()
        if existing:
            # Only update if new confidence is higher
            if confidence >= existing["confidence"]:
                self.db.execute("""UPDATE world_state 
                    SET value=?, confidence=?, source=?, timestamp=?
                    WHERE entity=? AND property=?""",
                    (value, confidence, source, time.time(), entity, property))
        else:
            self.db.execute("""INSERT INTO world_state
                (entity, property, value, confidence, source, timestamp)
                VALUES (?,?,?,?,?,?)""",
                (entity, property, value, confidence, source, time.time()))
        self.db.commit()

    def get(self, entity: str) -> dict:
        """Get all known properties of an entity."""
        rows = self.db.execute(
            "SELECT property, value, confidence FROM world_state WHERE entity=?",
            (entity.lower(),)).fetchall()
        return {r["property"]: {"value": r["value"], "confidence": r["confidence"]}
                for r in rows}

    def check_contradiction(self, entity: str, property: str, value: str) -> bool:
        """Returns True if value contradicts known world state."""
        existing = self.db.execute(
            "SELECT value FROM world_state WHERE entity=? AND property=? AND confidence > 0.6",
            (entity.lower(), property.lower())).fetchone()
        if existing and existing["value"].lower() != value.lower():
            return True
        return False

    def extract_and_update(self, text: str, source="conversation"):
        """
        Simple pattern-based entity extraction from text.
        Looks for: 'X is Y', 'X has Y', 'X was Y'
        """
        import re
        patterns = [
            r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+is\s+([^,.]+)',
            r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+was\s+([^,.]+)',
            r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+has\s+([^,.]+)',
        ]
        extracted = []
        for pat in patterns:
            for m in re.finditer(pat, text):
                entity = m.group(1).strip()
                value  = m.group(2).strip()[:100]
                if len(entity) > 2 and len(value) > 2:
                    self.update(entity, "description", value,
                                confidence=0.6, source=source)
                    extracted.append((entity, value))
        return extracted

    def prompt_block(self, entity: str) -> str:
        """Format known facts about entity for prompt injection."""
        facts = self.get(entity)
        if not facts:
            return ""
        lines = [f"KNOWN FACTS about {entity}:"]
        for prop, data in list(facts.items())[:5]:
            lines.append(f"  {prop}: {data['value']} (conf={data['confidence']:.2f})")
        return "\n".join(lines)

    def stats(self):
        total    = self.db.execute("SELECT COUNT(*) FROM world_state").fetchone()[0]
        entities = self.db.execute(
            "SELECT COUNT(DISTINCT entity) FROM world_state").fetchone()[0]
        return {"total_facts": total, "entities": entities}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    wm = WorldModel()

    # Seed some world facts
    wm.update("NEX", "type", "Dynamic Intelligence Organism", confidence=1.0, source="seed")
    wm.update("NEX", "model", "Qwen2.5-3B-Instruct fine-tuned", confidence=1.0, source="seed")
    wm.update("NEX", "belief_count", "20530", confidence=0.9, source="seed")
    wm.update("NEX", "eval_score", "100/100 ELITE", confidence=0.95, source="seed")
    wm.update("llama-server", "port", "8080", confidence=1.0, source="seed")
    wm.update("llama-server", "model", "nex_v2.gguf", confidence=1.0, source="seed")

    print("Stats:", wm.stats())
    print("\nNEX facts:")
    for k,v in wm.get("NEX").items():
        print(f"  {k}: {v['value']}")

    # Test extraction
    extracted = wm.extract_and_update(
        "Consciousness is the hard problem. Qualia are irreducible.")
    print(f"\nExtracted: {extracted}")

    # Test contradiction check
    print("\nContradiction check (NEX port=9999):",
          wm.check_contradiction("llama-server", "port", "9999"))
