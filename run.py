#!/usr/bin/env python3
"""
Run both TikTok monitor and web viewer together.

Usage:
    python run.py                    # Run sync+download once, then start viewer
    python run.py --watch            # Run monitor in watch mode + viewer
    python run.py --viewer-only      # Only run the viewer
"""

import argparse
import subprocess
import sys
import threading
import time
import signal

def run_viewer(port=8425):
    """Run the web viewer."""
    print(f"Starting viewer on http://localhost:{port}")
    subprocess.run([sys.executable, "viewer.py", "-p", str(port)])

def run_monitor(watch=False, interval=30):
    """Run the TikTok monitor."""
    cmd = [sys.executable, "tiktok_monitor.py"]
    if watch:
        cmd.extend(["--watch", "-i", str(interval)])
    print(f"Starting monitor: {' '.join(cmd)}")
    subprocess.run(cmd)

def main():
    parser = argparse.ArgumentParser(description="Run TikTok downloader and viewer")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="Run monitor in watch mode (periodic sync)")
    parser.add_argument("--interval", "-i", type=int, default=30,
                        help="Watch interval in minutes (default: 30)")
    parser.add_argument("--port", "-p", type=int, default=8425,
                        help="Viewer port (default: 8425)")
    parser.add_argument("--viewer-only", action="store_true",
                        help="Only run the viewer, skip monitor")
    parser.add_argument("--sync-only", action="store_true",
                        help="Only run sync+download once, no viewer")
    args = parser.parse_args()

    if args.sync_only:
        run_monitor(watch=False)
        return

    if args.viewer_only:
        run_viewer(args.port)
        return

    # Run both: monitor in background thread, viewer in main thread
    if args.watch:
        # Watch mode: run monitor continuously in background
        monitor_thread = threading.Thread(
            target=run_monitor,
            args=(True, args.interval),
            daemon=True
        )
        monitor_thread.start()
        print(f"Monitor running in watch mode (interval: {args.interval} min)")
    else:
        # One-shot: run sync+download first, then start viewer
        print("Running initial sync and download...")
        run_monitor(watch=False)
        print("Sync complete. Starting viewer...")

    # Run viewer in main thread (blocks until Ctrl+C)
    try:
        run_viewer(args.port)
    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    main()
