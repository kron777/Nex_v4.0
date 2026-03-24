"""
restore_beliefs.py — Restore beliefs from backup DB
Run: python3 restore_beliefs.py
"""
import sqlite3
import os

CURRENT_DB = os.path.expanduser("~/.config/nex/nex.db")
BACKUP_DB  = os.path.expanduser("~/.config/nex/backups/nex_pre_migration_1773008598.db")

print(f"Current DB: {CURRENT_DB}")
print(f"Backup DB:  {BACKUP_DB}")

# Connect to both
backup = sqlite3.connect(BACKUP_DB)
backup.row_factory = sqlite3.Row
current = sqlite3.connect(CURRENT_DB)

# Ensure energy column exists in current
try:
    current.execute("ALTER TABLE beliefs ADD COLUMN energy REAL DEFAULT 100.0")
    current.commit()
    print("Added energy column")
except Exception:
    pass  # already exists

# Get all beliefs from backup
print("Loading backup beliefs...")
backup_beliefs = backup.execute("""
    SELECT content, confidence, network_consensus, source, author,
           timestamp, last_referenced, decay_score, human_validated,
           tags, topic, origin
    FROM beliefs
""").fetchall()
print(f"Backup has {len(backup_beliefs)} beliefs")

# Get existing content in current DB
print("Loading current content fingerprints...")
existing = set(
    r[0] for r in current.execute("SELECT content FROM beliefs WHERE content IS NOT NULL").fetchall()
)
print(f"Current DB has {len(existing)} beliefs")

# Find missing ones
missing = [b for b in backup_beliefs if (b['content'] or '') not in existing]
print(f"Missing from current: {len(missing)}")

if not missing:
    print("Nothing to restore — all backup beliefs already present by content.")
    print("The UNIQUE constraint is working but rows were physically deleted.")
    print("\nForcing vacuum + recount...")
    current.execute("VACUUM")
    count = current.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    print(f"After vacuum: {count} beliefs")
else:
    # Insert missing beliefs in batches
    print(f"Restoring {len(missing)} beliefs...")
    batch_size = 500
    restored = 0
    for i in range(0, len(missing), batch_size):
        batch = missing[i:i+batch_size]
        current.executemany("""
            INSERT OR IGNORE INTO beliefs
            (content, confidence, network_consensus, source, author,
             timestamp, last_referenced, decay_score, human_validated,
             tags, topic, origin, energy)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,100.0)
        """, [
            (b['content'], b['confidence'], b['network_consensus'],
             b['source'], b['author'], b['timestamp'], b['last_referenced'],
             b['decay_score'], b['human_validated'], b['tags'],
             b['topic'], b['origin'])
            for b in batch
        ])
        current.commit()
        restored += len(batch)
        print(f"  Restored {restored}/{len(missing)}...")

    final_count = current.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    print(f"\nDone. Final belief count: {final_count}")

backup.close()
current.close()
