#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Start the web dashboard server
#  Access from any machine: http://<server-ip>:5000
# ═══════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! python3 -c "import flask" 2>/dev/null; then
    pip3 install -r requirements.txt --quiet
fi

echo ""
echo "  Starting DM-NAX Test Dashboard..."
echo "  URL: http://$(hostname -I | awk '{print $1}'):5000"
echo "  Press Ctrl+C to stop"
echo ""

python3 dashboard.py
