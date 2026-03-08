#!/bin/bash
# Run NEX test suite
cd "$(dirname "$0")"
source venv/bin/activate
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  NEX TEST SUITE                      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
python3 -m pytest tests/ -v --tb=short 2>&1 || python3 -m unittest discover -s tests -v
