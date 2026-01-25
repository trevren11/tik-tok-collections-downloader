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

# Run the monitor in watch mode (or custom command if provided)
if [ $# -eq 0 ]; then
    echo "Starting monitor in watch mode (interval: ${SYNC_INTERVAL:-120} minutes)..."

    # Check if viewer is enabled
    if [ "${ENABLE_VIEWER:-false}" = "true" ]; then
        VIEWER_PORT="${VIEWER_PORT:-8425}"
        echo "Web viewer enabled on port ${VIEWER_PORT}"
        # Start HTTP server in background serving the downloads directory
        cd /app/downloads && python -m http.server "${VIEWER_PORT}" &
        cd /app
    fi

    exec python -u tiktok_monitor.py --watch --interval "${SYNC_INTERVAL:-120}"
else
    exec "$@"
fi
