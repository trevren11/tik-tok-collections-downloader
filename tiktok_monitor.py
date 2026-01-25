#!/usr/bin/env python3
"""
TikTok Collections Monitor

Monitors your TikTok collections for changes, detects new/deleted videos,
and downloads new videos with metadata.

Modes:
  --sync       : Fetch collections and videos, update queue
  --download   : Process download queue
  --watch      : Run sync periodically + process downloads
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright


class DataStore:
    """JSON-based data store for collections, videos, and download queue."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.collections_file = self.data_dir / "collections.json"
        self.videos_file = self.data_dir / "videos.json"
        self.queue_file = self.data_dir / "download_queue.json"

        self.collections = self._load(self.collections_file, {})
        self.videos = self._load(self.videos_file, {})
        self.queue = self._load(self.queue_file, {"pending": [], "completed": [], "failed": []})

    def _load(self, path: Path, default: dict) -> dict:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return default

    def _save(self, path: Path, data: dict):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def save_collections(self):
        self._save(self.collections_file, self.collections)

    def save_videos(self):
        self._save(self.videos_file, self.videos)

    def save_queue(self):
        self._save(self.queue_file, self.queue)

    def update_collection(self, coll_id: str, coll_data: dict):
        self.collections[coll_id] = {
            **coll_data,
            "updated_at": datetime.now().isoformat(),
        }

    def add_video(self, video_id: str, video_data: dict):
        is_new = video_id not in self.videos
        self.videos[video_id] = {
            **video_data,
            "cached_at": datetime.now().isoformat(),
        }
        return is_new

    def queue_download(self, video_id: str, video_data: dict):
        # Don't queue if already in queue or completed
        if video_id in [v["id"] for v in self.queue["pending"]]:
            return False
        if video_id in self.queue["completed"]:
            return False

        self.queue["pending"].append({
            "id": video_id,
            "url": video_data.get("url"),
            "collection": video_data.get("collection_name"),
            "author": video_data.get("author"),
            "desc": video_data.get("desc", ""),
            "queued_at": datetime.now().isoformat(),
        })
        return True

    def get_pending_downloads(self) -> list:
        return self.queue["pending"]

    def mark_downloaded(self, video_id: str, path: str):
        # Remove from pending
        self.queue["pending"] = [v for v in self.queue["pending"] if v["id"] != video_id]
        self.queue["completed"].append(video_id)

        # Update video record
        if video_id in self.videos:
            self.videos[video_id]["downloaded"] = True
            self.videos[video_id]["download_path"] = path
            self.videos[video_id]["downloaded_at"] = datetime.now().isoformat()

    def mark_failed(self, video_id: str, error: str):
        # Move from pending to failed
        for v in self.queue["pending"]:
            if v["id"] == video_id:
                v["error"] = error
                v["failed_at"] = datetime.now().isoformat()
                self.queue["failed"].append(v)
                break
        self.queue["pending"] = [v for v in self.queue["pending"] if v["id"] != video_id]


class TikTokClient:
    """Client for fetching TikTok data via browser automation."""

    def __init__(self, sessionid: str):
        self.sessionid = sessionid

    def _create_context(self, playwright):
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        context.add_cookies([
            {"name": "sessionid", "value": self.sessionid, "domain": ".tiktok.com", "path": "/"},
            {"name": "sessionid_ss", "value": self.sessionid, "domain": ".tiktok.com", "path": "/"},
        ])
        return browser, context

    def get_collections(self) -> list:
        """Fetch all collections."""
        collections = []

        with sync_playwright() as p:
            browser, context = self._create_context(p)
            page = context.new_page()

            def handle_response(response):
                if "collection_list" in response.url:
                    try:
                        data = response.json()
                        if "collectionList" in data:
                            for coll in data["collectionList"]:
                                if not any(c.get("collectionId") == coll.get("collectionId") for c in collections):
                                    collections.append(coll)
                    except Exception:
                        pass

            page.on("response", handle_response)
            page.goto("https://www.tiktok.com/", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            browser.close()

        return collections

    def get_collection_videos(self, collection_id: str, collection_name: str, limit: Optional[int] = None) -> list:
        """Fetch videos in a collection."""
        videos = []

        with sync_playwright() as p:
            browser, context = self._create_context(p)
            page = context.new_page()

            def handle_response(response):
                if "collection/item_list" in response.url or "collect/item_list" in response.url:
                    try:
                        data = response.json()
                        if "itemList" in data:
                            videos.extend(data["itemList"])
                    except Exception:
                        pass

            page.on("response", handle_response)

            url = f"https://www.tiktok.com/@me/collection/{collection_name}-{collection_id}"
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # Scroll to load more if needed
            scroll_count = 0
            max_scrolls = 50 if not limit else (limit // 30) + 2

            while scroll_count < max_scrolls:
                prev_count = len(videos)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)
                scroll_count += 1

                if len(videos) == prev_count:
                    break
                if limit and len(videos) >= limit:
                    break

            browser.close()

        return videos[:limit] if limit else videos


class VideoDownloader:
    """Downloads TikTok videos using yt-dlp."""

    def __init__(self, download_dir: str):
        self.download_dir = Path(download_dir)

    def download(self, video_id: str, author: str, collection_name: str, description: str = "") -> Optional[str]:
        """
        Download video into collection/video_id/ folder with metadata.

        Returns the download path on success, None on failure.
        """
        # Create folder structure: collection/video_id/
        safe_collection = "".join(c if c.isalnum() or c in " -_" else "_" for c in collection_name)
        video_dir = self.download_dir / safe_collection / video_id
        video_dir.mkdir(parents=True, exist_ok=True)

        video_url = f"https://www.tiktok.com/@{author}/video/{video_id}"
        output_template = str(video_dir / f"{video_id}.%(ext)s")

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "yt_dlp",
                    "--no-warnings",
                    "-o", output_template,
                    "--write-info-json",
                    video_url,
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )

            if result.returncode == 0:
                # Save description/caption
                if description:
                    with open(video_dir / "caption.txt", "w") as f:
                        f.write(description)

                # Find the downloaded video file
                for ext in ["mp4", "webm", "mkv"]:
                    video_file = video_dir / f"{video_id}.{ext}"
                    if video_file.exists():
                        return str(video_file)

                # Check if any video file exists
                for f in video_dir.iterdir():
                    if f.suffix in [".mp4", ".webm", ".mkv"]:
                        return str(f)
            else:
                print(f"    yt-dlp error: {result.stderr[:200]}")

        except subprocess.TimeoutExpired:
            print(f"    Download timeout for {video_id}")
        except Exception as e:
            print(f"    Download error: {e}")

        return None


def load_config(config_path: str = "config.json") -> dict:
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def cmd_sync(client: TikTokClient, store: DataStore, collection_limit: Optional[int] = None, video_limit: Optional[int] = None):
    """Sync collections and videos, queue new downloads."""
    print("\n=== SYNC MODE ===")

    # Step 1: Fetch collections
    print("\nFetching collections...")
    collections = client.get_collections()
    print(f"Found {len(collections)} collections")

    for coll in collections:
        coll_id = coll.get("collectionId")
        coll_name = coll.get("name", "Unnamed")
        store.update_collection(coll_id, {
            "id": coll_id,
            "name": coll_name,
            "total": coll.get("total", 0),
        })
    store.save_collections()

    # Step 2: Fetch videos for each collection
    collections_to_process = list(store.collections.values())
    if collection_limit:
        collections_to_process = collections_to_process[:collection_limit]

    new_videos = 0
    queued = 0

    for coll in collections_to_process:
        coll_id = coll["id"]
        coll_name = coll["name"]
        print(f"\nFetching videos from: {coll_name}")

        videos = client.get_collection_videos(coll_id, coll_name, limit=video_limit)
        print(f"  Found {len(videos)} videos")

        for vid in videos:
            vid_id = vid.get("id")
            if not vid_id:
                continue

            author = vid.get("author", {}).get("uniqueId", "unknown")
            video_data = {
                "id": vid_id,
                "author": author,
                "desc": vid.get("desc", ""),
                "collection_id": coll_id,
                "collection_name": coll_name,
                "url": f"https://www.tiktok.com/@{author}/video/{vid_id}",
                "create_time": vid.get("createTime"),
                "stats": vid.get("stats", {}),
            }

            is_new = store.add_video(vid_id, video_data)
            if is_new:
                new_videos += 1
                if store.queue_download(vid_id, video_data):
                    queued += 1

    store.save_videos()
    store.save_queue()

    print(f"\n=== SYNC COMPLETE ===")
    print(f"New videos found: {new_videos}")
    print(f"Queued for download: {queued}")
    print(f"Pending downloads: {len(store.get_pending_downloads())}")


def cmd_download(store: DataStore, downloader: VideoDownloader, limit: Optional[int] = None):
    """Process download queue."""
    print("\n=== DOWNLOAD MODE ===")

    pending = store.get_pending_downloads()
    if not pending:
        print("No pending downloads.")
        return

    to_process = pending[:limit] if limit else pending
    print(f"Processing {len(to_process)} downloads...")

    for i, item in enumerate(to_process, 1):
        vid_id = item["id"]
        author = item.get("author", "unknown")
        collection = item.get("collection", "uncategorized")
        desc = item.get("desc", "")

        print(f"\n[{i}/{len(to_process)}] Downloading {vid_id}")
        print(f"  Collection: {collection}")
        print(f"  Author: @{author}")

        path = downloader.download(vid_id, author, collection, desc)

        if path:
            store.mark_downloaded(vid_id, path)
            print(f"  Success: {path}")
        else:
            store.mark_failed(vid_id, "Download failed")
            print(f"  Failed!")

        store.save_queue()
        store.save_videos()

    print(f"\n=== DOWNLOAD COMPLETE ===")
    print(f"Remaining in queue: {len(store.get_pending_downloads())}")


def cmd_watch(client: TikTokClient, store: DataStore, downloader: VideoDownloader, interval: int):
    """Watch mode: periodic sync + download."""
    print(f"\n=== WATCH MODE (every {interval} minutes) ===")
    print("Press Ctrl+C to stop\n")

    while True:
        try:
            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")

            # Sync first
            cmd_sync(client, store)

            # Then download
            cmd_download(store, downloader)

            print(f"\nNext check in {interval} minutes...")
            time.sleep(interval * 60)

        except KeyboardInterrupt:
            print("\n\nStopping...")
            break
        except Exception as e:
            print(f"\nError: {e}")
            print(f"Retrying in {interval} minutes...")
            time.sleep(interval * 60)


def cmd_status(store: DataStore):
    """Show current status."""
    print("\n=== STATUS ===")
    print(f"Collections: {len(store.collections)}")
    print(f"Videos tracked: {len(store.videos)}")
    print(f"Pending downloads: {len(store.queue['pending'])}")
    print(f"Completed downloads: {len(store.queue['completed'])}")
    print(f"Failed downloads: {len(store.queue['failed'])}")

    # Show download state summary by collection
    if store.collections:
        print("\n--- Collections Overview ---")
        for coll_id, coll in store.collections.items():
            coll_name = coll.get("name", "Unknown")
            # Count videos in this collection
            coll_videos = [v for v in store.videos.values() if v.get("collection_id") == coll_id]
            downloaded = sum(1 for v in coll_videos if v.get("downloaded"))
            total = len(coll_videos)
            print(f"  {coll_name}: {downloaded}/{total} downloaded")

    if store.queue["pending"]:
        print("\n--- Pending Downloads ---")
        for item in store.queue["pending"][:10]:
            print(f"  [{item['collection']}] {item['id']}")
        if len(store.queue["pending"]) > 10:
            print(f"  ... and {len(store.queue['pending']) - 10} more")

    if store.queue["failed"]:
        print("\n--- Failed Downloads ---")
        for item in store.queue["failed"][:5]:
            error = item.get("error", "Unknown error")
            print(f"  [{item['collection']}] {item['id']} - {error}")
        if len(store.queue["failed"]) > 5:
            print(f"  ... and {len(store.queue['failed']) - 5} more")


def main():
    parser = argparse.ArgumentParser(description="TikTok Collections Monitor")
    parser.add_argument("--sync", action="store_true", help="Fetch collections and videos, update queue")
    parser.add_argument("--download", action="store_true", help="Process download queue")
    parser.add_argument("--watch", action="store_true", help="Run sync + download periodically")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--interval", "-i", type=int, default=60, help="Watch interval in minutes")
    parser.add_argument("--limit", "-l", type=int, help="Limit downloads per run")
    parser.add_argument("--collection-limit", type=int, help="Limit collections to sync")
    parser.add_argument("--video-limit", type=int, help="Limit videos per collection")
    args = parser.parse_args()

    print("TikTok Collections Monitor")
    print("-" * 40)

    config = load_config()
    sessionid = config.get("cookies", {}).get("sessionid", "")
    if not sessionid:
        print("Error: No sessionid found in config.json")
        sys.exit(1)

    download_dir = config.get("download_dir", "./downloads")

    # Initialize
    client = TikTokClient(sessionid)
    store = DataStore(download_dir)
    downloader = VideoDownloader(download_dir)

    print(f"Data/Download dir: {download_dir}")

    if args.status:
        cmd_status(store)
    elif args.sync:
        cmd_sync(client, store, args.collection_limit, args.video_limit)
    elif args.download:
        cmd_download(store, downloader, args.limit)
    elif args.watch:
        cmd_watch(client, store, downloader, args.interval)
    else:
        # Default: sync then download
        cmd_sync(client, store, args.collection_limit, args.video_limit)
        cmd_download(store, downloader, args.limit)


if __name__ == "__main__":
    main()
