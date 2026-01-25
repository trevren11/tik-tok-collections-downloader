#!/usr/bin/env python3
"""
TikTok Collections Web Viewer

A simple web interface to browse downloaded TikTok videos.
Reads from the existing JSON data files created by tiktok_monitor.py.
"""

import json
import mimetypes
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def load_config(config_path: str = "config.json") -> dict:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


class ViewerHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for the video viewer."""

    data_dir = None

    def __init__(self, *args, **kwargs):
        # Set directory to serve static files from
        super().__init__(*args, directory=str(Path(__file__).parent), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # API endpoints
        if path == "/api/collections":
            self.send_json(self.get_collections())
        elif path == "/api/videos":
            query = parse_qs(parsed.query)
            collection_id = query.get("collection_id", [None])[0]
            self.send_json(self.get_videos(collection_id))
        elif path == "/api/status":
            self.send_json(self.get_status())
        elif path.startswith("/video/"):
            self.serve_video(path[7:])  # Strip /video/ prefix
        elif path == "/" or path == "/index.html":
            self.serve_index()
        else:
            super().do_GET()

    def send_json(self, data):
        content = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def get_collections(self) -> list:
        """Get all collections with video counts."""
        collections_file = Path(self.data_dir) / "collections.json"
        videos_file = Path(self.data_dir) / "videos.json"

        collections = {}
        if collections_file.exists():
            with open(collections_file) as f:
                collections = json.load(f)

        videos = {}
        if videos_file.exists():
            with open(videos_file) as f:
                videos = json.load(f)

        result = []
        for coll_id, coll in collections.items():
            coll_videos = [v for v in videos.values() if v.get("collection_id") == coll_id]
            downloaded = sum(1 for v in coll_videos if v.get("downloaded"))
            result.append({
                "id": coll_id,
                "name": coll.get("name", "Unknown"),
                "total_synced": len(coll_videos),
                "downloaded": downloaded,
                "total_reported": coll.get("total", 0),
            })

        return sorted(result, key=lambda x: x["name"].lower())

    def get_videos(self, collection_id: str = None) -> list:
        """Get videos, optionally filtered by collection."""
        videos_file = Path(self.data_dir) / "videos.json"

        if not videos_file.exists():
            return []

        with open(videos_file) as f:
            videos = json.load(f)

        result = []
        for vid_id, vid in videos.items():
            if collection_id and vid.get("collection_id") != collection_id:
                continue

            # Check if video file exists
            download_path = vid.get("download_path")
            has_file = download_path and Path(download_path).exists()

            # Get caption if available
            caption = vid.get("desc", "")
            if has_file:
                caption_file = Path(download_path).parent / "caption.txt"
                if caption_file.exists():
                    caption = caption_file.read_text()

            result.append({
                "id": vid_id,
                "author": vid.get("author", "unknown"),
                "desc": caption,
                "collection_id": vid.get("collection_id"),
                "collection_name": vid.get("collection_name", "Unknown"),
                "url": vid.get("url"),
                "downloaded": vid.get("downloaded", False),
                "download_path": download_path if has_file else None,
                "stats": vid.get("stats", {}),
                "create_time": vid.get("create_time"),
            })

        return sorted(result, key=lambda x: x.get("create_time") or 0, reverse=True)

    def get_status(self) -> dict:
        """Get download queue status."""
        queue_file = Path(self.data_dir) / "download_queue.json"

        if not queue_file.exists():
            return {"pending": 0, "completed": 0, "failed": 0}

        with open(queue_file) as f:
            queue = json.load(f)

        return {
            "pending": len(queue.get("pending", [])),
            "completed": len(queue.get("completed", [])),
            "failed": len(queue.get("failed", [])),
        }

    def serve_video(self, video_path: str):
        """Serve a video file from the download directory."""
        # video_path format: collection_name/video_id/filename
        full_path = Path(self.data_dir) / video_path

        if not full_path.exists() or not full_path.is_file():
            self.send_error(404, "Video not found")
            return

        # Security check - ensure path is within data_dir
        try:
            full_path.resolve().relative_to(Path(self.data_dir).resolve())
        except ValueError:
            self.send_error(403, "Access denied")
            return

        content_type, _ = mimetypes.guess_type(str(full_path))
        if not content_type:
            content_type = "application/octet-stream"

        file_size = full_path.stat().st_size

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", file_size)
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        with open(full_path, "rb") as f:
            self.wfile.write(f.read())

    def serve_index(self):
        """Serve the main HTML page."""
        html = self.generate_html()
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def generate_html(self) -> str:
        """Generate the single-page app HTML."""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TikTok Collections Viewer</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f;
            color: #fff;
            display: flex;
            height: 100vh;
        }

        /* Sidebar */
        .sidebar {
            width: 280px;
            background: #1a1a1a;
            border-right: 1px solid #333;
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        .sidebar-header {
            padding: 20px;
            border-bottom: 1px solid #333;
        }
        .sidebar-header h1 {
            font-size: 18px;
            margin-bottom: 10px;
        }
        .status {
            font-size: 12px;
            color: #888;
        }
        .status span { margin-right: 10px; }
        .status .pending { color: #f0ad4e; }
        .status .completed { color: #5cb85c; }
        .status .failed { color: #d9534f; }

        .collections-list {
            flex: 1;
            overflow-y: auto;
            padding: 10px;
        }
        .collection-item {
            padding: 12px 15px;
            border-radius: 8px;
            cursor: pointer;
            margin-bottom: 5px;
            transition: background 0.2s;
        }
        .collection-item:hover { background: #2a2a2a; }
        .collection-item.active { background: #fe2c55; }
        .collection-name {
            font-weight: 500;
            margin-bottom: 4px;
        }
        .collection-stats {
            font-size: 12px;
            color: #888;
        }
        .collection-item.active .collection-stats { color: #ffb8c5; }

        /* Main content */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .videos-header {
            padding: 15px 20px;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .videos-header h2 { font-size: 16px; }
        .filter-buttons button {
            background: #2a2a2a;
            border: none;
            color: #fff;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            margin-left: 5px;
        }
        .filter-buttons button.active { background: #fe2c55; }

        .videos-grid {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 15px;
            align-content: start;
        }
        .video-card {
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .video-card:hover { transform: scale(1.02); }
        .video-card.not-downloaded { opacity: 0.5; }
        .video-thumbnail {
            aspect-ratio: 9/16;
            background: #2a2a2a;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #666;
            font-size: 12px;
        }
        .video-card video {
            width: 100%;
            aspect-ratio: 9/16;
            object-fit: cover;
        }
        .video-info {
            padding: 10px;
        }
        .video-author {
            font-size: 13px;
            color: #888;
            margin-bottom: 4px;
        }
        .video-desc {
            font-size: 12px;
            color: #ccc;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        /* Video modal */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
        }
        .modal.active { display: flex; }
        .modal-content {
            display: flex;
            width: 100%;
            height: 100%;
        }
        .modal-video {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #000;
        }
        .modal-video video {
            max-height: 100%;
            max-width: 100%;
        }
        .modal-sidebar {
            width: 350px;
            background: #1a1a1a;
            padding: 20px;
            overflow-y: auto;
        }
        .modal-close {
            position: absolute;
            top: 20px;
            right: 380px;
            background: none;
            border: none;
            color: #fff;
            font-size: 30px;
            cursor: pointer;
            z-index: 1001;
        }
        .modal-author {
            font-size: 18px;
            margin-bottom: 15px;
        }
        .modal-author a {
            color: #fe2c55;
            text-decoration: none;
        }
        .modal-collection {
            color: #888;
            font-size: 14px;
            margin-bottom: 20px;
        }
        .modal-caption {
            font-size: 14px;
            line-height: 1.6;
            white-space: pre-wrap;
            margin-bottom: 20px;
            max-height: 300px;
            overflow-y: auto;
        }
        .modal-stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-bottom: 20px;
        }
        .stat {
            text-align: center;
            padding: 10px;
            background: #2a2a2a;
            border-radius: 8px;
        }
        .stat-value {
            font-size: 18px;
            font-weight: bold;
        }
        .stat-label {
            font-size: 11px;
            color: #888;
            margin-top: 4px;
        }
        .modal-link {
            display: block;
            background: #fe2c55;
            color: #fff;
            text-align: center;
            padding: 12px;
            border-radius: 8px;
            text-decoration: none;
            margin-top: 20px;
        }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }
    </style>
</head>
<body>
    <aside class="sidebar">
        <div class="sidebar-header">
            <h1>TikTok Collections</h1>
            <div class="status" id="status">Loading...</div>
        </div>
        <div class="collections-list" id="collections"></div>
    </aside>

    <main class="main">
        <div class="videos-header">
            <h2 id="current-collection">All Videos</h2>
            <div class="filter-buttons">
                <button id="filter-all" class="active">All</button>
                <button id="filter-downloaded">Downloaded</button>
                <button id="filter-pending">Pending</button>
            </div>
        </div>
        <div class="videos-grid" id="videos"></div>
    </main>

    <div class="modal" id="modal">
        <button class="modal-close" onclick="closeModal()">&times;</button>
        <div class="modal-content">
            <div class="modal-video">
                <video id="modal-video" controls></video>
            </div>
            <div class="modal-sidebar">
                <div class="modal-author" id="modal-author"></div>
                <div class="modal-collection" id="modal-collection"></div>
                <div class="modal-caption" id="modal-caption"></div>
                <div class="modal-stats" id="modal-stats"></div>
                <a class="modal-link" id="modal-link" href="#" target="_blank">View on TikTok</a>
            </div>
        </div>
    </div>

    <script>
        let collections = [];
        let videos = [];
        let currentCollection = null;
        let currentFilter = 'all';

        async function loadData() {
            const [collectionsRes, videosRes, statusRes] = await Promise.all([
                fetch('/api/collections'),
                fetch('/api/videos'),
                fetch('/api/status')
            ]);

            collections = await collectionsRes.json();
            videos = await videosRes.json();
            const status = await statusRes.json();

            renderStatus(status);
            renderCollections();
            renderVideos();
        }

        function renderStatus(status) {
            document.getElementById('status').innerHTML = `
                <span class="pending">${status.pending} pending</span>
                <span class="completed">${status.completed} done</span>
                <span class="failed">${status.failed} failed</span>
            `;
        }

        function renderCollections() {
            const container = document.getElementById('collections');

            // Add "All" option
            let html = `
                <div class="collection-item ${!currentCollection ? 'active' : ''}" onclick="selectCollection(null)">
                    <div class="collection-name">All Videos</div>
                    <div class="collection-stats">${videos.length} videos</div>
                </div>
            `;

            for (const coll of collections) {
                const isActive = currentCollection === coll.id;
                html += `
                    <div class="collection-item ${isActive ? 'active' : ''}" onclick="selectCollection('${coll.id}')">
                        <div class="collection-name">${escapeHtml(coll.name)}</div>
                        <div class="collection-stats">${coll.downloaded}/${coll.total_synced} downloaded</div>
                    </div>
                `;
            }

            container.innerHTML = html;
        }

        function renderVideos() {
            const container = document.getElementById('videos');

            let filtered = videos;

            // Filter by collection
            if (currentCollection) {
                filtered = filtered.filter(v => v.collection_id === currentCollection);
                const coll = collections.find(c => c.id === currentCollection);
                document.getElementById('current-collection').textContent = coll ? coll.name : 'Videos';
            } else {
                document.getElementById('current-collection').textContent = 'All Videos';
            }

            // Filter by download status
            if (currentFilter === 'downloaded') {
                filtered = filtered.filter(v => v.downloaded);
            } else if (currentFilter === 'pending') {
                filtered = filtered.filter(v => !v.downloaded);
            }

            if (filtered.length === 0) {
                container.innerHTML = '<div class="empty-state">No videos found</div>';
                return;
            }

            let html = '';
            for (const video of filtered) {
                const videoUrl = video.download_path ?
                    `/video/${video.download_path.split('/').slice(-3).join('/')}` : null;

                html += `
                    <div class="video-card ${!video.downloaded ? 'not-downloaded' : ''}"
                         onclick="openModal('${video.id}')">
                        ${videoUrl ?
                            `<video src="${videoUrl}" muted preload="metadata"></video>` :
                            `<div class="video-thumbnail">Not downloaded</div>`
                        }
                        <div class="video-info">
                            <div class="video-author">@${escapeHtml(video.author)}</div>
                            <div class="video-desc">${escapeHtml(video.desc || 'No caption')}</div>
                        </div>
                    </div>
                `;
            }

            container.innerHTML = html;
        }

        function selectCollection(id) {
            currentCollection = id;
            renderCollections();
            renderVideos();
        }

        function setFilter(filter) {
            currentFilter = filter;
            document.querySelectorAll('.filter-buttons button').forEach(b => b.classList.remove('active'));
            document.getElementById(`filter-${filter}`).classList.add('active');
            renderVideos();
        }

        function openModal(videoId) {
            const video = videos.find(v => v.id === videoId);
            if (!video) return;

            const modal = document.getElementById('modal');
            const modalVideo = document.getElementById('modal-video');

            if (video.download_path) {
                const videoUrl = `/video/${video.download_path.split('/').slice(-3).join('/')}`;
                modalVideo.src = videoUrl;
                modalVideo.style.display = 'block';
            } else {
                modalVideo.style.display = 'none';
            }

            document.getElementById('modal-author').innerHTML =
                `<a href="https://www.tiktok.com/@${video.author}" target="_blank">@${escapeHtml(video.author)}</a>`;
            document.getElementById('modal-collection').textContent =
                `Collection: ${escapeHtml(video.collection_name)}`;
            document.getElementById('modal-caption').textContent = video.desc || 'No caption';
            document.getElementById('modal-link').href = video.url;

            const stats = video.stats || {};
            document.getElementById('modal-stats').innerHTML = `
                <div class="stat">
                    <div class="stat-value">${formatNumber(stats.playCount || 0)}</div>
                    <div class="stat-label">Views</div>
                </div>
                <div class="stat">
                    <div class="stat-value">${formatNumber(stats.diggCount || 0)}</div>
                    <div class="stat-label">Likes</div>
                </div>
                <div class="stat">
                    <div class="stat-value">${formatNumber(stats.commentCount || 0)}</div>
                    <div class="stat-label">Comments</div>
                </div>
            `;

            modal.classList.add('active');
            if (video.download_path) {
                modalVideo.play();
            }
        }

        function closeModal() {
            const modal = document.getElementById('modal');
            const modalVideo = document.getElementById('modal-video');
            modalVideo.pause();
            modalVideo.src = '';
            modal.classList.remove('active');
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toString();
        }

        // Event listeners
        document.getElementById('filter-all').onclick = () => setFilter('all');
        document.getElementById('filter-downloaded').onclick = () => setFilter('downloaded');
        document.getElementById('filter-pending').onclick = () => setFilter('pending');

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeModal();
        });

        // Load data on start
        loadData();
    </script>
</body>
</html>'''

    def log_message(self, format, *args):
        # Suppress default logging for cleaner output
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="TikTok Collections Web Viewer")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port to run server on")
    parser.add_argument("--host", default="localhost", help="Host to bind to")
    args = parser.parse_args()

    config = load_config()
    data_dir = config.get("download_dir", "./downloads")

    if not Path(data_dir).exists():
        print(f"Warning: Data directory not found: {data_dir}")
        print("Run tiktok_monitor.py --sync first to create it.")

    ViewerHandler.data_dir = data_dir

    server = HTTPServer((args.host, args.port), ViewerHandler)
    print(f"TikTok Collections Viewer")
    print(f"Data directory: {data_dir}")
    print(f"Server running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
