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


if __name__ == "__main__":
    import unittest
    unittest.main()
