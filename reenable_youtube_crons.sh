#!/bin/bash
# Run this after 2026-04-13 16:17 to re-enable YouTube scrapers
(crontab -l 2>/dev/null; echo "0 * * * * cd /home/rr/Desktop/nex && source venv/bin/activate && python3 -c \"import sys; sys.path.insert(0,'.'); from nex_ws import emit_youtube_beliefs; emit_youtube_beliefs(50)\" >> /tmp/yt_inject.log 2>&1") | crontab -
echo "✓ YouTube crons re-enabled"
echo "Rate limits: 3 videos/run, 60s between each"
