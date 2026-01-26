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
        video_file = video_dir / "vid123.mp4"

        def create_video_file(*args, **kwargs):
            video_dir.mkdir(parents=True, exist_ok=True)
            video_file.touch()
            return mock.Mock(returncode=0, stderr="")

        with mock.patch("subprocess.run", side_effect=create_video_file):
            self.downloader.download("vid123", "author", "Test", "This is a caption")

        caption_file = video_dir / "caption.txt"
        self.assertTrue(caption_file.exists())
        self.assertEqual(caption_file.read_text(), "This is a caption")

    def test_returns_path_on_success(self):
        """download should return video path on success."""
        video_dir = Path(self.temp_dir) / "Test" / "vid123"
        video_file = video_dir / "vid123.mp4"

        def create_video_file(*args, **kwargs):
            video_dir.mkdir(parents=True, exist_ok=True)
            video_file.touch()
            return mock.Mock(returncode=0, stderr="")

        with mock.patch("subprocess.run", side_effect=create_video_file):
            result, was_skipped, error_type = self.downloader.download("vid123", "author", "Test", "")

        self.assertEqual(result, str(video_file))
        self.assertFalse(was_skipped)
        self.assertIsNone(error_type)

    def test_returns_none_on_failure(self):
        """download should return (None, False, error_type) on failure."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stderr="Error")
            result, was_skipped, error_type = self.downloader.download("vid123", "author", "Test", "")

        self.assertIsNone(result)
        self.assertFalse(was_skipped)
        self.assertEqual(error_type, "failed")

    def test_skips_existing_video(self):
        """download should skip if video already exists on disk."""
        video_dir = Path(self.temp_dir) / "Test" / "vid123"
        video_dir.mkdir(parents=True, exist_ok=True)
        video_file = video_dir / "vid123.mp4"
        video_file.touch()

        with mock.patch("subprocess.run") as mock_run:
            result, was_skipped, error_type = self.downloader.download("vid123", "author", "Test", "")

        # subprocess.run should NOT be called since file exists
        mock_run.assert_not_called()
        self.assertEqual(result, str(video_file))
        self.assertTrue(was_skipped)
        self.assertIsNone(error_type)


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
            "sessionid": "test123",
            "download_dir": "./downloads"
        }
        with open("config.json", "w") as f:
            json.dump(config_data, f)

        config = load_config("config.json")
        self.assertEqual(config["sessionid"], "test123")

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
        data_js = Path(self.temp_dir) / "json" / "data.js"
        self.assertTrue(data_js.exists(), "data.js should be created on DataStore init")

    def test_data_js_contains_valid_javascript(self):
        """data.js should contain valid JavaScript with window variables."""
        DataStore(self.temp_dir)
        data_js = Path(self.temp_dir) / "json" / "data.js"
        content = data_js.read_text()
        self.assertIn("window.collectionsData", content)
        self.assertIn("window.videosData", content)

    def test_data_js_contains_collections_data(self):
        """data.js should contain the collections data."""
        store = DataStore(self.temp_dir)
        store.update_collection("123", {"id": "123", "name": "Test Collection"})
        store.save_collections()

        data_js = Path(self.temp_dir) / "json" / "data.js"
        content = data_js.read_text()
        self.assertIn("Test Collection", content)

    def test_data_js_contains_videos_data(self):
        """data.js should contain the videos data."""
        store = DataStore(self.temp_dir)
        store.add_video("vid123", {"id": "vid123", "author": "testuser"})
        store.save_videos()

        data_js = Path(self.temp_dir) / "json" / "data.js"
        content = data_js.read_text()
        self.assertIn("testuser", content)

    def test_data_js_updated_on_save_collections(self):
        """data.js should be updated when collections are saved."""
        store = DataStore(self.temp_dir)
        data_js = Path(self.temp_dir) / "json" / "data.js"

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
        data_js = Path(self.temp_dir) / "json" / "data.js"

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
        viewer_file = Path(self.temp_dir) / "json" / "viewer.html"
        self.assertTrue(viewer_file.exists(), "viewer.html should be created on DataStore init")

    def test_viewer_html_contains_expected_content(self):
        """Copied viewer.html should contain expected HTML structure."""
        DataStore(self.temp_dir)  # Side effect: creates viewer.html
        viewer_file = Path(self.temp_dir) / "json" / "viewer.html"
        content = viewer_file.read_text()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("data.js", content)

    def test_viewer_html_matches_source(self):
        """Copied viewer.html should match the source file."""
        DataStore(self.temp_dir)  # Side effect: creates viewer.html
        viewer_file = Path(self.temp_dir) / "json" / "viewer.html"

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


class TestAvailableCollectionsFile(TestCase):
    """Tests for available_collections.json generation."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_available_collections_created_on_save(self):
        """available_collections.json should be created when collections are saved."""
        self.store.update_collection("123", {"id": "123", "name": "Test Collection", "total": 10})
        self.store.save_collections()

        available_file = Path(self.temp_dir) / "json" / "available_collections.json"
        self.assertTrue(available_file.exists(), "available_collections.json should be created")

    def test_available_collections_contains_all_collections(self):
        """available_collections.json should list all collections."""
        self.store.update_collection("123", {"id": "123", "name": "Collection A", "total": 10})
        self.store.update_collection("456", {"id": "456", "name": "Collection B", "total": 5})
        self.store.update_collection("789", {"id": "789", "name": "Collection C", "total": 20})
        self.store.save_collections()

        available_file = Path(self.temp_dir) / "json" / "available_collections.json"
        with open(available_file) as f:
            data = json.load(f)

        self.assertIn("collections", data)
        self.assertEqual(len(data["collections"]), 3)

    def test_available_collections_sorted_by_name(self):
        """Collections in available_collections.json should be sorted alphabetically."""
        self.store.update_collection("123", {"id": "123", "name": "Zebra", "total": 1})
        self.store.update_collection("456", {"id": "456", "name": "Apple", "total": 2})
        self.store.update_collection("789", {"id": "789", "name": "Mango", "total": 3})
        self.store.save_collections()

        available_file = Path(self.temp_dir) / "json" / "available_collections.json"
        with open(available_file) as f:
            data = json.load(f)

        names = [c["name"] for c in data["collections"]]
        self.assertEqual(names, ["Apple", "Mango", "Zebra"])

    def test_available_collections_contains_id_name_total(self):
        """Each collection entry should have id, name, and total fields."""
        self.store.update_collection("123", {"id": "123", "name": "Test", "total": 42})
        self.store.save_collections()

        available_file = Path(self.temp_dir) / "json" / "available_collections.json"
        with open(available_file) as f:
            data = json.load(f)

        coll = data["collections"][0]
        self.assertEqual(coll["id"], "123")
        self.assertEqual(coll["name"], "Test")
        self.assertEqual(coll["total"], 42)

    def test_available_collections_has_comment(self):
        """available_collections.json should include a helpful comment."""
        self.store.update_collection("123", {"id": "123", "name": "Test", "total": 10})
        self.store.save_collections()

        available_file = Path(self.temp_dir) / "json" / "available_collections.json"
        with open(available_file) as f:
            data = json.load(f)

        self.assertIn("_comment", data)
        self.assertIn("exclude_collections", data["_comment"])


class TestJsonFolderMigration(TestCase):
    """Tests for migration to json/ subfolder."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_creates_json_folder(self):
        """DataStore should create json/ subfolder."""
        DataStore(self.temp_dir)
        json_dir = Path(self.temp_dir) / "json"
        self.assertTrue(json_dir.exists(), "json/ subfolder should be created")

    def test_files_created_in_json_folder(self):
        """JSON files should be created in json/ subfolder."""
        store = DataStore(self.temp_dir)
        store.update_collection("123", {"id": "123", "name": "Test"})
        store.save_collections()

        # Files should be in json/ folder
        self.assertTrue((Path(self.temp_dir) / "json" / "collections.json").exists())
        # Files should NOT be in root
        self.assertFalse((Path(self.temp_dir) / "collections.json").exists())

    def test_migrates_existing_files(self):
        """Should migrate existing files from root to json/ folder."""
        # Create files in old location (before DataStore init)
        old_collections = Path(self.temp_dir) / "collections.json"
        old_collections.write_text('{"test_coll": {"id": "test_coll", "name": "Test"}}')

        old_videos = Path(self.temp_dir) / "videos.json"
        old_videos.write_text('{"test_vid": {"id": "test_vid"}}')

        # Initialize DataStore (should migrate)
        store = DataStore(self.temp_dir)

        # Files should be moved to json/
        self.assertFalse(old_collections.exists(), "Old collections.json should be moved")
        self.assertFalse(old_videos.exists(), "Old videos.json should be moved")
        self.assertTrue((Path(self.temp_dir) / "json" / "collections.json").exists())
        self.assertTrue((Path(self.temp_dir) / "json" / "videos.json").exists())

        # Data should be preserved
        self.assertIn("test_coll", store.collections)
        self.assertIn("test_vid", store.videos)

    def test_does_not_overwrite_existing_json_folder_files(self):
        """Migration should not overwrite if file already exists in json/."""
        # Create json folder with file
        json_dir = Path(self.temp_dir) / "json"
        json_dir.mkdir()
        new_file = json_dir / "collections.json"
        new_file.write_text('{"new": {"id": "new", "name": "New Data"}}')

        # Create old file
        old_file = Path(self.temp_dir) / "collections.json"
        old_file.write_text('{"old": {"id": "old", "name": "Old Data"}}')

        # Initialize (should NOT migrate since new file exists)
        store = DataStore(self.temp_dir)

        # New file should be used, old file should remain
        self.assertIn("new", store.collections)
        self.assertNotIn("old", store.collections)
        self.assertTrue(old_file.exists(), "Old file should remain if migration skipped")


class TestPerCollectionQueue(TestCase):
    """Tests for per-collection queue operations."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_get_pending_for_collection(self):
        """get_pending_for_collection should filter by collection name."""
        self.store.queue_download("vid1", {"url": "u1", "collection_name": "Recipes"})
        self.store.queue_download("vid2", {"url": "u2", "collection_name": "Music"})
        self.store.queue_download("vid3", {"url": "u3", "collection_name": "Recipes"})

        recipes = self.store.get_pending_for_collection("Recipes")
        self.assertEqual(len(recipes), 2)
        self.assertEqual({v["id"] for v in recipes}, {"vid1", "vid3"})

    def test_get_pending_for_collection_empty(self):
        """get_pending_for_collection returns empty list for unknown collection."""
        self.store.queue_download("vid1", {"url": "u1", "collection_name": "Recipes"})

        result = self.store.get_pending_for_collection("Unknown")
        self.assertEqual(result, [])

    def test_clear_pending_for_collection(self):
        """clear_pending_for_collection should remove only that collection's videos."""
        self.store.queue_download("vid1", {"url": "u1", "collection_name": "Recipes"})
        self.store.queue_download("vid2", {"url": "u2", "collection_name": "Music"})
        self.store.queue_download("vid3", {"url": "u3", "collection_name": "Recipes"})

        cleared = self.store.clear_pending_for_collection("Recipes")

        self.assertEqual(cleared, 2)
        self.assertEqual(len(self.store.queue["pending"]), 1)
        self.assertEqual(self.store.queue["pending"][0]["id"], "vid2")

    def test_clear_pending_for_collection_empty(self):
        """clear_pending_for_collection returns 0 for unknown collection."""
        self.store.queue_download("vid1", {"url": "u1", "collection_name": "Recipes"})

        cleared = self.store.clear_pending_for_collection("Unknown")

        self.assertEqual(cleared, 0)
        self.assertEqual(len(self.store.queue["pending"]), 1)


class TestExcludeCollections(TestCase):
    """Tests for exclude_collections filtering in cmd_sync."""

    def setUp(self):
        """Create a temporary directory and mock dependencies."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

        # Add some test collections to the store
        self.store.update_collection("coll1", {"id": "coll1", "name": "Recipes", "total": 10})
        self.store.update_collection("coll2", {"id": "coll2", "name": "Music", "total": 20})
        self.store.update_collection("coll3", {"id": "coll3", "name": "Comedy", "total": 15})
        self.store.update_collection("coll4", {"id": "coll4", "name": "Tech", "total": 5})
        self.store.save_collections()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_no_exclusions_processes_all(self):
        """With no exclusions, all collections should be processed."""
        collections = list(self.store.collections.values())
        exclude_collections = None

        # Simulate the filtering logic from cmd_sync
        if exclude_collections:
            exclude_set = set(exclude_collections)
            collections = [
                c for c in collections
                if c.get("id") not in exclude_set and c.get("name") not in exclude_set
            ]

        self.assertEqual(len(collections), 4)

    def test_empty_exclusions_processes_all(self):
        """With empty exclusion list, all collections should be processed."""
        collections = list(self.store.collections.values())
        exclude_collections = []

        if exclude_collections:
            exclude_set = set(exclude_collections)
            collections = [
                c for c in collections
                if c.get("id") not in exclude_set and c.get("name") not in exclude_set
            ]

        self.assertEqual(len(collections), 4)

    def test_exclude_by_name(self):
        """Collections can be excluded by name."""
        collections = list(self.store.collections.values())
        exclude_collections = ["Recipes", "Comedy"]

        exclude_set = set(exclude_collections)
        filtered = [
            c for c in collections
            if c.get("id") not in exclude_set and c.get("name") not in exclude_set
        ]

        self.assertEqual(len(filtered), 2)
        names = [c["name"] for c in filtered]
        self.assertNotIn("Recipes", names)
        self.assertNotIn("Comedy", names)
        self.assertIn("Music", names)
        self.assertIn("Tech", names)

    def test_exclude_by_id(self):
        """Collections can be excluded by ID."""
        collections = list(self.store.collections.values())
        exclude_collections = ["coll1", "coll3"]

        exclude_set = set(exclude_collections)
        filtered = [
            c for c in collections
            if c.get("id") not in exclude_set and c.get("name") not in exclude_set
        ]

        self.assertEqual(len(filtered), 2)
        ids = [c["id"] for c in filtered]
        self.assertNotIn("coll1", ids)
        self.assertNotIn("coll3", ids)
        self.assertIn("coll2", ids)
        self.assertIn("coll4", ids)

    def test_exclude_mixed_names_and_ids(self):
        """Collections can be excluded using a mix of names and IDs."""
        collections = list(self.store.collections.values())
        exclude_collections = ["Recipes", "coll2"]  # Name and ID

        exclude_set = set(exclude_collections)
        filtered = [
            c for c in collections
            if c.get("id") not in exclude_set and c.get("name") not in exclude_set
        ]

        self.assertEqual(len(filtered), 2)
        names = [c["name"] for c in filtered]
        self.assertIn("Comedy", names)
        self.assertIn("Tech", names)

    def test_exclude_nonexistent_collection(self):
        """Excluding a non-existent collection should not cause errors."""
        collections = list(self.store.collections.values())
        exclude_collections = ["NonExistent", "fake123"]

        exclude_set = set(exclude_collections)
        filtered = [
            c for c in collections
            if c.get("id") not in exclude_set and c.get("name") not in exclude_set
        ]

        self.assertEqual(len(filtered), 4)  # All collections still present

    def test_exclude_all_collections(self):
        """Excluding all collections should result in empty list."""
        collections = list(self.store.collections.values())
        exclude_collections = ["Recipes", "Music", "Comedy", "Tech"]

        exclude_set = set(exclude_collections)
        filtered = [
            c for c in collections
            if c.get("id") not in exclude_set and c.get("name") not in exclude_set
        ]

        self.assertEqual(len(filtered), 0)

    def test_exclude_case_sensitive(self):
        """Exclusion matching should be case-sensitive."""
        collections = list(self.store.collections.values())
        exclude_collections = ["recipes", "MUSIC"]  # Wrong case

        exclude_set = set(exclude_collections)
        filtered = [
            c for c in collections
            if c.get("id") not in exclude_set and c.get("name") not in exclude_set
        ]

        # None should be excluded because case doesn't match
        self.assertEqual(len(filtered), 4)


class TestLoadConfigWithExcludeCollections(TestCase):
    """Tests for loading exclude_collections from config."""

    def setUp(self):
        """Create a temporary directory for config files."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        """Clean up."""
        os.chdir(self.original_dir)
        shutil.rmtree(self.temp_dir)

    def test_loads_exclude_collections_array(self):
        """load_config should load exclude_collections as an array."""
        config_data = {
            "sessionid": "test123",
            "download_dir": "./downloads",
            "exclude_collections": ["Collection1", "coll123"]
        }
        with open("config.json", "w") as f:
            json.dump(config_data, f)

        config = load_config("config.json")
        self.assertEqual(config["exclude_collections"], ["Collection1", "coll123"])

    def test_missing_exclude_collections_defaults_to_empty(self):
        """Config without exclude_collections should allow default empty list."""
        config_data = {
            "sessionid": "test123",
            "download_dir": "./downloads"
        }
        with open("config.json", "w") as f:
            json.dump(config_data, f)

        config = load_config("config.json")
        # The config.get("exclude_collections", []) in main() handles the default
        self.assertIsNone(config.get("exclude_collections"))

    def test_empty_exclude_collections_array(self):
        """load_config should handle empty exclude_collections array."""
        config_data = {
            "sessionid": "test123",
            "download_dir": "./downloads",
            "exclude_collections": []
        }
        with open("config.json", "w") as f:
            json.dump(config_data, f)

        config = load_config("config.json")
        self.assertEqual(config["exclude_collections"], [])


class TestWatchModeStartupDownload(TestCase):
    """Tests for watch mode resuming downloads on startup."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_pending_queue_available_on_restart(self):
        """Pending downloads should be available when DataStore is reloaded."""
        # First instance - add items to pending queue
        store1 = DataStore(self.temp_dir)
        store1.add_video("vid1", {"id": "vid1", "author": "user1"})
        store1.add_video("vid2", {"id": "vid2", "author": "user2"})
        store1.queue_download("vid1", {"url": "test1", "collection_name": "C1", "author": "user1"})
        store1.queue_download("vid2", {"url": "test2", "collection_name": "C2", "author": "user2"})
        store1.save_queue()
        store1.save_videos()

        # Second instance - simulate container restart
        store2 = DataStore(self.temp_dir)

        # Pending queue should have items ready to download
        self.assertEqual(len(store2.queue["pending"]), 2)
        pending_ids = [item["id"] for item in store2.queue["pending"]]
        self.assertIn("vid1", pending_ids)
        self.assertIn("vid2", pending_ids)

    def test_partial_download_resumes(self):
        """Downloads should resume from where they left off after restart."""
        # First instance - add 3 items, complete 1
        store1 = DataStore(self.temp_dir)
        store1.add_video("vid1", {"id": "vid1"})
        store1.add_video("vid2", {"id": "vid2"})
        store1.add_video("vid3", {"id": "vid3"})
        store1.queue_download("vid1", {"url": "t1", "collection_name": "C"})
        store1.queue_download("vid2", {"url": "t2", "collection_name": "C"})
        store1.queue_download("vid3", {"url": "t3", "collection_name": "C"})

        # Complete vid1
        store1.mark_downloaded("vid1", "/path/vid1.mp4")
        store1.save_queue()
        store1.save_videos()

        # Second instance - should have 2 pending, 1 completed
        store2 = DataStore(self.temp_dir)
        self.assertEqual(len(store2.queue["pending"]), 2)
        self.assertEqual(len(store2.queue["completed"]), 1)
        self.assertIn("vid1", store2.queue["completed"])

    def test_failed_downloads_not_in_pending(self):
        """Failed downloads should not be in pending queue on restart."""
        store1 = DataStore(self.temp_dir)
        store1.add_video("vid1", {"id": "vid1"})
        store1.add_video("vid2", {"id": "vid2"})
        store1.queue_download("vid1", {"url": "t1", "collection_name": "C"})
        store1.queue_download("vid2", {"url": "t2", "collection_name": "C"})

        # Fail vid1
        store1.mark_failed("vid1", "Network error")
        store1.save_queue()

        # Restart
        store2 = DataStore(self.temp_dir)
        self.assertEqual(len(store2.queue["pending"]), 1)
        self.assertEqual(len(store2.queue["failed"]), 1)
        pending_ids = [item["id"] for item in store2.queue["pending"]]
        self.assertNotIn("vid1", pending_ids)
        self.assertIn("vid2", pending_ids)

    def test_queue_file_contains_all_data(self):
        """The queue file should contain all necessary data for resuming."""
        store1 = DataStore(self.temp_dir)
        store1.queue_download("vid1", {
            "url": "https://tiktok.com/video/123",
            "collection_name": "Test Collection",
            "author": "testuser",
            "desc": "Test description"
        })
        store1.save_queue()

        # Check the file directly
        queue_file = Path(self.temp_dir) / "json" / "download_queue.json"
        with open(queue_file) as f:
            data = json.load(f)

        self.assertEqual(len(data["pending"]), 1)
        item = data["pending"][0]
        self.assertEqual(item["id"], "vid1")
        self.assertEqual(item["url"], "https://tiktok.com/video/123")
        self.assertEqual(item["collection"], "Test Collection")
        self.assertEqual(item["author"], "testuser")


class TestTikTokClientDirectAPI(TestCase):
    """Tests for TikTokClient direct API call approach.

    These tests verify that the client uses direct API calls via page.evaluate()
    instead of relying on page response interception, which is more reliable.
    """

    def test_get_collections_uses_direct_api_url(self):
        """get_collections should make direct API calls to collection_list endpoint."""
        # Import here to get fresh mock
        from tiktok_monitor import TikTokClient

        # The method signature should match the direct API approach
        client = TikTokClient("test_session_id")

        # Check that the method docstring indicates direct API approach
        self.assertIn("direct api", client.get_collections.__doc__.lower())

    def test_get_collection_videos_uses_direct_api_url(self):
        """get_collection_videos should make direct API calls to item_list endpoint."""
        from tiktok_monitor import TikTokClient

        client = TikTokClient("test_session_id")

        # Check that the method docstring indicates direct API approach
        self.assertIn("direct api", client.get_collection_videos.__doc__.lower())

    def test_get_collections_method_has_pagination_support(self):
        """get_collections should support pagination with cursor."""
        import inspect
        from tiktok_monitor import TikTokClient

        # Get the source code of get_collections
        source = inspect.getsource(TikTokClient.get_collections)

        # Verify it uses cursor-based pagination
        self.assertIn("cursor", source)
        self.assertIn("has_more", source)  # Check for the actual variable name
        # Verify it makes direct API calls (uses page.evaluate)
        self.assertIn("page.evaluate", source)
        # Verify it calls the correct API endpoint
        self.assertIn("api/user/collection_list", source)

    def test_get_collection_videos_method_has_pagination_support(self):
        """get_collection_videos should support pagination with cursor."""
        import inspect
        from tiktok_monitor import TikTokClient

        source = inspect.getsource(TikTokClient.get_collection_videos)

        # Verify it uses cursor-based pagination
        self.assertIn("cursor", source)
        self.assertIn("has_more", source)  # Check for the actual variable name
        # Verify it makes direct API calls
        self.assertIn("page.evaluate", source)
        # Verify it calls the correct API endpoint
        self.assertIn("api/collection/item_list", source)

    def test_get_collections_extracts_secuid(self):
        """get_collections should extract secUid from page for API calls."""
        import inspect
        from tiktok_monitor import TikTokClient

        source = inspect.getsource(TikTokClient.get_collections)

        # Verify it extracts secUid
        self.assertIn("secUid", source)
        # Verify it tries multiple methods to get secUid
        self.assertIn("__NEXT_DATA__", source)
        self.assertIn("SIGI_STATE", source)

    def test_get_collection_videos_includes_required_params(self):
        """get_collection_videos API call should include all required parameters."""
        import inspect
        from tiktok_monitor import TikTokClient

        source = inspect.getsource(TikTokClient.get_collection_videos)

        # Verify required API parameters are set
        self.assertIn("collectionId", source)
        self.assertIn("count", source)
        self.assertIn("cursor", source)
        self.assertIn("aid", source)

    def test_methods_do_not_use_response_interception(self):
        """Direct API methods should NOT use page.on('response') interception."""
        import inspect
        from tiktok_monitor import TikTokClient

        collections_source = inspect.getsource(TikTokClient.get_collections)
        videos_source = inspect.getsource(TikTokClient.get_collection_videos)

        # These methods should NOT use response interception (the old approach)
        self.assertNotIn("page.on(\"response\"", collections_source)
        self.assertNotIn("page.on('response'", collections_source)
        self.assertNotIn("page.on(\"response\"", videos_source)
        self.assertNotIn("page.on('response'", videos_source)

    def test_get_collections_has_retry_logic(self):
        """get_collections should have retry logic for transient failures."""
        import inspect
        from tiktok_monitor import TikTokClient

        source = inspect.getsource(TikTokClient.get_collections)

        # Verify retry logic exists
        self.assertIn("attempt", source.lower())
        self.assertIn("retry", source.lower())

    def test_get_collection_videos_has_retry_logic(self):
        """get_collection_videos should have retry logic for transient failures."""
        import inspect
        from tiktok_monitor import TikTokClient

        source = inspect.getsource(TikTokClient.get_collection_videos)

        # Verify retry logic exists
        self.assertIn("attempt", source.lower())


class TestRateLimiter(TestCase):
    """Tests for the RateLimiter class."""

    def test_initial_state_no_delay(self):
        """RateLimiter should start with no delay."""
        from tiktok_monitor import RateLimiter
        limiter = RateLimiter()
        self.assertEqual(limiter.get_current_delay(), 0.0)

    def test_report_rate_limit_increases_delay(self):
        """report_rate_limit should increase the delay."""
        from tiktok_monitor import RateLimiter
        limiter = RateLimiter(initial_delay=1.0, backoff_factor=2.0)

        limiter.report_rate_limit()
        self.assertEqual(limiter.get_current_delay(), 1.0)

        limiter.report_rate_limit()
        self.assertEqual(limiter.get_current_delay(), 2.0)

        limiter.report_rate_limit()
        self.assertEqual(limiter.get_current_delay(), 4.0)

    def test_report_rate_limit_respects_max_delay(self):
        """report_rate_limit should not exceed max_delay."""
        from tiktok_monitor import RateLimiter
        limiter = RateLimiter(initial_delay=1.0, max_delay=5.0, backoff_factor=10.0)

        limiter.report_rate_limit()
        self.assertEqual(limiter.get_current_delay(), 1.0)

        limiter.report_rate_limit()
        self.assertEqual(limiter.get_current_delay(), 5.0)  # Capped at max

        limiter.report_rate_limit()
        self.assertEqual(limiter.get_current_delay(), 5.0)  # Still capped

    def test_report_success_reduces_delay_on_each_success(self):
        """report_success should reduce delay by half on each success."""
        from tiktok_monitor import RateLimiter
        limiter = RateLimiter(initial_delay=1.0, backoff_factor=2.0)

        # First set a delay - two rate limits gets us to 2.0
        limiter.report_rate_limit()  # 0 -> 1.0
        limiter.report_rate_limit()  # 1.0 -> 2.0
        self.assertEqual(limiter.get_current_delay(), 2.0)

        # First success should halve delay: 2.0 -> 1.0
        limiter.report_success()
        self.assertEqual(limiter.get_current_delay(), 1.0)

        # Second success should halve again: 1.0 -> 0.5
        limiter.report_success()
        self.assertEqual(limiter.get_current_delay(), 0.5)

        # Third success should clear (0.5 / 2 = 0.25 < 0.5 threshold)
        limiter.report_success()
        self.assertEqual(limiter.get_current_delay(), 0.0)

    def test_report_success_clears_delay_when_below_threshold(self):
        """report_success should clear delay when it drops below 0.5."""
        from tiktok_monitor import RateLimiter
        limiter = RateLimiter(initial_delay=1.0, backoff_factor=2.0)

        limiter.report_rate_limit()  # Sets delay to 1.0
        self.assertEqual(limiter.get_current_delay(), 1.0)

        # First success: 1.0 -> 0.5
        limiter.report_success()
        self.assertEqual(limiter.get_current_delay(), 0.5)

        # Second success: 0.5 / 2 = 0.25 < 0.5 threshold, so clears to 0
        limiter.report_success()
        self.assertEqual(limiter.get_current_delay(), 0.0)

    def test_rate_limit_increases_delay_after_successes_reduced_it(self):
        """report_rate_limit should increase delay even after successes reduced it."""
        from tiktok_monitor import RateLimiter
        limiter = RateLimiter(initial_delay=1.0, backoff_factor=2.0)

        # Set initial delay
        limiter.report_rate_limit()  # 0 -> 1.0
        limiter.report_rate_limit()  # 1.0 -> 2.0
        self.assertEqual(limiter.get_current_delay(), 2.0)

        # Success reduces delay: 2.0 -> 1.0
        limiter.report_success()
        self.assertEqual(limiter.get_current_delay(), 1.0)

        # Another rate limit should double: 1.0 -> 2.0
        limiter.report_rate_limit()
        self.assertEqual(limiter.get_current_delay(), 2.0)

        # Success should halve again: 2.0 -> 1.0
        limiter.report_success()
        self.assertEqual(limiter.get_current_delay(), 1.0)


class TestRateLimitErrorDetection(TestCase):
    """Tests for rate limit error detection in VideoDownloader."""

    def setUp(self):
        """Create a temporary directory for test downloads."""
        self.temp_dir = tempfile.mkdtemp()
        self.downloader = VideoDownloader(self.temp_dir, {"sessionid": "test"})

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_detects_429_as_rate_limit(self):
        """Should detect HTTP 429 as rate limit error."""
        stderr = "ERROR: [download] Got error: HTTP Error 429: Too Many Requests"
        self.assertTrue(self.downloader._is_rate_limit_error(stderr))

    def test_detects_530_as_rate_limit(self):
        """Should detect HTTP 530 as rate limit error."""
        stderr = "ERROR: [download] Got error: HTTP Error 530: Too Many Requests"
        self.assertTrue(self.downloader._is_rate_limit_error(stderr))

    def test_detects_0_bytes_read_as_rate_limit(self):
        """Should detect '0 bytes read' as rate limit error."""
        stderr = "ERROR: [download] Got error: 0 bytes read, 8545873 more expected. Giving up after 10 retries"
        self.assertTrue(self.downloader._is_rate_limit_error(stderr))

    def test_does_not_detect_404_as_rate_limit(self):
        """Should not detect 404 as rate limit error."""
        stderr = "ERROR: unable to download video data: HTTP Error 404: Not Found"
        self.assertFalse(self.downloader._is_rate_limit_error(stderr))

    def test_detects_404_as_not_found(self):
        """Should detect 404 as not found error."""
        stderr = "ERROR: unable to download video data: HTTP Error 404: Not Found"
        self.assertTrue(self.downloader._is_not_found_error(stderr))

    def test_does_not_detect_429_as_not_found(self):
        """Should not detect 429 as not found error."""
        stderr = "ERROR: [download] Got error: HTTP Error 429: Too Many Requests"
        self.assertFalse(self.downloader._is_not_found_error(stderr))

    def test_download_returns_rate_limited_error_type(self):
        """download should return rate_limited error type on 429/530 errors."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1,
                stderr="ERROR: [download] Got error: HTTP Error 429: Too Many Requests"
            )
            result, was_skipped, error_type = self.downloader.download("vid123", "author", "Test", "")

        self.assertIsNone(result)
        self.assertFalse(was_skipped)
        self.assertEqual(error_type, "rate_limited")

    def test_download_returns_not_found_error_type(self):
        """download should return not_found error type on 404 errors."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1,
                stderr="ERROR: unable to download video data: HTTP Error 404: Not Found"
            )
            result, was_skipped, error_type = self.downloader.download("vid123", "author", "Test", "")

        self.assertIsNone(result)
        self.assertFalse(was_skipped)
        self.assertEqual(error_type, "not_found")


class TestThreadSafeQueueOperations(TestCase):
    """Tests for thread-safe queue operations in DataStore."""

    def setUp(self):
        """Create a temporary directory for test data."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_pop_pending_download_returns_first_item(self):
        """pop_pending_download should return and remove the first pending item."""
        self.store.queue_download("vid1", {"url": "url1", "collection_name": "Test"})
        self.store.queue_download("vid2", {"url": "url2", "collection_name": "Test"})

        item = self.store.pop_pending_download()
        self.assertEqual(item["id"], "vid1")
        self.assertEqual(len(self.store.get_pending_downloads()), 1)

    def test_pop_pending_download_returns_none_when_empty(self):
        """pop_pending_download should return None when queue is empty."""
        item = self.store.pop_pending_download()
        self.assertIsNone(item)

    def test_requeue_video_moves_to_end(self):
        """requeue_video should move video to end of pending queue."""
        self.store.queue_download("vid1", {"url": "url1", "collection_name": "Test"})
        self.store.queue_download("vid2", {"url": "url2", "collection_name": "Test"})
        self.store.queue_download("vid3", {"url": "url3", "collection_name": "Test"})

        # Requeue vid1 (should move to end)
        result = self.store.requeue_video("vid1")
        self.assertTrue(result)

        pending = self.store.get_pending_downloads()
        self.assertEqual(pending[0]["id"], "vid2")
        self.assertEqual(pending[1]["id"], "vid3")
        self.assertEqual(pending[2]["id"], "vid1")

    def test_requeue_video_adds_requeued_at(self):
        """requeue_video should add requeued_at timestamp."""
        self.store.queue_download("vid1", {"url": "url1", "collection_name": "Test"})
        self.store.requeue_video("vid1")

        pending = self.store.get_pending_downloads()
        self.assertIn("requeued_at", pending[0])

    def test_requeue_video_returns_false_if_not_found(self):
        """requeue_video should return False if video not in pending."""
        result = self.store.requeue_video("nonexistent")
        self.assertFalse(result)

    def test_get_pending_count(self):
        """get_pending_count should return correct count."""
        self.assertEqual(self.store.get_pending_count(), 0)

        self.store.queue_download("vid1", {"url": "url1", "collection_name": "Test"})
        self.assertEqual(self.store.get_pending_count(), 1)

        self.store.queue_download("vid2", {"url": "url2", "collection_name": "Test"})
        self.assertEqual(self.store.get_pending_count(), 2)

    def test_get_pending_downloads_returns_copy(self):
        """get_pending_downloads should return a copy, not the original list."""
        self.store.queue_download("vid1", {"url": "url1", "collection_name": "Test"})

        pending = self.store.get_pending_downloads()
        pending.clear()  # Modify the returned list

        # Original should be unchanged
        self.assertEqual(self.store.get_pending_count(), 1)

    def test_concurrent_queue_operations(self):
        """Queue operations should be thread-safe under concurrent access."""
        import threading
        import time

        errors = []

        def queue_videos(start_id, count):
            try:
                for i in range(count):
                    self.store.queue_download(f"vid{start_id + i}", {"url": f"url{i}", "collection_name": "Test"})
            except Exception as e:
                errors.append(e)

        def pop_videos(count):
            try:
                for _ in range(count):
                    self.store.pop_pending_download()
                    time.sleep(0.001)  # Small delay to increase contention
            except Exception as e:
                errors.append(e)

        # Create threads that concurrently add and remove from queue
        threads = [
            threading.Thread(target=queue_videos, args=(0, 50)),
            threading.Thread(target=queue_videos, args=(100, 50)),
            threading.Thread(target=pop_videos, args=(30,)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        self.assertEqual(len(errors), 0, f"Errors during concurrent operations: {errors}")


class TestDownloadWorker(TestCase):
    """Tests for DownloadWorker background processing."""

    def setUp(self):
        """Create temporary directory and mock downloader."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = DataStore(self.temp_dir)
        self.downloader = VideoDownloader(self.temp_dir, {"sessionid": "test"})

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_download_worker_can_start_and_stop(self):
        """DownloadWorker should start and stop cleanly."""
        from tiktok_monitor import DownloadWorker

        worker = DownloadWorker(self.store, self.downloader, max_parallel=2)
        worker.start()
        self.assertTrue(worker.is_running())

        worker.stop(timeout=5)
        self.assertFalse(worker.is_running())

    def test_download_worker_processes_queue(self):
        """DownloadWorker should process items from the queue."""
        import time
        from tiktok_monitor import DownloadWorker

        # Add item to queue
        self.store.queue_download("vid1", {"url": "https://example.com/video", "collection_name": "Test", "author": "testuser"})

        # Mock the download to succeed
        with mock.patch.object(self.downloader, 'download') as mock_download:
            mock_download.return_value = ("/path/to/video.mp4", False, None)

            worker = DownloadWorker(self.store, self.downloader, max_parallel=1)
            worker.start()

            # Wait for processing
            time.sleep(0.5)

            worker.stop(timeout=5)

        # Should have been processed
        self.assertEqual(self.store.get_pending_count(), 0)

    def test_download_worker_handles_rate_limit(self):
        """DownloadWorker should requeue rate-limited videos."""
        import time
        from tiktok_monitor import DownloadWorker, VideoDownloader

        # Add item to queue
        self.store.queue_download("vid1", {"url": "https://example.com/video", "collection_name": "Test", "author": "testuser"})

        # Mock the download to return rate_limited, then succeed
        call_count = [0]

        def mock_download_fn(video_id, author, collection_name, description=""):
            call_count[0] += 1
            if call_count[0] == 1:
                return (None, False, VideoDownloader.ERROR_RATE_LIMITED)
            return ("/path/to/video.mp4", False, None)

        with mock.patch.object(self.downloader, 'download', side_effect=mock_download_fn):
            with mock.patch.object(self.downloader.rate_limiter, 'wait_if_needed'):
                worker = DownloadWorker(self.store, self.downloader, max_parallel=1)
                worker.start()

                # Wait for both attempts to complete
                for _ in range(30):  # Wait up to 3 seconds
                    time.sleep(0.1)
                    if call_count[0] >= 2:
                        break

                worker.stop(timeout=5)

        # Should have been called twice (rate limited then success)
        self.assertEqual(call_count[0], 2)

    def test_download_worker_marks_not_found_as_failed(self):
        """DownloadWorker should mark 404 videos as failed."""
        import time
        from tiktok_monitor import DownloadWorker, VideoDownloader

        # Add item to queue
        self.store.queue_download("vid1", {"url": "https://example.com/video", "collection_name": "Test", "author": "testuser"})

        # Track if download was called
        download_called = [False]

        def mock_download_fn(video_id, author, collection_name, description=""):
            download_called[0] = True
            return (None, False, VideoDownloader.ERROR_NOT_FOUND)

        with mock.patch.object(self.downloader, 'download', side_effect=mock_download_fn):
            with mock.patch.object(self.downloader.rate_limiter, 'wait_if_needed'):
                worker = DownloadWorker(self.store, self.downloader, max_parallel=1)
                worker.start()

                # Wait for download to be called
                for _ in range(30):  # Wait up to 3 seconds
                    time.sleep(0.1)
                    if download_called[0]:
                        break

                # Give worker time to process the result
                time.sleep(0.2)

                worker.stop(timeout=5)

        # Should be marked as failed
        self.assertEqual(len(self.store.queue["failed"]), 1)
        self.assertEqual(self.store.queue["failed"][0]["id"], "vid1")


if __name__ == "__main__":
    import unittest
    unittest.main()
