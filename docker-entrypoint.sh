#!/bin/bash
set -e

# Ensure unbuffered output for real-time logs
export PYTHONUNBUFFERED=1

# Link config if mounted
if [ -f /app/config/config.json ]; then
    ln -sf /app/config/config.json /app/config.json
    echo "Config file linked successfully"
else
    echo "WARNING: No config.json found at /app/config/config.json"
fi

# Start the viewer in the background
echo "Starting web viewer on port 8080..."
python -u viewer.py --host 0.0.0.0 --port 8080 &
VIEWER_PID=$!

# Give viewer time to start
sleep 2

# Cleanup on exit
trap "kill $VIEWER_PID 2>/dev/null" EXIT

# Run the monitor in watch mode (or custom command if provided)
if [ $# -eq 0 ]; then
    echo "Starting monitor in watch mode (interval: ${SYNC_INTERVAL:-120} minutes)..."
    exec python -u tiktok_monitor.py --watch --interval "${SYNC_INTERVAL:-120}"
else
    exec "$@"
fi
