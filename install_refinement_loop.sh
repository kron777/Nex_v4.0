#!/bin/bash
# install_refinement_loop.sh
# Installs the refinement loop as a systemd service that starts on boot

set -e
NEX=/home/rr/Desktop/nex

echo "Installing NEX refinement loop..."
sudo cp $NEX/nex_refinement_loop.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nex-refinement-loop
sudo systemctl start nex-refinement-loop
sudo systemctl status nex-refinement-loop

echo ""
echo "Refinement loop is running. Monitor with:"
echo "  tail -f $NEX/logs/refinement_loop.log"
echo "  sudo systemctl status nex-refinement-loop"
