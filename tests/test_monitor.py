#!/usr/bin/env python3
"""
Unit tests for TikTok Collections Monitor.
"""

import json
import os
import tempfile
import shutil
from pathlib import Path
from unittest import TestCase, mock
import sys

# Mock playwright before importing tiktok_monitor
sys.modules["playwright"] = mock.MagicMock()
sys.modules["playwright.sync_api"] = mock.MagicMock()

sys.path.insert(0, str(Path(__file__).parent.parent))

from tiktok_monitor import DataStore, VideoDownloader, load_config


class TestDataStore(TestCase):
    """Tests for the DataStore class."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_init_creates_directory(self):
        """DataStore should create the data directory if it doesn't exist."""
        new_dir = os.path.join(self.temp_dir, "new_subdir")
        DataStore(new_dir)  # Creating store should create directory
        self.assertTrue(os.path.exists(new_dir))

    def test_init_creates_empty_structures(self):
        """DataStore should initialize with empty collections, videos, and queue."""
        self.assertEqual(self.store.collections, {})
        self.assertEqual(self.store.videos, {})
        self.assertEqual(self.store.queue, {"pending": [], "completed": [], "failed": []})

    def test_update_collection(self):
        """update_collection should store collection data with timestamp."""
        self.store.update_collection("123", {"id": "123", "name": "Test Collection", "total": 10})
        self.assertIn("123", self.store.collections)
        self.assertEqual(self.store.collections["123"]["name"], "Test Collection")
        self.assertIn("updated_at", self.store.collections["123"])

    def test_save_and_load_collections(self):
        """Collections should persist to disk and reload correctly."""
        self.store.update_collection("123", {"id": "123", "name": "Test"})
        self.store.save_collections()

        # Create new store instance to test loading
        new_store = DataStore(self.temp_dir)
        self.assertIn("123", new_store.collections)
        self.assertEqual(new_store.collections["123"]["name"], "Test")

    def test_add_video_returns_true_for_new(self):
        """add_video should return True for new videos."""
        result = self.store.add_video("vid123", {"id": "vid123", "author": "user1"})
        self.assertTrue(result)

    def test_add_video_returns_false_for_existing(self):
        """add_video should return False for existing videos."""
        self.store.add_video("vid123", {"id": "vid123", "author": "user1"})
        result = self.store.add_video("vid123", {"id": "vid123", "author": "user1"})
        self.assertFalse(result)

    def test_add_video_adds_cached_at(self):
        """add_video should add cached_at timestamp."""
        self.store.add_video("vid123", {"id": "vid123"})
        self.assertIn("cached_at", self.store.videos["vid123"])

    def test_add_video_preserves_download_status(self):
        """add_video should preserve downloaded status when updating existing video."""
        # Add video and mark as downloaded
        self.store.add_video("vid123", {"id": "vid123", "author": "user1"})
        self.store.videos["vid123"]["downloaded"] = True
        self.store.videos["vid123"]["download_path"] = "/path/to/video.mp4"
        self.store.videos["vid123"]["downloaded_at"] = "2024-01-01T12:00:00"

        # Update the same video (simulating a sync)
        self.store.add_video("vid123", {"id": "vid123", "author": "user1", "desc": "new desc"})

        # Download info should be preserved
        self.assertTrue(self.store.videos["vid123"]["downloaded"])
        self.assertEqual(self.store.videos["vid123"]["download_path"], "/path/to/video.mp4")
        self.assertEqual(self.store.videos["vid123"]["downloaded_at"], "2024-01-01T12:00:00")
        # New data should also be there
        self.assertEqual(self.store.videos["vid123"]["desc"], "new desc")

    def test_queue_download(self):
        """queue_download should add video to pending queue."""
        result = self.store.queue_download("vid123", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "Recipes",
            "author": "chef",
            "desc": "A recipe"
        })
        self.assertTrue(result)
        self.assertEqual(len(self.store.queue["pending"]), 1)
        self.assertEqual(self.store.queue["pending"][0]["id"], "vid123")

    def test_queue_download_no_duplicates(self):
        """queue_download should not add duplicates."""
        self.store.queue_download("vid123", {"url": "test"})
        result = self.store.queue_download("vid123", {"url": "test"})
        self.assertFalse(result)
        self.assertEqual(len(self.store.queue["pending"]), 1)

    def test_queue_download_skips_completed(self):
        """queue_download should skip already completed videos."""
        self.store.queue["completed"].append("vid123")
        result = self.store.queue_download("vid123", {"url": "test"})
        self.assertFalse(result)

    def test_get_pending_downloads(self):
        """get_pending_downloads should return pending queue."""
        self.store.queue_download("vid1", {"url": "test1"})
        self.store.queue_download("vid2", {"url": "test2"})
        pending = self.store.get_pending_downloads()
        self.assertEqual(len(pending), 2)

    def test_mark_downloaded(self):
        """mark_downloaded should move video from pending to completed."""
        self.store.queue_download("vid123", {"url": "test"})
        self.store.add_video("vid123", {"id": "vid123"})
        self.store.mark_downloaded("vid123", "/path/to/video.mp4")

        self.assertEqual(len(self.store.queue["pending"]), 0)
        self.assertIn("vid123", self.store.queue["completed"])
        self.assertTrue(self.store.videos["vid123"]["downloaded"])
        self.assertEqual(self.store.videos["vid123"]["download_path"], "/path/to/video.mp4")

    def test_mark_failed(self):
        """mark_failed should move video from pending to failed with error."""
        self.store.queue_download("vid123", {"url": "test"})
        self.store.mark_failed("vid123", "Network error")

        self.assertEqual(len(self.store.queue["pending"]), 0)
        self.assertEqual(len(self.store.queue["failed"]), 1)
        self.assertEqual(self.store.queue["failed"][0]["error"], "Network error")


class TestVideoDownloader(TestCase):
    """Tests for the VideoDownloader class."""

    def setUp(self):
        """Create a temporary directory for downloads."""
        self.temp_dir = tempfile.mkdtemp()
        self.downloader = VideoDownloader(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_creates_folder_structure(self):
        """download should create collection/video_id folder structure."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stderr="")
            self.downloader.download("vid123", "author", "My Collection", "desc")

        expected_dir = Path(self.temp_dir) / "My Collection" / "vid123"
        self.assertTrue(expected_dir.exists())

    def test_sanitizes_collection_name(self):
        """download should sanitize collection names for filesystem."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stderr="")
            self.downloader.download("vid123", "author", "Bad/Name:Here", "desc")

        expected_dir = Path(self.temp_dir) / "Bad_Name_Here" / "vid123"
        self.assertTrue(expected_dir.exists())

    def test_saves_caption_on_success(self):
        """download should save caption.txt on successful download."""
        video_dir = Path(self.temp_dir) / "Test" / "vid123"
        video_dir.mkdir(parents=True, exist_ok=True)
        video_file = video_dir / "vid123.mp4"
        video_file.touch()

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stderr="")
            self.downloader.download("vid123", "author", "Test", "This is a caption")

        caption_file = video_dir / "caption.txt"
        self.assertTrue(caption_file.exists())
        self.assertEqual(caption_file.read_text(), "This is a caption")

    def test_returns_path_on_success(self):
        """download should return video path on success."""
        video_dir = Path(self.temp_dir) / "Test" / "vid123"
        video_dir.mkdir(parents=True, exist_ok=True)
        video_file = video_dir / "vid123.mp4"
        video_file.touch()

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stderr="")
            result = self.downloader.download("vid123", "author", "Test", "")

        self.assertEqual(result, str(video_file))

    def test_returns_none_on_failure(self):
        """download should return None on failure."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stderr="Error")
            result = self.downloader.download("vid123", "author", "Test", "")

        self.assertIsNone(result)


class TestLoadConfig(TestCase):
    """Tests for the load_config function."""

    def setUp(self):
        """Create a temporary directory for config files."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        """Clean up."""
        os.chdir(self.original_dir)
        shutil.rmtree(self.temp_dir)

    def test_loads_valid_config(self):
        """load_config should load a valid JSON config file."""
        config_data = {
            "cookies": {"sessionid": "test123"},
            "download_dir": "./downloads"
        }
        with open("config.json", "w") as f:
            json.dump(config_data, f)

        config = load_config("config.json")
        self.assertEqual(config["cookies"]["sessionid"], "test123")

    def test_exits_on_missing_config(self):
        """load_config should exit if config file is missing."""
        with self.assertRaises(SystemExit):
            load_config("nonexistent.json")


class TestQueuePersistence(TestCase):
    """Tests for queue state persistence across restarts."""

    def setUp(self):
        """Create a temporary directory."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)

    def test_queue_persists_across_instances(self):
        """Queue state should persist when DataStore is reloaded."""
        store1 = DataStore(self.temp_dir)
        store1.queue_download("vid1", {"url": "test1", "collection_name": "C1"})
        store1.queue_download("vid2", {"url": "test2", "collection_name": "C2"})
        store1.save_queue()

        store2 = DataStore(self.temp_dir)
        self.assertEqual(len(store2.queue["pending"]), 2)

    def test_completed_persists(self):
        """Completed downloads should persist."""
        store1 = DataStore(self.temp_dir)
        store1.queue_download("vid1", {"url": "test"})
        store1.add_video("vid1", {"id": "vid1"})
        store1.mark_downloaded("vid1", "/path/video.mp4")
        store1.save_queue()
        store1.save_videos()

        store2 = DataStore(self.temp_dir)
        self.assertIn("vid1", store2.queue["completed"])
        self.assertTrue(store2.videos["vid1"]["downloaded"])

    def test_failed_persists(self):
        """Failed downloads should persist with error info."""
        store1 = DataStore(self.temp_dir)
        store1.queue_download("vid1", {"url": "test"})
        store1.mark_failed("vid1", "Download timeout")
        store1.save_queue()

        store2 = DataStore(self.temp_dir)
        self.assertEqual(len(store2.queue["failed"]), 1)
        self.assertEqual(store2.queue["failed"][0]["error"], "Download timeout")


class TestDeletedFromTikTok(TestCase):
    """Tests for tracking videos deleted from TikTok."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_add_video_sets_deleted_false(self):
        """New videos should have deleted_from_tiktok set to False."""
        self.store.add_video("vid123", {
            "id": "vid123",
            "deleted_from_tiktok": False,
        })
        self.assertFalse(self.store.videos["vid123"].get("deleted_from_tiktok"))

    def test_mark_video_as_deleted(self):
        """Videos can be marked as deleted from TikTok."""
        self.store.add_video("vid123", {"id": "vid123", "collection_id": "coll1"})

        # Simulate marking as deleted
        self.store.videos["vid123"]["deleted_from_tiktok"] = True
        self.store.videos["vid123"]["deleted_at"] = "2024-01-01T12:00:00"

        self.assertTrue(self.store.videos["vid123"]["deleted_from_tiktok"])
        self.assertEqual(self.store.videos["vid123"]["deleted_at"], "2024-01-01T12:00:00")

    def test_deleted_status_persists(self):
        """Deleted from TikTok status should persist across restarts."""
        store1 = DataStore(self.temp_dir)
        store1.add_video("vid123", {"id": "vid123", "collection_id": "coll1"})
        store1.videos["vid123"]["deleted_from_tiktok"] = True
        store1.videos["vid123"]["deleted_at"] = "2024-01-01T12:00:00"
        store1.save_videos()

        store2 = DataStore(self.temp_dir)
        self.assertTrue(store2.videos["vid123"]["deleted_from_tiktok"])
        self.assertEqual(store2.videos["vid123"]["deleted_at"], "2024-01-01T12:00:00")

    def test_deleted_video_keeps_download_info(self):
        """A video marked as deleted should retain its download path and status."""
        self.store.add_video("vid123", {"id": "vid123", "collection_id": "coll1"})
        self.store.mark_downloaded("vid123", "/path/to/video.mp4")

        # Mark as deleted from TikTok
        self.store.videos["vid123"]["deleted_from_tiktok"] = True

        # Should still have download info
        self.assertTrue(self.store.videos["vid123"]["downloaded"])
        self.assertEqual(self.store.videos["vid123"]["download_path"], "/path/to/video.mp4")
        self.assertTrue(self.store.videos["vid123"]["deleted_from_tiktok"])

    def test_get_deleted_videos(self):
        """Can filter videos by deleted_from_tiktok status."""
        self.store.add_video("vid1", {"id": "vid1", "collection_id": "c1"})
        self.store.add_video("vid2", {"id": "vid2", "collection_id": "c1"})
        self.store.add_video("vid3", {"id": "vid3", "collection_id": "c1"})

        # Mark some as deleted
        self.store.videos["vid1"]["deleted_from_tiktok"] = True
        self.store.videos["vid3"]["deleted_from_tiktok"] = True

        deleted = [v for v in self.store.videos.values() if v.get("deleted_from_tiktok")]
        not_deleted = [v for v in self.store.videos.values() if not v.get("deleted_from_tiktok")]

        self.assertEqual(len(deleted), 2)
        self.assertEqual(len(not_deleted), 1)


class TestDeleteVideo(TestCase):
    """Tests for the delete_video method."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_delete_removes_from_videos(self):
        """delete_video should remove video from videos dict."""
        self.store.add_video("vid123", {"id": "vid123"})
        self.store.delete_video("vid123")
        self.assertNotIn("vid123", self.store.videos)

    def test_delete_removes_from_completed_queue(self):
        """delete_video should remove video from completed queue."""
        self.store.add_video("vid123", {"id": "vid123"})
        self.store.queue["completed"].append("vid123")
        self.store.delete_video("vid123")
        self.assertNotIn("vid123", self.store.queue["completed"])

    def test_delete_removes_from_pending_queue(self):
        """delete_video should remove video from pending queue."""
        self.store.queue_download("vid123", {"url": "test", "collection_name": "Test"})
        self.store.delete_video("vid123")
        pending_ids = [v["id"] for v in self.store.queue["pending"]]
        self.assertNotIn("vid123", pending_ids)

    def test_delete_removes_from_failed_queue(self):
        """delete_video should remove video from failed queue."""
        self.store.queue_download("vid123", {"url": "test"})
        self.store.mark_failed("vid123", "Test error")
        self.store.delete_video("vid123")
        failed_ids = [v["id"] for v in self.store.queue["failed"]]
        self.assertNotIn("vid123", failed_ids)

    def test_delete_removes_video_folder(self):
        """delete_video should remove the video folder and files."""
        # Create video folder structure
        video_dir = Path(self.temp_dir) / "TestCollection" / "vid123"
        video_dir.mkdir(parents=True)
        (video_dir / "vid123.mp4").touch()
        (video_dir / "caption.txt").write_text("Test caption")

        self.store.add_video("vid123", {"id": "vid123", "download_path": str(video_dir / "vid123.mp4")})
        self.store.delete_video("vid123")

        self.assertFalse(video_dir.exists())

    def test_delete_removes_empty_collection_folder(self):
        """delete_video should remove empty collection folder after video deletion."""
        # Create video folder structure
        collection_dir = Path(self.temp_dir) / "TestCollection"
        video_dir = collection_dir / "vid123"
        video_dir.mkdir(parents=True)
        (video_dir / "vid123.mp4").touch()

        self.store.add_video("vid123", {"id": "vid123", "download_path": str(video_dir / "vid123.mp4")})
        self.store.delete_video("vid123")

        self.assertFalse(collection_dir.exists())

    def test_delete_keeps_collection_with_other_videos(self):
        """delete_video should keep collection folder if other videos exist."""
        # Create collection with two videos
        collection_dir = Path(self.temp_dir) / "TestCollection"
        video_dir1 = collection_dir / "vid1"
        video_dir2 = collection_dir / "vid2"
        video_dir1.mkdir(parents=True)
        video_dir2.mkdir(parents=True)
        (video_dir1 / "vid1.mp4").touch()
        (video_dir2 / "vid2.mp4").touch()

        self.store.add_video("vid1", {"id": "vid1", "download_path": str(video_dir1 / "vid1.mp4")})
        self.store.add_video("vid2", {"id": "vid2", "download_path": str(video_dir2 / "vid2.mp4")})

        self.store.delete_video("vid1")

        # Collection folder should still exist with vid2
        self.assertTrue(collection_dir.exists())
        self.assertFalse(video_dir1.exists())
        self.assertTrue(video_dir2.exists())


class TestDataJsGeneration(TestCase):
    """Tests for data.js generation."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_data_js_created_on_init(self):
        """data.js should be created when DataStore is initialized."""
        DataStore(self.temp_dir)
        data_js = Path(self.temp_dir) / "data.js"
        self.assertTrue(data_js.exists(), "data.js should be created on DataStore init")

    def test_data_js_contains_valid_javascript(self):
        """data.js should contain valid JavaScript with window variables."""
        DataStore(self.temp_dir)
        data_js = Path(self.temp_dir) / "data.js"
        content = data_js.read_text()
        self.assertIn("window.collectionsData", content)
        self.assertIn("window.videosData", content)

    def test_data_js_contains_collections_data(self):
        """data.js should contain the collections data."""
        store = DataStore(self.temp_dir)
        store.update_collection("123", {"id": "123", "name": "Test Collection"})
        store.save_collections()

        data_js = Path(self.temp_dir) / "data.js"
        content = data_js.read_text()
        self.assertIn("Test Collection", content)

    def test_data_js_contains_videos_data(self):
        """data.js should contain the videos data."""
        store = DataStore(self.temp_dir)
        store.add_video("vid123", {"id": "vid123", "author": "testuser"})
        store.save_videos()

        data_js = Path(self.temp_dir) / "data.js"
        content = data_js.read_text()
        self.assertIn("testuser", content)

    def test_data_js_updated_on_save_collections(self):
        """data.js should be updated when collections are saved."""
        store = DataStore(self.temp_dir)
        data_js = Path(self.temp_dir) / "data.js"

        # Get initial modification time
        initial_content = data_js.read_text()

        # Update and save
        store.update_collection("456", {"id": "456", "name": "New Collection"})
        store.save_collections()

        new_content = data_js.read_text()
        self.assertIn("New Collection", new_content)
        self.assertNotEqual(initial_content, new_content)

    def test_data_js_updated_on_save_videos(self):
        """data.js should be updated when videos are saved."""
        store = DataStore(self.temp_dir)
        data_js = Path(self.temp_dir) / "data.js"

        initial_content = data_js.read_text()

        store.add_video("newvid", {"id": "newvid", "author": "newauthor"})
        store.save_videos()

        new_content = data_js.read_text()
        self.assertIn("newauthor", new_content)


class TestViewerHtmlGeneration(TestCase):
    """Tests for viewer.html generation in DataStore."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_viewer_html_created_on_init(self):
        """DataStore should copy viewer.html to data directory on init."""
        DataStore(self.temp_dir)  # Side effect: creates viewer.html
        viewer_file = Path(self.temp_dir) / "viewer.html"
        self.assertTrue(viewer_file.exists(), "viewer.html should be created on DataStore init")

    def test_viewer_html_contains_expected_content(self):
        """Copied viewer.html should contain expected HTML structure."""
        DataStore(self.temp_dir)  # Side effect: creates viewer.html
        viewer_file = Path(self.temp_dir) / "viewer.html"
        content = viewer_file.read_text()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("data.js", content)

    def test_viewer_html_matches_source(self):
        """Copied viewer.html should match the source file."""
        DataStore(self.temp_dir)  # Side effect: creates viewer.html
        viewer_file = Path(self.temp_dir) / "viewer.html"

        # Get source file path (same logic as _write_viewer_html)
        import tiktok_monitor
        script_dir = Path(tiktok_monitor.__file__).parent
        viewer_src = script_dir / "viewer.html"

        self.assertEqual(viewer_file.read_text(), viewer_src.read_text())


class TestCookieHeader(TestCase):
    """Tests for cookie header creation in VideoDownloader."""

    def setUp(self):
        """Create a temporary directory for downloads."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_no_cookies_creates_empty_header(self):
        """VideoDownloader without cookies should have empty cookie header."""
        downloader = VideoDownloader(self.temp_dir)
        self.assertEqual(downloader._cookie_header, "")

    def test_single_cookie_header(self):
        """VideoDownloader with single cookie should create proper header."""
        cookies = {"sessionid": "test123"}
        downloader = VideoDownloader(self.temp_dir, cookies=cookies)
        self.assertEqual(downloader._cookie_header, "sessionid=test123")

    def test_multiple_cookies_header(self):
        """VideoDownloader with multiple cookies should join them with semicolons."""
        cookies = {"sessionid": "test123", "ttwid": "abc456"}
        downloader = VideoDownloader(self.temp_dir, cookies=cookies)
        # Check both cookies are present (order may vary)
        self.assertIn("sessionid=test123", downloader._cookie_header)
        self.assertIn("ttwid=abc456", downloader._cookie_header)
        self.assertIn("; ", downloader._cookie_header)

    def test_empty_cookie_value_excluded(self):
        """Cookies with empty values should be excluded from header."""
        cookies = {"sessionid": "test123", "empty": "", "ttwid": "abc456"}
        downloader = VideoDownloader(self.temp_dir, cookies=cookies)
        self.assertNotIn("empty=", downloader._cookie_header)
        self.assertIn("sessionid=test123", downloader._cookie_header)
        self.assertIn("ttwid=abc456", downloader._cookie_header)


class TestCorruptedJsonHandling(TestCase):
    """Tests for handling corrupted or empty JSON files."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_empty_videos_json_handled(self):
        """Empty videos.json should not crash DataStore."""
        # Create empty videos.json
        videos_file = Path(self.temp_dir) / "videos.json"
        videos_file.write_text("")

        # Should not raise exception
        store = DataStore(self.temp_dir)
        self.assertEqual(store.videos, {})

    def test_corrupted_videos_json_handled(self):
        """Corrupted videos.json should not crash DataStore."""
        videos_file = Path(self.temp_dir) / "videos.json"
        videos_file.write_text("{ invalid json }")

        store = DataStore(self.temp_dir)
        self.assertEqual(store.videos, {})

    def test_empty_collections_json_handled(self):
        """Empty collections.json should not crash DataStore."""
        collections_file = Path(self.temp_dir) / "collections.json"
        collections_file.write_text("")

        store = DataStore(self.temp_dir)
        self.assertEqual(store.collections, {})

    def test_empty_queue_json_handled(self):
        """Empty download_queue.json should not crash DataStore."""
        queue_file = Path(self.temp_dir) / "download_queue.json"
        queue_file.write_text("")

        store = DataStore(self.temp_dir)
        self.assertEqual(store.queue, {"pending": [], "completed": [], "failed": []})


class TestPreventDuplicateDownloads(TestCase):
    """Tests to ensure videos are not re-downloaded."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_queue_skips_already_downloaded_video(self):
        """queue_download should skip videos marked as downloaded."""
        # Add video and mark as downloaded
        self.store.add_video("vid123", {"id": "vid123", "downloaded": True})
        self.store.videos["vid123"]["downloaded"] = True

        # Try to queue - should return False
        result = self.store.queue_download("vid123", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "Test",
        })

        self.assertFalse(result, "Should not queue already downloaded video")
        self.assertEqual(len(self.store.queue["pending"]), 0)

    def test_queue_skips_video_with_file_on_disk(self):
        """queue_download should skip videos that have files on disk."""
        # Create video file on disk
        video_dir = Path(self.temp_dir) / "TestCollection" / "vid123"
        video_dir.mkdir(parents=True)
        (video_dir / "vid123.mp4").touch()

        # Add video to store (not marked as downloaded)
        self.store.add_video("vid123", {"id": "vid123"})

        # Try to queue - should return False because file exists
        result = self.store.queue_download("vid123", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "TestCollection",
        })

        self.assertFalse(result, "Should not queue video with existing file on disk")
        self.assertEqual(len(self.store.queue["pending"]), 0)

    def test_queue_auto_marks_downloaded_when_file_exists(self):
        """queue_download should mark video as downloaded if file exists on disk."""
        # Create video file on disk
        video_dir = Path(self.temp_dir) / "TestCollection" / "vid123"
        video_dir.mkdir(parents=True)
        video_file = video_dir / "vid123.mp4"
        video_file.touch()

        # Add video to store (not marked as downloaded)
        self.store.add_video("vid123", {"id": "vid123"})

        # Try to queue
        self.store.queue_download("vid123", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "TestCollection",
        })

        # Should now be marked as downloaded
        self.assertTrue(self.store.videos["vid123"].get("downloaded"))
        self.assertEqual(self.store.videos["vid123"]["download_path"], str(video_file))

    def test_queue_auto_adds_to_completed_when_file_exists(self):
        """queue_download should add to completed list if file exists on disk."""
        # Create video file on disk
        video_dir = Path(self.temp_dir) / "TestCollection" / "vid123"
        video_dir.mkdir(parents=True)
        (video_dir / "vid123.mp4").touch()

        # Add video to store
        self.store.add_video("vid123", {"id": "vid123"})

        # Try to queue
        self.store.queue_download("vid123", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "TestCollection",
        })

        # Should be in completed list
        self.assertIn("vid123", self.store.queue["completed"])

    def test_queue_allows_new_video_without_file(self):
        """queue_download should allow queueing new videos without existing files."""
        self.store.add_video("vid123", {"id": "vid123"})

        result = self.store.queue_download("vid123", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "TestCollection",
        })

        self.assertTrue(result, "Should queue new video without existing file")
        self.assertEqual(len(self.store.queue["pending"]), 1)

    def test_sanitized_collection_name_matches_disk(self):
        """queue_download should find files even with special chars in collection name."""
        # Create video file with sanitized collection name
        video_dir = Path(self.temp_dir) / "Test_Collection" / "vid123"
        video_dir.mkdir(parents=True)
        (video_dir / "vid123.mp4").touch()

        self.store.add_video("vid123", {"id": "vid123"})

        # Queue with unsanitized name - should still find the file
        result = self.store.queue_download("vid123", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "Test/Collection",  # Has special char
        })

        self.assertFalse(result, "Should find file with sanitized collection name")


if __name__ == "__main__":
    import unittest
    unittest.main()
