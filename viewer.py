#!/usr/bin/env python3
"""
Minimal HTTP server for the TikTok collections viewer.
Serves the viewer.html and downloaded videos.
"""

import argparse
import http.server
import socketserver
import os
from pathlib import Path

class ViewerHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler to serve from the downloads directory."""

    def __init__(self, *args, **kwargs):
        # Serve from downloads directory
        super().__init__(*args, directory=str(Path("downloads").absolute()), **kwargs)

    def end_headers(self):
        # Add CORS headers to allow local access
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def log_message(self, format, *args):
        """Custom log format."""
        print(f"[Viewer] {self.address_string()} - {format % args}")

def main():
    parser = argparse.ArgumentParser(description="TikTok Collections Viewer Server")
    parser.add_argument("-p", "--port", type=int, default=8425,
                        help="Port to serve on (default: 8425)")
    parser.add_argument("-d", "--directory", default="downloads",
                        help="Downloads directory to serve (default: downloads)")
    args = parser.parse_args()

    # Change to the downloads directory
    downloads_dir = Path(args.directory)
    if not downloads_dir.exists():
        print(f"Creating downloads directory: {downloads_dir}")
        downloads_dir.mkdir(parents=True, exist_ok=True)

    # Check for viewer.html in downloads directory
    viewer_path = downloads_dir / "viewer.html"
    if viewer_path.exists():
        print(f"✓ Viewer found at: {viewer_path}")
        print(f"✓ Access at: http://localhost:{args.port}/viewer.html")
    else:
        print(f"⚠ Warning: viewer.html not found at {viewer_path}")
        print("  Run the monitor first to generate the viewer")

    # Start server
    with socketserver.TCPServer(("", args.port), ViewerHTTPRequestHandler) as httpd:
        print(f"\n🌐 Viewer server running at http://0.0.0.0:{args.port}")
        print(f"📁 Serving: {downloads_dir.absolute()}")
        print("Press Ctrl+C to stop\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\nShutting down viewer server...")

if __name__ == "__main__":
    main()
