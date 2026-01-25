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
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


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

    def delete_video(self, video_id: str) -> Optional[str]:
        """
        Delete a video from tracking and remove its files.

        Returns the deleted file path if files were removed, None otherwise.
        """
        import shutil

        deleted_path = None

        # Get video info before removing
        video = self.videos.get(video_id)
        if video:
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
            del self.videos[video_id]

        # Remove from queue lists
        self.queue["pending"] = [v for v in self.queue["pending"] if v["id"] != video_id]
        self.queue["failed"] = [v for v in self.queue["failed"] if v["id"] != video_id]
        if video_id in self.queue["completed"]:
            self.queue["completed"].remove(video_id)

        return deleted_path

    def clear_all_data(self):
        """Clear all tracking data (collections, videos, queue)."""
        self.collections = {}
        self.videos = {}
        self.queue = {"pending": [], "completed": [], "failed": []}

    def get_downloaded_videos(self) -> list:
        """Get list of all downloaded video IDs."""
        return [vid for vid, data in self.videos.items() if data.get("downloaded")]


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
                logger.error(f"yt-dlp error: {result.stderr[:200]}")

        except subprocess.TimeoutExpired:
            logger.error(f"Download timeout for {video_id}")
        except Exception as e:
            logger.error(f"Download error: {e}")

        return None


def load_config(config_path: str = "config.json") -> dict:
    path = Path(config_path)
    if not path.exists():
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def cmd_sync(client: TikTokClient, store: DataStore, collection_limit: Optional[int] = None, video_limit: Optional[int] = None):
    """Sync collections and videos, queue new downloads."""
    logger.info("=== SYNC MODE ===")

    # Step 1: Fetch collections
    logger.info("Fetching collections...")
    collections = client.get_collections()
    logger.info(f"Found {len(collections)} collections")

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

    deleted_count = 0

    for coll in collections_to_process:
        coll_id = coll["id"]
        coll_name = coll["name"]
        logger.info(f"Fetching videos from: {coll_name}")

        videos = client.get_collection_videos(coll_id, coll_name, limit=video_limit)
        logger.info(f"  Found {len(videos)} videos")

        # Track which video IDs we found in this sync
        found_video_ids = set()

        for vid in videos:
            vid_id = vid.get("id")
            if not vid_id:
                continue

            found_video_ids.add(vid_id)
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
                "deleted_from_tiktok": False,  # Mark as not deleted since we found it
            }

            is_new = store.add_video(vid_id, video_data)
            if is_new:
                new_videos += 1
                if store.queue_download(vid_id, video_data):
                    queued += 1

        # Check for videos that were in this collection but are now missing
        for vid_id, vid_data in store.videos.items():
            if vid_data.get("collection_id") == coll_id:
                if vid_id not in found_video_ids and not vid_data.get("deleted_from_tiktok"):
                    vid_data["deleted_from_tiktok"] = True
                    vid_data["deleted_at"] = datetime.now().isoformat()
                    deleted_count += 1
                    logger.info(f"  Marked as deleted: {vid_id}")

    store.save_videos()
    store.save_queue()

    logger.info("=== SYNC COMPLETE ===")
    logger.info(f"New videos found: {new_videos}")
    logger.info(f"Queued for download: {queued}")
    logger.info(f"Marked as deleted from TikTok: {deleted_count}")
    logger.info(f"Pending downloads: {len(store.get_pending_downloads())}")


def cmd_download(store: DataStore, downloader: VideoDownloader, limit: Optional[int] = None):
    """Process download queue."""
    logger.info("=== DOWNLOAD MODE ===")

    pending = store.get_pending_downloads()
    if not pending:
        logger.info("No pending downloads.")
        return

    to_process = pending[:limit] if limit else pending
    logger.info(f"Processing {len(to_process)} downloads...")

    for i, item in enumerate(to_process, 1):
        vid_id = item["id"]
        author = item.get("author", "unknown")
        collection = item.get("collection", "uncategorized")
        desc = item.get("desc", "")

        logger.info(f"[{i}/{len(to_process)}] Downloading {vid_id} from {collection} (@{author})")

        path = downloader.download(vid_id, author, collection, desc)

        if path:
            store.mark_downloaded(vid_id, path)
            logger.info(f"  Success: {path}")
        else:
            store.mark_failed(vid_id, "Download failed")
            logger.warning("  Failed!")

        store.save_queue()
        store.save_videos()

    logger.info("=== DOWNLOAD COMPLETE ===")
    logger.info(f"Remaining in queue: {len(store.get_pending_downloads())}")


def cmd_watch(client: TikTokClient, store: DataStore, downloader: VideoDownloader, interval: int):
    """Watch mode: periodic sync + download."""
    logger.info(f"=== WATCH MODE (every {interval} minutes) ===")
    logger.info("Press Ctrl+C to stop")

    while True:
        try:
            logger.info("Starting sync cycle...")

            # Sync first
            cmd_sync(client, store)

            # Then download
            cmd_download(store, downloader)

            logger.info(f"Next check in {interval} minutes...")
            time.sleep(interval * 60)

        except KeyboardInterrupt:
            logger.info("Stopping...")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            logger.info(f"Retrying in {interval} minutes...")
            time.sleep(interval * 60)


def cmd_delete(store: DataStore, video_ids: list, delete_all: bool = False):
    """Delete videos and their files."""
    import shutil

    logger.info("=== DELETE MODE ===")

    if delete_all:
        # Get all video IDs (not just downloaded)
        video_ids = list(store.videos.keys())
        if not video_ids and not store.collections:
            logger.info("No data to delete.")
            return
        logger.info(f"Deleting all data ({len(video_ids)} videos, {len(store.collections)} collections)...")

        # Delete all video folders
        deleted = 0
        for vid_id in video_ids:
            path = store.delete_video(vid_id)
            if path:
                deleted += 1

        # Clean up any remaining collection folders in the download directory
        for item in store.data_dir.iterdir():
            if item.is_dir() and item.name not in [".", ".."]:
                # Skip if it's not a collection folder (check if it contains video folders)
                try:
                    shutil.rmtree(item)
                    logger.info(f"  Removed folder: {item.name}")
                except Exception:
                    pass

        # Clear all tracking data
        store.clear_all_data()
        store.save_collections()
        store.save_videos()
        store.save_queue()

        logger.info("=== DELETE COMPLETE ===")
        logger.info(f"Deleted {deleted} video(s) and all tracking data")
        return

    elif not video_ids:
        logger.info("No video IDs specified. Use --delete <id> or --delete-all")
        return

    deleted = 0
    for vid_id in video_ids:
        path = store.delete_video(vid_id)
        if path:
            logger.info(f"  Deleted: {vid_id} ({path})")
            deleted += 1
        else:
            logger.info(f"  Removed from tracking: {vid_id}")

    store.save_videos()
    store.save_queue()

    logger.info("=== DELETE COMPLETE ===")
    logger.info(f"Deleted {deleted} video(s) and files")


def cmd_status(store: DataStore):
    """Show current status."""
    deleted_videos = [v for v in store.videos.values() if v.get("deleted_from_tiktok")]

    logger.info("=== STATUS ===")
    logger.info(f"Collections: {len(store.collections)}")
    logger.info(f"Videos tracked: {len(store.videos)}")
    logger.info(f"Deleted from TikTok: {len(deleted_videos)}")
    logger.info(f"Pending downloads: {len(store.queue['pending'])}")
    logger.info(f"Completed downloads: {len(store.queue['completed'])}")
    logger.info(f"Failed downloads: {len(store.queue['failed'])}")

    # Show download state summary by collection
    if store.collections:
        logger.info("--- Collections Overview ---")
        for coll_id, coll in store.collections.items():
            coll_name = coll.get("name", "Unknown")
            # Count videos in this collection
            coll_videos = [v for v in store.videos.values() if v.get("collection_id") == coll_id]
            downloaded = sum(1 for v in coll_videos if v.get("downloaded"))
            deleted = sum(1 for v in coll_videos if v.get("deleted_from_tiktok"))
            total = len(coll_videos)
            status = f"{downloaded}/{total} downloaded"
            if deleted:
                status += f", {deleted} deleted"
            logger.info(f"  {coll_name}: {status}")

    if deleted_videos:
        logger.info("--- Deleted from TikTok ---")
        for vid in deleted_videos[:10]:
            vid_id = vid.get("id", "unknown")
            coll_name = vid.get("collection_name", "unknown")
            downloaded = "saved" if vid.get("downloaded") else "NOT saved"
            logger.info(f"  [{coll_name}] {vid_id} - {downloaded}")
        if len(deleted_videos) > 10:
            logger.info(f"  ... and {len(deleted_videos) - 10} more")

    if store.queue["pending"]:
        logger.info("--- Pending Downloads ---")
        for item in store.queue["pending"][:10]:
            logger.info(f"  [{item['collection']}] {item['id']}")
        if len(store.queue["pending"]) > 10:
            logger.info(f"  ... and {len(store.queue['pending']) - 10} more")

    if store.queue["failed"]:
        logger.info("--- Failed Downloads ---")
        for item in store.queue["failed"][:5]:
            error = item.get("error", "Unknown error")
            logger.info(f"  [{item['collection']}] {item['id']} - {error}")
        if len(store.queue["failed"]) > 5:
            logger.info(f"  ... and {len(store.queue['failed']) - 5} more")


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
    parser.add_argument("--delete", nargs="+", metavar="VIDEO_ID", help="Delete specific video(s) by ID")
    parser.add_argument("--delete-all", action="store_true", help="Delete all downloaded videos")
    args = parser.parse_args()

    logger.info("TikTok Collections Monitor")
    logger.info("-" * 40)

    config = load_config()
    sessionid = config.get("cookies", {}).get("sessionid", "")
    if not sessionid:
        logger.error("No sessionid found in config.json")
        sys.exit(1)

    download_dir = config.get("download_dir", "./downloads")

    # Initialize
    client = TikTokClient(sessionid)
    store = DataStore(download_dir)
    downloader = VideoDownloader(download_dir)

    logger.info(f"Data/Download dir: {download_dir}")

    if args.status:
        cmd_status(store)
    elif args.delete or args.delete_all:
        cmd_delete(store, args.delete or [], args.delete_all)
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
