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
    exec python -u tiktok_monitor.py --watch --interval "${SYNC_INTERVAL:-120}" $CMD_ARGS
else
    exec "$@"
fi
