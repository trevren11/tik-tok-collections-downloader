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
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        self._save_lock = threading.Lock()  # Prevent concurrent file writes

        self.collections_file = self.data_dir / "collections.json"
        self.videos_file = self.data_dir / "videos.json"
        self.queue_file = self.data_dir / "download_queue.json"
        self.data_js_file = self.data_dir / "data.js"
        self.viewer_file = self.data_dir / "viewer.html"

        self._corruption_detected = False
        self.collections = self._load(self.collections_file, {})
        self.videos = self._load(self.videos_file, {})
        self.queue = self._load(self.queue_file, {"pending": [], "completed": [], "failed": []})

        # Only scan disk if corruption was detected (expensive on network drives)
        if self._corruption_detected:
            logger.info("Corruption detected, reconciling with disk...")
            self._reconcile_with_disk()

        # Write viewer HTML on startup
        self._write_viewer_html()
        self._write_data_js()

    def _load(self, path: Path, default: dict) -> dict:
        if path.exists():
            try:
                with open(path) as f:
                    content = f.read()
                    if not content.strip():
                        self._corruption_detected = True
                        return default
                    return json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"Corrupted JSON file: {path}, using default")
                self._corruption_detected = True
                return default
        return default

    def _reconcile_with_disk(self):
        """Scan disk and update download status, clean up incomplete downloads."""
        import shutil
        fixed_count = 0
        cleaned_count = 0

        collection_dirs = [d for d in self.data_dir.iterdir()
                          if d.is_dir() and not d.name.startswith(".")]

        for collection_dir in collection_dirs:
            for video_dir in collection_dir.iterdir():
                if not video_dir.is_dir():
                    continue
                video_id = video_dir.name

                # Check for .part files (incomplete downloads)
                part_files = list(video_dir.glob("*.part"))
                video_file = None
                for f in video_dir.iterdir():
                    if f.suffix.lower() in [".mp4", ".webm", ".mkv"]:
                        video_file = f
                        break

                # Clean up incomplete downloads
                if part_files and not video_file:
                    # Only .part files, no complete video - delete folder
                    shutil.rmtree(video_dir)
                    # Mark as not downloaded if in videos
                    if video_id in self.videos:
                        self.videos[video_id]["downloaded"] = False
                        self.videos[video_id]["download_path"] = None
                    # Remove from completed queue
                    if video_id in self.queue["completed"]:
                        self.queue["completed"].remove(video_id)
                    cleaned_count += 1
                    continue

                # Delete any leftover .part files if video is complete
                for pf in part_files:
                    pf.unlink()

                # Update download status if video exists
                if video_file and video_id in self.videos:
                    if not self.videos[video_id].get("downloaded"):
                        self.videos[video_id]["downloaded"] = True
                        self.videos[video_id]["download_path"] = str(video_file)
                        if video_id not in self.queue["completed"]:
                            self.queue["completed"].append(video_id)
                        fixed_count += 1

        if fixed_count > 0 or cleaned_count > 0:
            logger.info(f"Reconciled {fixed_count} videos, cleaned {cleaned_count} incomplete")
            self.save_videos()
            self.save_queue()

    def _save(self, path: Path, data: dict):
        """Atomically save JSON data to prevent corruption."""
        with self._save_lock:
            # Write to temp file first, then rename (atomic on most filesystems)
            temp_path = path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(path)  # Atomic rename

    def _write_data_js(self):
        """Write data.js for the static viewer (allows viewing without a server)."""
        with self._save_lock:
            content = "// Auto-generated by tiktok_monitor.py - do not edit\n"
            content += f"window.collectionsData = {json.dumps(self.collections)};\n"
            content += f"window.videosData = {json.dumps(self.videos)};\n"
            # Atomic write
            temp_path = self.data_js_file.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                f.write(content)
            temp_path.replace(self.data_js_file)

    def _write_viewer_html(self):
        """Write the static viewer HTML file."""
        # Get viewer.html from the same directory as this script
        script_dir = Path(__file__).parent
        viewer_src = script_dir / "viewer.html"
        if viewer_src.exists():
            import shutil
            shutil.copy(viewer_src, self.viewer_file)
            logger.info(f"Viewer written to: {self.viewer_file}")
        else:
            logger.warning(f"Viewer source not found at: {viewer_src}")

    def save_collections(self):
        self._save(self.collections_file, self.collections)
        self._write_data_js()
        self._write_available_collections()

    def _write_available_collections(self):
        """Write a reference file listing all available collections for exclusion config."""
        available_file = self.data_dir / "available_collections.json"
        collections_list = []
        for coll_id, coll in self.collections.items():
            collections_list.append({
                "id": coll_id,
                "name": coll.get("name", "Unknown"),
                "total": coll.get("total", 0),
            })
        # Sort by name for easier reading
        collections_list.sort(key=lambda x: x["name"].lower())
        self._save(available_file, {
            "_comment": "Reference file for exclude_collections config. Use 'id' or 'name' values.",
            "collections": collections_list,
        })

    def save_videos(self):
        self._save(self.videos_file, self.videos)
        self._write_data_js()

    def save_queue(self):
        self._save(self.queue_file, self.queue)

    def update_collection(self, coll_id: str, coll_data: dict):
        self.collections[coll_id] = {
            **coll_data,
            "updated_at": datetime.now().isoformat(),
        }

    def add_video(self, video_id: str, video_data: dict):
        is_new = video_id not in self.videos
        if is_new:
            self.videos[video_id] = {
                **video_data,
                "cached_at": datetime.now().isoformat(),
            }
        else:
            # Preserve existing download info when updating
            existing = self.videos[video_id]
            self.videos[video_id] = {
                **video_data,
                "cached_at": datetime.now().isoformat(),
                "downloaded": existing.get("downloaded", False),
                "download_path": existing.get("download_path"),
                "downloaded_at": existing.get("downloaded_at"),
            }
        return is_new

    def queue_download(self, video_id: str, video_data: dict):
        # Don't queue if already in queue or completed
        if video_id in [v["id"] for v in self.queue["pending"]]:
            return False
        if video_id in self.queue["completed"]:
            return False

        # Don't queue if already marked as downloaded in videos dict
        if video_id in self.videos and self.videos[video_id].get("downloaded"):
            return False

        # Don't queue if video file already exists on disk
        collection_name = video_data.get("collection_name", "uncategorized")
        safe_collection = "".join(c if c.isalnum() or c in " -_" else "_" for c in collection_name)
        video_dir = self.data_dir / safe_collection / video_id
        if video_dir.exists():
            for f in video_dir.iterdir():
                if f.suffix.lower() in [".mp4", ".webm", ".mkv"]:
                    # File exists, mark as downloaded and skip
                    if video_id in self.videos:
                        self.videos[video_id]["downloaded"] = True
                        self.videos[video_id]["download_path"] = str(f)
                    if video_id not in self.queue["completed"]:
                        self.queue["completed"].append(video_id)
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

    def verify_downloads(self) -> dict:
        """
        Verify download status by checking actual files on disk.
        Returns dict with counts of fixed records.
        """
        fixed_downloaded = 0
        fixed_missing = 0

        for vid_id, vid_data in self.videos.items():
            download_path = vid_data.get("download_path")
            marked_downloaded = vid_data.get("downloaded", False)

            # Check if file actually exists
            file_exists = download_path and Path(download_path).exists()

            if marked_downloaded and not file_exists:
                # Marked as downloaded but file is missing
                vid_data["downloaded"] = False
                vid_data["download_path"] = None
                fixed_missing += 1
            elif not marked_downloaded and file_exists:
                # File exists but not marked as downloaded
                vid_data["downloaded"] = True
                fixed_downloaded += 1

        if fixed_downloaded > 0 or fixed_missing > 0:
            self.save_videos()

        return {"fixed_downloaded": fixed_downloaded, "fixed_missing": fixed_missing}

    def count_actual_downloads(self) -> dict:
        """
        Count actual video files on disk by scanning the download directory.
        Returns dict with collection_name -> count mapping and _total.
        """
        counts = {"_total": 0}

        # Scan all subdirectories (collections) in the data_dir
        for collection_dir in self.data_dir.iterdir():
            if not collection_dir.is_dir():
                continue
            # Skip hidden directories
            if collection_dir.name.startswith("."):
                continue

            collection_count = 0
            # Each collection contains video_id folders
            for video_dir in collection_dir.iterdir():
                if not video_dir.is_dir():
                    continue
                # Check if there's a video file in this folder
                for f in video_dir.iterdir():
                    if f.suffix.lower() in [".mp4", ".webm", ".mkv"]:
                        collection_count += 1
                        counts["_total"] += 1
                        break  # Only count one video per folder

            if collection_count > 0:
                counts[collection_dir.name] = collection_count

        return counts


class TikTokClient:
    """Client for fetching TikTok data via browser automation."""

    def __init__(self, sessionid: str):
        self.sessionid = sessionid

    def _create_context(self, playwright):
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Denver",
            color_scheme="dark",
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )
        context.add_cookies([
            {"name": "sessionid", "value": self.sessionid, "domain": ".tiktok.com", "path": "/"},
            {"name": "sessionid_ss", "value": self.sessionid, "domain": ".tiktok.com", "path": "/"},
        ])
        return browser, context

    def get_collections(self) -> list:
        """Fetch all collections."""
        collections = []

        logger.info("Launching browser to fetch collections...")
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
                                    logger.info(f"  Found collection: {coll.get('name')} ({coll.get('total', 0)} videos)")
                    except Exception:
                        pass

            page.on("response", handle_response)

            # Navigate to profile page which should trigger collections API
            try:
                page.goto("https://www.tiktok.com/@me", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                # Check page title to detect issues
                title = page.title()
                logger.info(f"  Page loaded: {title[:50]}")

                if "captcha" in title.lower() or "verify" in title.lower():
                    logger.error("TikTok is showing a captcha/verification page - session may be flagged")
                elif "login" in title.lower():
                    logger.error("TikTok is showing login page - sessionid may be expired")

                # Try clicking on Collections tab if no collections found yet
                if not collections:
                    try:
                        # Look for collections/saved tab
                        collections_selectors = [
                            '[data-e2e="saved-tab"]',
                            'a[href*="collection"]',
                            'span:has-text("Collections")',
                            'span:has-text("Saved")',
                        ]
                        for selector in collections_selectors:
                            if page.locator(selector).count() > 0:
                                logger.info(f"  Clicking collections tab: {selector}")
                                page.locator(selector).first.click()
                                page.wait_for_timeout(3000)
                                break
                    except Exception as e:
                        logger.warning(f"  Could not click collections tab: {e}")

                # Wait for API responses
                page.wait_for_timeout(3000)

            except Exception as e:
                logger.warning(f"Navigation issue (may still work): {e}")
                if collections:
                    logger.info(f"  Got {len(collections)} collections despite navigation issue")

            browser.close()

        return collections

    def get_collection_videos(self, collection_id: str, collection_name: str, limit: Optional[int] = None, quick_check: bool = False) -> list:
        """Fetch videos in a collection.

        Args:
            quick_check: If True, only fetch first ~30 videos (for checking if new content exists)
        """
        videos = []
        seen_ids = set()

        with sync_playwright() as p:
            browser, context = self._create_context(p)
            page = context.new_page()

            def handle_response(response):
                if "collection/item_list" in response.url or "collect/item_list" in response.url:
                    try:
                        data = response.json()
                        if "itemList" in data:
                            new_count = 0
                            for item in data["itemList"]:
                                vid_id = item.get("id")
                                if vid_id and vid_id not in seen_ids:
                                    seen_ids.add(vid_id)
                                    videos.append(item)
                                    new_count += 1
                            if new_count > 0:
                                logger.info(f"    [{collection_name}] Loaded {len(videos)} videos...")
                    except Exception:
                        pass

            page.on("response", handle_response)

            url = f"https://www.tiktok.com/@me/collection/{collection_name}-{collection_id}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                # Wait longer for the video grid to load before scrolling
                page.wait_for_timeout(5000)

                # Try to wait for video grid to appear
                try:
                    page.wait_for_selector('[data-e2e="user-post-item"], [class*="DivItemContainer"]', timeout=10000)
                    logger.info(f"    [{collection_name}] Video grid loaded")
                except Exception:
                    logger.warning(f"    [{collection_name}] Video grid not found, page may not have loaded correctly")
            except Exception as e:
                logger.warning(f"  [{collection_name}] Navigation issue: {e}")

            # Scroll to load videos - quick_check only does minimal scrolling
            scroll_count = 0
            max_scrolls = 3 if quick_check else 500  # quick_check: ~30 videos, full: ~10,000+
            last_height = 0

            try:
                while scroll_count < max_scrolls:
                    prev_count = len(videos)

                    # Scroll to bottom
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2000)
                    scroll_count += 1

                    # Check if page height changed (true indicator of more content)
                    current_height = page.evaluate("document.body.scrollHeight")

                    if len(videos) == prev_count and current_height == last_height:
                        # No new videos AND page didn't grow - try a few more times
                        page.wait_for_timeout(1000)
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(2000)
                        final_height = page.evaluate("document.body.scrollHeight")

                        if final_height == current_height and len(videos) == prev_count:
                            logger.info(f"    [{collection_name}] Reached bottom at {len(videos)} videos")
                            break

                    last_height = current_height

                    if limit and len(videos) >= limit:
                        break
            except Exception as e:
                # Keep whatever videos we captured even if scrolling fails
                logger.warning(f"    [{collection_name}] Scrolling error (keeping {len(videos)} videos): {e}")

            browser.close()

        return videos[:limit] if limit else videos

    def get_favorites(self, limit: Optional[int] = None) -> list:
        """Fetch favorited/liked videos (not in any specific collection)."""
        videos = []

        logger.info("Launching browser to fetch favorites...")
        with sync_playwright() as p:
            browser, context = self._create_context(p)
            page = context.new_page()

            def handle_response(response):
                # TikTok uses various endpoints for favorites/liked videos
                if any(x in response.url for x in ["favorite/item_list", "favorite_item_list", "liked/item_list", "like-list"]):
                    try:
                        data = response.json()
                        if "itemList" in data:
                            videos.extend(data["itemList"])
                            logger.info(f"    [Favorites] Loaded {len(videos)} videos...")
                    except Exception:
                        pass

            page.on("response", handle_response)

            # Navigate to favorites page
            try:
                page.goto("https://www.tiktok.com/@me", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning(f"  [Favorites] Navigation issue: {e}")

            # Try to click on the Favorites tab if it exists
            try:
                # Look for favorites tab - TikTok UI varies but typically has a favorites/liked tab
                favorites_selectors = [
                    'div[data-e2e="favorites-tab"]',
                    'a[href*="favorites"]',
                    'span:has-text("Favorites")',
                    'div:has-text("Favorites"):not(:has(*))',
                ]
                for selector in favorites_selectors:
                    try:
                        if page.locator(selector).count() > 0:
                            page.locator(selector).first.click()
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            # Scroll to load more
            scroll_count = 0
            max_scrolls = 50 if not limit else (limit // 30) + 2

            try:
                while scroll_count < max_scrolls:
                    prev_count = len(videos)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)
                    scroll_count += 1

                    if len(videos) == prev_count:
                        break
                    if limit and len(videos) >= limit:
                        break
            except Exception as e:
                # Keep whatever videos we captured even if scrolling fails
                logger.warning(f"    [Favorites] Scrolling error (keeping {len(videos)} videos): {e}")

            browser.close()

        return videos[:limit] if limit else videos


class VideoDownloader:
    """Downloads TikTok videos using yt-dlp."""

    def __init__(self, download_dir: str, cookies: dict = None, max_workers: int = 10):
        self.download_dir = Path(download_dir)
        self.cookies = cookies or {}
        self.max_workers = max_workers
        self._cookie_header = self._build_cookie_header()

    def _build_cookie_header(self) -> str:
        """Build cookie header string for yt-dlp."""
        if not self.cookies:
            return ""
        parts = [f"{name}={value}" for name, value in self.cookies.items() if value]
        return "; ".join(parts)

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
            cmd = [
                sys.executable, "-m", "yt_dlp",
                "--no-warnings",
                "-o", output_template,
                "--write-info-json",
            ]

            # Pass cookies via HTTP header instead of file
            if self._cookie_header:
                cmd.extend(["--add-header", f"Cookie: {self._cookie_header}"])

            cmd.append(video_url)

            result = subprocess.run(
                cmd,
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


def _download_collection_videos(store: DataStore, downloader: "VideoDownloader", collection_id: str, max_parallel: int = 10) -> int:
    """Download pending videos for a specific collection with parallel downloads. Returns count of successful downloads."""
    pending = [v for v in store.get_pending_downloads() if v.get("collection") == store.collections.get(collection_id, {}).get("name") or (collection_id == "_favorites" and v.get("collection") == "Favorites")]

    if not pending:
        return 0

    success_count = [0]  # Use list to allow modification in nested scope
    lock = threading.Lock()

    def download_worker(item, index):
        """Worker function to download a single video."""
        vid_id = item["id"]
        author = item.get("author", "unknown")
        collection = item.get("collection", "uncategorized")
        desc = item.get("desc", "")

        logger.info(f"    [{index}/{len(pending)}] Downloading {vid_id} (@{author})")

        path = downloader.download(vid_id, author, collection, desc)

        return {
            "vid_id": vid_id,
            "path": path,
            "success": path is not None,
        }

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        future_to_item = {
            executor.submit(download_worker, item, i): item
            for i, item in enumerate(pending, 1)
        }

        for future in as_completed(future_to_item):
            result = future.result()
            vid_id = result["vid_id"]

            with lock:
                if result["success"]:
                    store.mark_downloaded(vid_id, result["path"])
                    logger.info(f"      Success: {result['path']}")
                    success_count[0] += 1
                else:
                    store.mark_failed(vid_id, "Download failed")
                    logger.warning(f"      Failed: {vid_id}")

                store.save_queue()
                store.save_videos()

    return success_count[0]


def _process_collection_videos(store: DataStore, coll_id: str, coll_name: str, videos: list) -> tuple:
    """Process fetched videos for a collection. Returns (new_count, queued_count, deleted_count, found_ids)."""
    found_video_ids = set()
    new_count = 0
    queued_count = 0
    deleted_count = 0

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
            "deleted_from_tiktok": False,
        }

        is_new = store.add_video(vid_id, video_data)
        if is_new:
            new_count += 1
            if store.queue_download(vid_id, video_data):
                queued_count += 1

    # Check for videos that were in this collection but are now missing
    # SANITY CHECK: Only mark as deleted if we actually loaded some videos
    # This prevents mass false-deletions when the page fails to load
    if len(found_video_ids) > 0:
        for vid_id, vid_data in list(store.videos.items()):
            if vid_data.get("collection_id") == coll_id:
                if vid_id not in found_video_ids and not vid_data.get("deleted_from_tiktok"):
                    vid_data["deleted_from_tiktok"] = True
                    vid_data["deleted_at"] = datetime.now().isoformat()
                    deleted_count += 1
                    logger.info(f"  [{coll_name}] Marked as deleted: {vid_id}")
    else:
        # Count how many we would have marked as deleted
        existing_count = sum(1 for v in store.videos.values() if v.get("collection_id") == coll_id and not v.get("deleted_from_tiktok"))
        if existing_count > 0:
            logger.warning(f"  [{coll_name}] Skipping deletion check - no videos loaded from API (would have marked {existing_count} as deleted)")

    return new_count, queued_count, deleted_count, found_video_ids


def cmd_sync(client: TikTokClient, store: DataStore, collection_limit: Optional[int] = None, video_limit: Optional[int] = None, downloader: Optional[VideoDownloader] = None, max_parallel: int = 10, exclude_collections: Optional[list] = None):
    """Sync collections and videos, queue new downloads. Optionally download after each collection."""
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

    # Step 2: Fetch videos for each collection (in parallel)
    collections_to_process = list(store.collections.values())

    # Filter out excluded collections (by name or ID)
    if exclude_collections:
        exclude_set = set(exclude_collections)
        before_count = len(collections_to_process)
        collections_to_process = [
            c for c in collections_to_process
            if c.get("id") not in exclude_set and c.get("name") not in exclude_set
        ]
        excluded_count = before_count - len(collections_to_process)
        if excluded_count > 0:
            logger.info(f"Excluding {excluded_count} collection(s) per config")

    if collection_limit:
        collections_to_process = collections_to_process[:collection_limit]

    new_videos = 0
    downloaded = 0
    deleted_count = 0

    logger.info(f"Fetching videos from {len(collections_to_process)} collections...")

    # Fetch collections sequentially (each needs its own browser instance)
    for i, coll in enumerate(collections_to_process, 1):
        coll_id = coll["id"]
        coll_name = coll["name"]

        # Check if this collection has been synced before
        existing_videos = [v for v in store.videos.values() if v.get("collection_id") == coll_id]
        has_been_synced = len(existing_videos) > 0

        try:
            if has_been_synced:
                # Quick check: only fetch first ~30 videos to see if there's new content
                logger.info(f"  [{i}/{len(collections_to_process)}] Quick check: {coll_name}")
                preview_videos = client.get_collection_videos(coll_id, coll_name, quick_check=True)

                # Check if any preview videos are new
                existing_ids = set(store.videos.keys())
                new_in_preview = [v for v in preview_videos if v.get("id") not in existing_ids]

                if not new_in_preview:
                    logger.info(f"  [{i}/{len(collections_to_process)}] {coll_name}: No new videos in recent {len(preview_videos)}, skipping full sync")
                    continue
                else:
                    logger.info(f"  [{i}/{len(collections_to_process)}] {coll_name}: Found {len(new_in_preview)} new in preview, doing full sync...")
                    videos = client.get_collection_videos(coll_id, coll_name, limit=video_limit)
            else:
                # First time syncing this collection - fetch all
                logger.info(f"  [{i}/{len(collections_to_process)}] Fetching: {coll_name}")
                videos = client.get_collection_videos(coll_id, coll_name, limit=video_limit)

            logger.info(f"  [{i}/{len(collections_to_process)}] {coll_name}: Found {len(videos)} videos")
        except Exception as e:
            logger.error(f"  [{i}/{len(collections_to_process)}] Error fetching {coll_name}: {e}")
            continue

        # Process the fetched videos
        new_count, queued_count, del_count, _ = _process_collection_videos(
            store, coll_id, coll_name, videos
        )
        new_videos += new_count
        deleted_count += del_count

        # Download immediately if downloader is provided (parallel downloads still work)
        if downloader and queued_count > 0:
            store.save_videos()
            store.save_queue()
            logger.info(f"  Downloading {queued_count} new videos from {coll_name}...")
            downloaded += _download_collection_videos(store, downloader, coll_id, max_parallel)

    # Step 3: Fetch favorited videos (not in any collection)
    logger.info("Fetching favorited videos (not in collections)...")
    favorites = client.get_favorites(limit=video_limit)
    logger.info(f"Found {len(favorites)} favorited videos")

    # Track which favorites we found
    found_favorite_ids = set()
    favorites_new = 0
    favorites_queued = 0

    for vid in favorites:
        vid_id = vid.get("id")
        if not vid_id:
            continue

        # Skip if this video is already in a collection
        if vid_id in store.videos and store.videos[vid_id].get("collection_id") != "_favorites":
            continue

        found_favorite_ids.add(vid_id)
        author = vid.get("author", {}).get("uniqueId", "unknown")
        video_data = {
            "id": vid_id,
            "author": author,
            "desc": vid.get("desc", ""),
            "collection_id": "_favorites",
            "collection_name": "Favorites",
            "url": f"https://www.tiktok.com/@{author}/video/{vid_id}",
            "create_time": vid.get("createTime"),
            "stats": vid.get("stats", {}),
            "deleted_from_tiktok": False,
        }

        is_new = store.add_video(vid_id, video_data)
        if is_new:
            favorites_new += 1
            new_videos += 1
            if store.queue_download(vid_id, video_data):
                favorites_queued += 1

    # Check for favorites that are now missing
    for vid_id, vid_data in store.videos.items():
        if vid_data.get("collection_id") == "_favorites":
            if vid_id not in found_favorite_ids and not vid_data.get("deleted_from_tiktok"):
                vid_data["deleted_from_tiktok"] = True
                vid_data["deleted_at"] = datetime.now().isoformat()
                deleted_count += 1
                logger.info(f"  Marked favorite as deleted: {vid_id}")

    if favorites_new > 0:
        logger.info(f"  New favorites: {favorites_new}, queued: {favorites_queued}")

    # Download favorites immediately if downloader is provided
    if downloader and favorites_queued > 0:
        store.save_videos()
        store.save_queue()
        logger.info(f"  Downloading {favorites_queued} new favorites...")
        downloaded += _download_collection_videos(store, downloader, "_favorites")

    store.save_videos()
    store.save_queue()

    logger.info("=== SYNC COMPLETE ===")
    logger.info(f"New videos found: {new_videos}")
    logger.info(f"Downloaded: {downloaded}")
    logger.info(f"Marked as deleted from TikTok: {deleted_count}")
    logger.info(f"Pending downloads: {len(store.get_pending_downloads())}")


def cmd_download(store: DataStore, downloader: VideoDownloader, limit: Optional[int] = None, max_parallel: int = 10):
    """Process download queue with parallel downloads."""
    logger.info("=== DOWNLOAD MODE ===")

    pending = store.get_pending_downloads()
    if not pending:
        logger.info("No pending downloads.")
        return

    to_process = pending[:limit] if limit else pending
    logger.info(f"Processing {len(to_process)} downloads (up to {max_parallel} in parallel)...")

    success_count = 0
    fail_count = 0
    lock = threading.Lock()

    def download_worker(item, index):
        """Worker function to download a single video."""
        vid_id = item["id"]
        author = item.get("author", "unknown")
        collection = item.get("collection", "uncategorized")
        desc = item.get("desc", "")

        logger.info(f"[{index}/{len(to_process)}] Downloading {vid_id} from {collection} (@{author})")

        path = downloader.download(vid_id, author, collection, desc)

        return {
            "vid_id": vid_id,
            "path": path,
            "success": path is not None,
        }

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        # Submit all downloads
        future_to_item = {
            executor.submit(download_worker, item, i): item
            for i, item in enumerate(to_process, 1)
        }

        # Process results as they complete
        for future in as_completed(future_to_item):
            result = future.result()
            vid_id = result["vid_id"]

            with lock:
                if result["success"]:
                    store.mark_downloaded(vid_id, result["path"])
                    logger.info(f"  Success: {result['path']}")
                    success_count += 1
                else:
                    store.mark_failed(vid_id, "Download failed")
                    logger.warning(f"  Failed: {vid_id}")
                    fail_count += 1

                store.save_queue()
                store.save_videos()

    logger.info("=== DOWNLOAD COMPLETE ===")
    logger.info(f"Downloaded: {success_count}, Failed: {fail_count}")
    logger.info(f"Remaining in queue: {len(store.get_pending_downloads())}")


def cmd_watch(client: TikTokClient, store: DataStore, downloader: VideoDownloader, interval: int, exclude_collections: Optional[list] = None, download_limit: Optional[int] = None, collection_limit: Optional[int] = None, video_limit: Optional[int] = None):
    """Watch mode: periodic sync + download."""
    logger.info(f"=== WATCH MODE (every {interval} minutes) ===")
    logger.info("Press Ctrl+C to stop")
    logger.info(f"Current status: {len(store.videos)} videos tracked, {len(store.queue['pending'])} pending")

    # On startup, immediately process any pending downloads from previous runs
    # This allows resuming downloads without waiting for a full sync
    pending_count = len(store.queue['pending'])
    if pending_count > 0:
        logger.info(f"=== RESUMING {pending_count} PENDING DOWNLOADS ===")
        cmd_download(store, downloader, limit=download_limit)
        logger.info("=== RESUME COMPLETE ===")

    while True:
        try:
            logger.info("Starting sync cycle...")

            # Sync and download - downloads happen after each collection
            cmd_sync(client, store, collection_limit=collection_limit, video_limit=video_limit, downloader=downloader, exclude_collections=exclude_collections)

            # Process any remaining downloads (e.g., from previous failed attempts)
            cmd_download(store, downloader, limit=download_limit)

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
    # Verify downloads against actual files on disk
    logger.info("Verifying downloads against disk...")
    verify_result = store.verify_downloads()
    if verify_result["fixed_downloaded"] > 0 or verify_result["fixed_missing"] > 0:
        logger.info(f"  Fixed {verify_result['fixed_downloaded']} unmarked downloads, {verify_result['fixed_missing']} missing files")

    # Get actual download counts from disk
    actual_counts = store.count_actual_downloads()

    deleted_videos = [v for v in store.videos.values() if v.get("deleted_from_tiktok")]

    logger.info("=== STATUS ===")
    logger.info(f"Collections: {len(store.collections)}")
    logger.info(f"Videos tracked: {len(store.videos)}")
    logger.info(f"Actually downloaded (verified): {actual_counts['_total']}")
    logger.info(f"Deleted from TikTok: {len(deleted_videos)}")
    logger.info(f"Pending downloads: {len(store.queue['pending'])}")
    logger.info(f"Failed downloads: {len(store.queue['failed'])}")

    # Show download state summary by collection
    if store.collections:
        logger.info("--- Collections Overview ---")
        for coll_id, coll in store.collections.items():
            coll_name = coll.get("name", "Unknown")
            # Count videos in this collection
            coll_videos = [v for v in store.videos.values() if v.get("collection_id") == coll_id]
            # Get folder name (sanitized version of collection name)
            safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in coll_name)
            downloaded = actual_counts.get(safe_name, 0)  # Use folder name for disk count
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

    # Environment variables override config (useful for Docker/Unraid)
    sessionid = os.environ.get("TIKTOK_SESSION_ID") or config.get("sessionid", "")
    if not sessionid:
        logger.error("No sessionid found in TIKTOK_SESSION_ID env var or config.json")
        sys.exit(1)

    download_dir = os.environ.get("DOWNLOAD_DIR") or config.get("download_dir", "./downloads")
    exclude_collections = config.get("exclude_collections", [])

    # Limit environment variables (useful for testing in Docker/Unraid)
    env_download_limit = os.environ.get("DOWNLOAD_LIMIT")
    env_collection_limit = os.environ.get("COLLECTION_LIMIT")
    env_video_limit = os.environ.get("VIDEO_LIMIT")

    # Initialize
    client = TikTokClient(sessionid)
    store = DataStore(download_dir)
    cookies = {"sessionid": sessionid}
    downloader = VideoDownloader(download_dir, cookies)

    logger.info(f"Data/Download dir: {download_dir}")

    # Environment variables override command line args (useful for Docker/Unraid testing)
    download_limit = int(env_download_limit) if env_download_limit else args.limit
    collection_limit = int(env_collection_limit) if env_collection_limit else args.collection_limit
    video_limit = int(env_video_limit) if env_video_limit else args.video_limit

    if download_limit:
        logger.info(f"Download limit: {download_limit} videos per run")

    if args.status:
        cmd_status(store)
    elif args.delete or args.delete_all:
        cmd_delete(store, args.delete or [], args.delete_all)
    elif args.sync:
        cmd_sync(client, store, collection_limit, video_limit, exclude_collections=exclude_collections)
    elif args.download:
        cmd_download(store, downloader, download_limit)
    elif args.watch:
        cmd_watch(client, store, downloader, args.interval, exclude_collections=exclude_collections, download_limit=download_limit, collection_limit=collection_limit, video_limit=video_limit)
    else:
        # Default: sync then download
        cmd_sync(client, store, collection_limit, video_limit, exclude_collections=exclude_collections)
        cmd_download(store, downloader, download_limit)


if __name__ == "__main__":
    main()
