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
from urllib.parse import parse_qs, unquote, urlparse


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
        elif path == "/api/config":
            self.send_json({"download_dir": self.data_dir})
        elif path.startswith("/video/"):
            self.serve_video(path[7:])  # Strip /video/ prefix
        elif path == "/" or path == "/index.html":
            self.serve_index()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/delete":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}
            video_id = data.get("video_id")
            if video_id:
                result = self.delete_video(video_id)
                self.send_json(result)
            else:
                self.send_json({"success": False, "error": "No video_id provided"})
        else:
            self.send_error(404, "Not found")

    def send_json(self, data):
        content = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def _safe_load_json(self, filepath: Path, default=None):
        """Safely load JSON file, returning default if file is being written or corrupt."""
        if default is None:
            default = {}
        if not filepath.exists():
            return default
        try:
            with open(filepath) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # File is being written or is corrupt - return default
            return default

    def get_collections(self) -> list:
        """Get all collections with video counts."""
        collections_file = Path(self.data_dir) / "collections.json"
        videos_file = Path(self.data_dir) / "videos.json"

        collections = self._safe_load_json(collections_file, {})
        videos = self._safe_load_json(videos_file, {})

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
        videos = self._safe_load_json(videos_file, {})

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
                "deleted_from_tiktok": vid.get("deleted_from_tiktok", False),
            })

        return sorted(result, key=lambda x: x.get("create_time") or 0, reverse=True)

    def get_status(self) -> dict:
        """Get download queue status."""
        queue_file = Path(self.data_dir) / "download_queue.json"
        videos_file = Path(self.data_dir) / "videos.json"

        videos = self._safe_load_json(videos_file, {})
        deleted_count = sum(1 for v in videos.values() if v.get("deleted_from_tiktok"))

        queue = self._safe_load_json(queue_file, {})

        return {
            "pending": len(queue.get("pending", [])),
            "completed": len(queue.get("completed", [])),
            "failed": len(queue.get("failed", [])),
            "deleted": deleted_count,
        }

    def delete_video(self, video_id: str) -> dict:
        """Delete a video and its files."""
        import shutil

        videos_file = Path(self.data_dir) / "videos.json"
        queue_file = Path(self.data_dir) / "download_queue.json"

        videos = self._safe_load_json(videos_file, {})
        if not videos:
            return {"success": False, "error": "No videos found or file busy"}

        if video_id not in videos:
            return {"success": False, "error": "Video not found"}

        # Get video info and delete files
        video = videos[video_id]
        deleted_path = None
        download_path = video.get("download_path")
        if download_path:
            video_dir = Path(download_path).parent
            if video_dir.exists():
                shutil.rmtree(video_dir)
                deleted_path = str(video_dir)

                # Also remove parent collection folder if empty
                collection_dir = video_dir.parent
                if collection_dir.exists() and not any(collection_dir.iterdir()):
                    collection_dir.rmdir()

        # Remove from videos
        del videos[video_id]
        try:
            with open(videos_file, "w") as f:
                json.dump(videos, f, indent=2)
        except IOError:
            return {"success": False, "error": "Could not save videos file"}

        # Update queue
        queue = self._safe_load_json(queue_file, {})
        if queue:
            queue["pending"] = [v for v in queue.get("pending", []) if v["id"] != video_id]
            queue["failed"] = [v for v in queue.get("failed", []) if v["id"] != video_id]
            if video_id in queue.get("completed", []):
                queue["completed"].remove(video_id)

            try:
                with open(queue_file, "w") as f:
                    json.dump(queue, f, indent=2)
            except IOError:
                pass  # Non-critical, queue will be updated on next sync

        return {"success": True, "deleted_path": deleted_path}

    def serve_video(self, video_path: str):
        """Serve a video file from the download directory."""
        # video_path format: collection_name/video_id/filename
        # URL-decode the path to handle spaces and special characters
        video_path = unquote(video_path)
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

        # Handle range requests for video streaming
        range_header = self.headers.get("Range")
        if range_header:
            # Parse range header (e.g., "bytes=0-" or "bytes=0-1024")
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if range_match[1] else file_size - 1

            # Ensure valid range
            if start >= file_size:
                self.send_error(416, "Range Not Satisfiable")
                return

            end = min(end, file_size - 1)
            content_length = end - start + 1

            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", content_length)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

            try:
                with open(full_path, "rb") as f:
                    f.seek(start)
                    remaining = content_length
                    chunk_size = 64 * 1024
                    while remaining > 0:
                        chunk = f.read(min(chunk_size, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            # No range request - send full file
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", file_size)
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

            try:
                with open(full_path, "rb") as f:
                    chunk_size = 64 * 1024
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

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
            flex-shrink: 0;
        }
        .videos-header h2 { font-size: 16px; }
        .filter-buttons button, .view-buttons button {
            background: #2a2a2a;
            border: none;
            color: #fff;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            margin-left: 5px;
        }
        .filter-buttons button.active, .view-buttons button.active { background: #fe2c55; }
        .view-buttons { margin-left: 20px; }
        .view-buttons button { font-size: 14px; padding: 6px 10px; }

        .videos-grid {
            overflow-y: auto;
            padding: 20px;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 20px;
            align-content: start;
        }
        /* View mode: small */
        .videos-grid.view-small {
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 15px;
        }
        .videos-grid.view-small .video-card video,
        .videos-grid.view-small .video-thumbnail {
            height: 320px;
            min-height: 320px;
        }
        .videos-grid.view-small .video-info { padding: 8px; }
        .videos-grid.view-small .video-author { font-size: 12px; }
        .videos-grid.view-small .video-desc { font-size: 11px; -webkit-line-clamp: 2; }
        /* View mode: large */
        .videos-grid.view-large {
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 25px;
        }
        .videos-grid.view-large .video-card video,
        .videos-grid.view-large .video-thumbnail {
            height: 570px;
            min-height: 570px;
        }
        .videos-grid.view-large .video-info { padding: 15px; }
        .videos-grid.view-large .video-desc { -webkit-line-clamp: 3; }
        /* View mode: list */
        .videos-grid.view-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .videos-grid.view-list .video-card {
            display: flex;
            flex-direction: row;
            min-height: 120px;
            flex-shrink: 0;
        }
        .videos-grid.view-list .video-card video,
        .videos-grid.view-list .video-thumbnail {
            width: 68px;
            height: 120px;
            min-height: 120px;
            min-width: 68px;
            aspect-ratio: auto;
            flex-shrink: 0;
        }
        .videos-grid.view-list .video-info {
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: 12px 20px;
        }
        .videos-grid.view-list .video-desc { -webkit-line-clamp: 2; }
        .video-card {
            background: #1a1a1a;
            border-radius: 8px;
            overflow: hidden;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .video-card:hover { transform: scale(1.02); }
        .video-card.not-downloaded { opacity: 0.5; }
        .video-card.deleted { border: 2px solid #d9534f; }
        .video-card.deleted .video-info::after {
            content: "DELETED FROM TIKTOK";
            display: block;
            color: #d9534f;
            font-size: 10px;
            font-weight: bold;
            margin-top: 4px;
        }
        .video-thumbnail {
            width: 100%;
            height: 390px;
            min-height: 390px;
            background: #2a2a2a;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #666;
            font-size: 12px;
        }
        .video-card video {
            width: 100%;
            height: 390px;
            min-height: 390px;
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
        .modal-delete {
            display: block;
            background: #d9534f;
            color: #fff;
            text-align: center;
            padding: 12px;
            border-radius: 8px;
            border: none;
            cursor: pointer;
            margin-top: 10px;
            width: 100%;
            font-size: 14px;
        }
        .modal-delete:hover { background: #c9302c; }
        .modal-path {
            font-size: 11px;
            color: #666;
            background: #0f0f0f;
            padding: 8px 10px;
            border-radius: 4px;
            margin-top: 15px;
            word-break: break-all;
            font-family: monospace;
        }
        .modal-path-label {
            color: #888;
            margin-bottom: 4px;
            display: block;
        }
        .download-dir {
            font-size: 11px;
            color: #666;
            margin-top: 10px;
            word-break: break-all;
            font-family: monospace;
            background: #0f0f0f;
            padding: 6px 8px;
            border-radius: 4px;
        }
        .download-dir-label {
            color: #888;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin-bottom: 2px;
            display: block;
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
            <div class="download-dir" id="download-dir"></div>
        </div>
        <div class="collections-list" id="collections"></div>
    </aside>

    <main class="main">
        <div class="videos-header">
            <h2 id="current-collection">All Videos</h2>
            <div style="display: flex; align-items: center;">
                <div class="filter-buttons">
                    <button id="filter-all" class="active">All</button>
                    <button id="filter-downloaded">Downloaded</button>
                    <button id="filter-pending">Pending</button>
                    <button id="filter-deleted">Deleted</button>
                </div>
                <div class="view-buttons">
                    <button id="view-list" title="List view">☰</button>
                    <button id="view-small" title="Small grid">▪▪</button>
                    <button id="view-medium" class="active" title="Medium grid">◼◼</button>
                    <button id="view-large" title="Large grid">⬛</button>
                </div>
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
                <div class="modal-path" id="modal-path"></div>
                <button class="modal-delete" id="modal-delete" onclick="deleteCurrentVideo()">Delete Video</button>
            </div>
        </div>
    </div>

    <script>
        let collections = [];
        let videos = [];
        let currentCollection = null;
        let currentFilter = 'all';
        let currentVideoId = null;
        let currentView = 'medium';
        let downloadDir = '';

        async function loadData() {
            try {
                const [collectionsRes, videosRes, statusRes, configRes] = await Promise.all([
                    fetch('/api/collections'),
                    fetch('/api/videos'),
                    fetch('/api/status'),
                    fetch('/api/config')
                ]);

                collections = await collectionsRes.json();
                videos = await videosRes.json();
                const status = await statusRes.json();
                const config = await configRes.json();
                downloadDir = config.download_dir;

                console.log('Loaded', videos.length, 'videos,', collections.length, 'collections');
                console.log('Download dir:', downloadDir);

                renderStatus(status);
                renderDownloadDir();
                renderCollections();
                renderVideos();
            } catch (err) {
                console.error('Failed to load data:', err);
                document.getElementById('videos').innerHTML =
                    '<div class="empty-state">Error loading videos: ' + err.message + '</div>';
            }
        }

        function renderDownloadDir() {
            document.getElementById('download-dir').innerHTML = `
                <span class="download-dir-label">Download folder:</span>
                ${escapeHtml(downloadDir)}
            `;
        }

        function renderStatus(status) {
            document.getElementById('status').innerHTML = `
                <span class="pending">${status.pending} pending</span>
                <span class="completed">${status.completed} done</span>
                <span class="failed">${status.failed} failed</span>
                ${status.deleted ? `<span class="failed">${status.deleted} deleted</span>` : ''}
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
                filtered = filtered.filter(v => !v.downloaded && !v.deleted_from_tiktok);
            } else if (currentFilter === 'deleted') {
                filtered = filtered.filter(v => v.deleted_from_tiktok);
            }

            if (filtered.length === 0) {
                container.innerHTML = '<div class="empty-state">No videos found</div>';
                return;
            }

            let html = '';
            for (const video of filtered) {
                const videoUrl = getVideoUrl(video.download_path);

                const classes = ['video-card'];
                if (!video.downloaded) classes.push('not-downloaded');
                if (video.deleted_from_tiktok) classes.push('deleted');

                html += `
                    <div class="${classes.join(' ')}"
                         onclick="openModal('${video.id}')">
                        ${videoUrl ?
                            `<video src="${videoUrl}" muted playsinline preload="auto"
                                onloadeddata="this.parentElement.classList.add('loaded')"
                                onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                            ></video>
                            <div class="video-thumbnail" style="display:none;">Failed to load</div>` :
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

        function getVideoUrl(downloadPath) {
            if (!downloadPath) return null;
            // Get last 3 path components and URL-encode each one
            const parts = downloadPath.split('/').slice(-3);
            return '/video/' + parts.map(p => encodeURIComponent(p)).join('/');
        }

        function openModal(videoId) {
            const video = videos.find(v => v.id === videoId);
            if (!video) return;

            currentVideoId = videoId;
            const modal = document.getElementById('modal');
            const modalVideo = document.getElementById('modal-video');

            if (video.download_path) {
                const videoUrl = getVideoUrl(video.download_path);
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

            // Show file path
            const pathEl = document.getElementById('modal-path');
            if (video.download_path) {
                pathEl.innerHTML = `<span class="modal-path-label">File location:</span>${escapeHtml(video.download_path)}`;
                pathEl.style.display = 'block';
            } else {
                pathEl.style.display = 'none';
            }

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

        async function deleteCurrentVideo() {
            if (!currentVideoId) return;

            if (!confirm('Are you sure you want to delete this video and its files?')) {
                return;
            }

            try {
                const response = await fetch('/api/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ video_id: currentVideoId })
                });

                const result = await response.json();
                if (result.success) {
                    // Remove from local videos array
                    videos = videos.filter(v => v.id !== currentVideoId);
                    closeModal();
                    renderVideos();
                    renderCollections();
                    // Reload status
                    const statusRes = await fetch('/api/status');
                    renderStatus(await statusRes.json());
                } else {
                    alert('Failed to delete: ' + (result.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Error deleting video: ' + err.message);
            }
        }

        function setView(view) {
            currentView = view;
            const grid = document.getElementById('videos');
            grid.classList.remove('view-list', 'view-small', 'view-large');
            if (view !== 'medium') {
                grid.classList.add('view-' + view);
            }
            document.querySelectorAll('.view-buttons button').forEach(b => b.classList.remove('active'));
            document.getElementById('view-' + view).classList.add('active');
        }

        // Event listeners
        document.getElementById('filter-all').onclick = () => setFilter('all');
        document.getElementById('filter-downloaded').onclick = () => setFilter('downloaded');
        document.getElementById('filter-pending').onclick = () => setFilter('pending');
        document.getElementById('filter-deleted').onclick = () => setFilter('deleted');

        document.getElementById('view-list').onclick = () => setView('list');
        document.getElementById('view-small').onclick = () => setView('small');
        document.getElementById('view-medium').onclick = () => setView('medium');
        document.getElementById('view-large').onclick = () => setView('large');

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeModal();
        });

        // Load data on start
        loadData();
    </script>
</body>
</html>'''

    def log_message(self, format, *args):
        # Log requests for debugging - use format string safely
        try:
            print(format % args)
        except Exception:
            print(f"[LOG] {args}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="TikTok Collections Web Viewer")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port to run server on")
    parser.add_argument("--host", default="localhost", help="Host to bind to")
    args = parser.parse_args()

    config = load_config()
    # Environment variable overrides config (useful for Docker)
    data_dir = os.environ.get("DOWNLOAD_DIR") or config.get("download_dir", "./downloads")

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
