#!/bin/bash
set -e

# Ensure unbuffered output for real-time logs
export PYTHONUNBUFFERED=1

# Link config if mounted
if [ -f /app/config/config.json ]; then
    ln -sf /app/config/config.json /app/config.json
    echo "Config file linked successfully"
elif [ -n "$TIKTOK_SESSION_ID" ]; then
    # Generate config.json from environment variables
    echo "Generating config.json from environment variables..."
    cat > /app/config.json << EOF
{
    "sessionid": "$TIKTOK_SESSION_ID",
    "download_dir": "${DOWNLOAD_DIR:-/app/downloads}"
}
EOF
    echo "Config generated from TIKTOK_SESSION_ID"
else
    echo "ERROR: No config.json found and TIKTOK_SESSION_ID not set"
    echo "Either mount a config.json or set the TIKTOK_SESSION_ID environment variable"
    exit 1
fi

# Start the viewer server in the background
VIEWER_PORT="${VIEWER_PORT:-2507}"
echo "Starting viewer server on port ${VIEWER_PORT}..."
python -u viewer.py -p "${VIEWER_PORT}" -d /app/downloads &
VIEWER_PID=$!
echo "Viewer server started (PID: $VIEWER_PID)"

# Handle shutdown gracefully
cleanup() {
    echo "Shutting down..."
    kill $VIEWER_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# Build command arguments
CMD_ARGS=""

# Add --full-sync if enabled
if [ "${FULL_SYNC:-false}" = "true" ]; then
    CMD_ARGS="$CMD_ARGS --full-sync"
    echo "Full sync mode enabled"
fi

# Run the monitor in watch mode (or custom command if provided)
if [ $# -eq 0 ]; then
    # Check if we should fetch all favorites first (one-time operation)
    if [ "${FETCH_ALL_FAVORITES:-false}" = "true" ]; then
        echo "Fetching ALL favorites first (this may take a while)..."
        python -u tiktok_monitor.py --fetch-all-favorites
        echo "Favorites fetch complete"
    fi

    echo "Starting monitor in watch mode (interval: ${SYNC_INTERVAL:-120} minutes)..."
    python -u tiktok_monitor.py --watch --interval "${SYNC_INTERVAL:-120}" $CMD_ARGS
else
    exec "$@"
fi
