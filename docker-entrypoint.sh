#!/bin/bash
set -e

# Link config if mounted
if [ -f /app/config/config.json ]; then
    ln -sf /app/config/config.json /app/config.json
fi

# Start the viewer in the background
echo "Starting web viewer on port 8080..."
python viewer.py --host 0.0.0.0 --port 8080 &
VIEWER_PID=$!

# Give viewer time to start
sleep 2

# Run the monitor in watch mode (or custom command if provided)
if [ $# -eq 0 ]; then
    echo "Starting monitor in watch mode..."
    python tiktok_monitor.py --watch --interval "${SYNC_INTERVAL:-60}"
else
    exec "$@"
fi

# Cleanup on exit
trap "kill $VIEWER_PID 2>/dev/null" EXIT
