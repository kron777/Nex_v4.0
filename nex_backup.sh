#!/bin/bash
# NEX DB nightly backup — preserves her mind
LIVE="/home/rr/Desktop/nex/nex.db"
BACKUP_DIR="/media/rr/NEX/backups"
mkdir -p "$BACKUP_DIR"

# Keep last 7 daily backups
STAMP=$(date +%Y%m%d_%H%M)
cp "$LIVE" "$BACKUP_DIR/nex_${STAMP}.db"

# Delete backups older than 7 days
find "$BACKUP_DIR" -name "nex_*.db" -mtime +7 -delete

echo "[backup] $(date) — nex.db backed up to $BACKUP_DIR/nex_${STAMP}.db ($(du -h $LIVE | cut -f1))"
