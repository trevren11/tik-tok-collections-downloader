#!/usr/bin/env python3
"""
Unit tests for the TikTok video import script.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from import_videos import VideoImporter, VideoInfo, ImportReport


class TestVideoImporter(unittest.TestCase):
    """Tests for VideoImporter class."""

    def setUp(self):
        """Create temporary directories for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.source_dir = Path(self.temp_dir) / "source"
        self.dest_dir = Path(self.temp_dir) / "dest"
        self.source_dir.mkdir()
        self.dest_dir.mkdir()

    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.temp_dir)

    def create_test_video(self, collection_name: str, video_id: str,
                          with_metadata: bool = True,
                          metadata_overrides: dict = None,
                          in_dest: bool = False) -> Path:
        """Helper to create a test video with optional metadata."""
        base_dir = self.dest_dir if in_dest else self.source_dir
        video_dir = base_dir / collection_name / video_id
        video_dir.mkdir(parents=True, exist_ok=True)

        # Create video file
        video_file = video_dir / f"{video_id}.mp4"
        video_file.write_text("fake video content")

        if with_metadata:
            # Create .info.json
            metadata = {
                "id": video_id,
                "uploader": "testuser",
                "description": "Test video description",
                "upload_date": "20240101",
                "playlist_title": collection_name,
            }
            if metadata_overrides:
                metadata.update(metadata_overrides)

            info_json = video_dir / f"{video_id}.info.json"
            info_json.write_text(json.dumps(metadata))

            # Create caption.txt
            caption_file = video_dir / "caption.txt"
            caption_file.write_text(metadata.get("description", ""))

        return video_file


class TestExtractVideoId(TestVideoImporter):
    """Tests for video ID extraction."""

    def test_extract_video_id_from_standard_filename(self):
        """Test extracting video ID from standard filename."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        # Standard 19-digit TikTok video ID
        self.assertEqual(
            importer.extract_video_id("7597399138594065687.mp4"),
            "7597399138594065687"
        )

    def test_extract_video_id_from_filename_with_prefix(self):
        """Test extracting video ID when filename has prefix."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        self.assertEqual(
            importer.extract_video_id("tiktok_7597399138594065687.mp4"),
            "7597399138594065687"
        )

    def test_extract_video_id_from_filename_with_suffix(self):
        """Test extracting video ID when filename has suffix."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        self.assertEqual(
            importer.extract_video_id("7597399138594065687_720p.mp4"),
            "7597399138594065687"
        )

    def test_extract_video_id_returns_none_for_invalid(self):
        """Test that None is returned for invalid filenames."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        self.assertIsNone(importer.extract_video_id("random_video.mp4"))
        self.assertIsNone(importer.extract_video_id("12345.mp4"))

    def test_extract_video_id_handles_17_to_20_digits(self):
        """Test that 17-20 digit IDs are extracted."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        # 17 digits
        self.assertEqual(
            importer.extract_video_id("12345678901234567.mp4"),
            "12345678901234567"
        )

        # 20 digits
        self.assertEqual(
            importer.extract_video_id("12345678901234567890.mp4"),
            "12345678901234567890"
        )


class TestSanitizeCollectionName(TestVideoImporter):
    """Tests for collection name sanitization."""

    def test_sanitize_basic_name(self):
        """Test that basic names are unchanged."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        self.assertEqual(importer.sanitize_collection_name("My Collection"), "My Collection")
        self.assertEqual(importer.sanitize_collection_name("test-collection"), "test-collection")
        self.assertEqual(importer.sanitize_collection_name("test_collection"), "test_collection")

    def test_sanitize_special_characters(self):
        """Test that special characters are replaced with underscores."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        self.assertEqual(importer.sanitize_collection_name("Test/Collection"), "Test_Collection")
        self.assertEqual(importer.sanitize_collection_name("Test:Collection"), "Test_Collection")
        self.assertEqual(importer.sanitize_collection_name("Test<>Collection"), "Test__Collection")


class TestFindVideosInSource(TestVideoImporter):
    """Tests for finding videos in source directory."""

    def test_find_videos_empty_directory(self):
        """Test finding videos in an empty directory."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 0)

    def test_find_videos_single_video(self):
        """Test finding a single video."""
        self.create_test_video("TestCollection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].video_id, "7597399138594065687")

    def test_find_videos_multiple_collections(self):
        """Test finding videos across multiple collections."""
        self.create_test_video("Collection1", "7597399138594065687")
        self.create_test_video("Collection1", "7597399138594065688")
        self.create_test_video("Collection2", "7597399138594065689")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 3)
        video_ids = {v.video_id for v in videos}
        self.assertEqual(video_ids, {"7597399138594065687", "7597399138594065688", "7597399138594065689"})

    def test_find_videos_skips_partial_downloads(self):
        """Test that partial downloads (.part files) are skipped."""
        video_dir = self.source_dir / "TestCollection" / "7597399138594065687"
        video_dir.mkdir(parents=True)

        # Create a partial download
        part_file = video_dir / "7597399138594065687.mp4.part"
        part_file.write_text("partial")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 0)

    def test_find_videos_different_extensions(self):
        """Test finding videos with different extensions."""
        video_dir = self.source_dir / "TestCollection"
        video_dir.mkdir(parents=True)

        # Create videos with different extensions
        (video_dir / "7597399138594065687.mp4").write_text("video")
        (video_dir / "7597399138594065688.webm").write_text("video")
        (video_dir / "7597399138594065689.mkv").write_text("video")
        (video_dir / "7597399138594065690.txt").write_text("not a video")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 3)

    def test_find_videos_detects_info_json(self):
        """Test that .info.json files are detected."""
        self.create_test_video("TestCollection", "7597399138594065687", with_metadata=True)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        self.assertIsNotNone(videos[0].info_json_path)
        self.assertTrue(videos[0].info_json_path.exists())

    def test_find_videos_detects_caption(self):
        """Test that caption.txt files are detected."""
        self.create_test_video("TestCollection", "7597399138594065687", with_metadata=True)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        self.assertIsNotNone(videos[0].caption_path)
        self.assertTrue(videos[0].caption_path.exists())

    def test_find_videos_nonexistent_source(self):
        """Test handling of nonexistent source directory."""
        importer = VideoImporter("/nonexistent/path", str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 0)


class TestLoadMetadata(TestVideoImporter):
    """Tests for loading metadata from .info.json files."""

    def test_load_metadata_basic(self):
        """Test loading basic metadata."""
        self.create_test_video("TestCollection", "7597399138594065687", with_metadata=True)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        video = videos[0]

        importer.load_metadata(video)

        self.assertEqual(video.author, "testuser")
        self.assertEqual(video.description, "Test video description")
        self.assertEqual(video.collection_name, "TestCollection")
        self.assertEqual(video.upload_date, "20240101")

    def test_load_metadata_without_info_json(self):
        """Test loading metadata when .info.json doesn't exist."""
        self.create_test_video("TestCollection", "7597399138594065687", with_metadata=False)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        video = videos[0]

        importer.load_metadata(video)

        self.assertIsNone(video.author)
        self.assertIsNone(video.description)

    def test_load_metadata_alternative_fields(self):
        """Test loading metadata from alternative field names."""
        self.create_test_video(
            "TestCollection", "7597399138594065687",
            with_metadata=True,
            metadata_overrides={
                "uploader": None,
                "creator": "altcreator",
                "playlist_title": None,
                "playlist": "AltPlaylist",
            }
        )

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]

        importer.load_metadata(video)

        self.assertEqual(video.author, "altcreator")
        self.assertEqual(video.collection_name, "AltPlaylist")

    def test_load_metadata_deleted_video(self):
        """Test that deleted videos are marked correctly."""
        self.create_test_video(
            "TestCollection", "7597399138594065687",
            with_metadata=True,
            metadata_overrides={"availability": "private"}
        )

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]

        importer.load_metadata(video)

        self.assertTrue(video.deleted_from_tiktok)


class TestInferCollectionFromPath(TestVideoImporter):
    """Tests for inferring collection from file path."""

    def test_infer_collection_from_parent_directory(self):
        """Test inferring collection from parent directory name."""
        self.create_test_video("MyCollection", "7597399138594065687", with_metadata=False)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]

        importer.infer_collection_from_path(video)

        self.assertEqual(video.collection_name, "MyCollection")

    def test_infer_collection_skips_if_already_set(self):
        """Test that inference is skipped if collection is already set."""
        self.create_test_video("PathCollection", "7597399138594065687", with_metadata=False)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]

        # Set collection manually
        video.collection_name = "MetadataCollection"

        importer.infer_collection_from_path(video)

        # Should not be overwritten
        self.assertEqual(video.collection_name, "MetadataCollection")

    def test_infer_collection_skips_video_id_folders(self):
        """Test that video ID folders are not used as collection names."""
        # Create video directly in a video ID folder
        video_dir = self.source_dir / "7597399138594065687"
        video_dir.mkdir(parents=True)
        (video_dir / "7597399138594065687.mp4").write_text("video")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]

        importer.infer_collection_from_path(video)

        # Should not use the video ID as collection name
        self.assertIsNone(video.collection_name)


class TestCheckIfAlreadyImported(TestVideoImporter):
    """Tests for checking if videos are already imported."""

    def test_check_video_not_imported(self):
        """Test checking a video that hasn't been imported."""
        self.create_test_video("TestCollection", "7597399138594065687", in_dest=False)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]
        video.collection_name = "TestCollection"

        result = importer.check_if_already_imported(video)

        self.assertFalse(result)
        self.assertFalse(video.already_imported)

    def test_check_video_already_imported(self):
        """Test checking a video that has been imported."""
        # Create in both source and destination
        self.create_test_video("TestCollection", "7597399138594065687", in_dest=False)
        self.create_test_video("TestCollection", "7597399138594065687", in_dest=True)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]
        video.collection_name = "TestCollection"

        result = importer.check_if_already_imported(video)

        self.assertTrue(result)
        self.assertTrue(video.already_imported)

    def test_check_video_without_collection(self):
        """Test that videos without collection are not marked as imported."""
        self.create_test_video("TestCollection", "7597399138594065687", in_dest=False)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()
        video = videos[0]
        video.collection_name = None

        result = importer.check_if_already_imported(video)

        self.assertFalse(result)


class TestScanDestinationVideos(TestVideoImporter):
    """Tests for scanning destination directory."""

    def test_scan_empty_destination(self):
        """Test scanning an empty destination."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        video_ids = importer.scan_destination_videos()

        self.assertEqual(len(video_ids), 0)

    def test_scan_destination_with_videos(self):
        """Test scanning destination with existing videos."""
        self.create_test_video("Collection1", "7597399138594065687", in_dest=True)
        self.create_test_video("Collection1", "7597399138594065688", in_dest=True)
        self.create_test_video("Collection2", "7597399138594065689", in_dest=True)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        video_ids = importer.scan_destination_videos()

        self.assertEqual(len(video_ids), 3)
        self.assertIn("7597399138594065687", video_ids)
        self.assertIn("7597399138594065688", video_ids)
        self.assertIn("7597399138594065689", video_ids)

    def test_scan_nonexistent_destination(self):
        """Test scanning a nonexistent destination."""
        shutil.rmtree(self.dest_dir)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        video_ids = importer.scan_destination_videos()

        self.assertEqual(len(video_ids), 0)


class TestAnalyze(TestVideoImporter):
    """Tests for the full analysis workflow."""

    def test_analyze_empty_source(self):
        """Test analyzing an empty source directory."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        report = importer.analyze()

        self.assertEqual(report.total_videos_found, 0)
        self.assertEqual(report.videos_to_import, 0)

    def test_analyze_single_video_to_import(self):
        """Test analyzing with a single video to import."""
        self.create_test_video("TestCollection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        report = importer.analyze()

        self.assertEqual(report.total_videos_found, 1)
        self.assertEqual(report.videos_with_metadata, 1)
        self.assertEqual(report.videos_with_collection, 1)
        self.assertEqual(report.videos_to_import, 1)
        self.assertEqual(report.videos_already_imported, 0)

    def test_analyze_skips_already_imported(self):
        """Test that already imported videos are skipped."""
        self.create_test_video("TestCollection", "7597399138594065687", in_dest=False)
        self.create_test_video("TestCollection", "7597399138594065687", in_dest=True)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        report = importer.analyze()

        self.assertEqual(report.total_videos_found, 1)
        self.assertEqual(report.videos_already_imported, 1)
        self.assertEqual(report.videos_to_import, 0)

    def test_analyze_tracks_deleted_videos(self):
        """Test that deleted videos are tracked."""
        self.create_test_video(
            "TestCollection", "7597399138594065687",
            metadata_overrides={"availability": "private"}
        )

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        report = importer.analyze()

        self.assertEqual(report.videos_deleted_from_tiktok, 1)
        self.assertEqual(report.videos_to_import, 1)

    def test_analyze_tracks_videos_without_collection(self):
        """Test that videos without collection are tracked."""
        # Create video without metadata and with video ID as folder name
        video_dir = self.source_dir / "7597399138594065687"
        video_dir.mkdir(parents=True)
        (video_dir / "7597399138594065687.mp4").write_text("video")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        report = importer.analyze()

        self.assertEqual(report.total_videos_found, 1)
        self.assertEqual(report.videos_without_collection, 1)
        self.assertEqual(report.videos_to_import, 0)

    def test_analyze_groups_by_collection(self):
        """Test that videos are grouped by collection."""
        self.create_test_video("Collection1", "7597399138594065687")
        self.create_test_video("Collection1", "7597399138594065688")
        self.create_test_video("Collection2", "7597399138594065689")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        report = importer.analyze()

        self.assertEqual(len(report.by_collection), 2)
        self.assertEqual(len(report.by_collection["Collection1"]), 2)
        self.assertEqual(len(report.by_collection["Collection2"]), 1)


class TestCopyVideo(TestVideoImporter):
    """Tests for copying videos."""

    def test_copy_video_dry_run(self):
        """Test that dry run doesn't copy files."""
        self.create_test_video("TestCollection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=True)
        videos = importer.find_videos_in_source()
        video = videos[0]
        video.collection_name = "TestCollection"

        result = importer.copy_video(video)

        self.assertTrue(result)
        # Destination should not have the file
        dest_file = self.dest_dir / "TestCollection" / "7597399138594065687" / "7597399138594065687.mp4"
        self.assertFalse(dest_file.exists())

    def test_copy_video_actual_copy(self):
        """Test that actual copy works."""
        self.create_test_video("TestCollection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=False)
        videos = importer.find_videos_in_source()
        video = videos[0]
        video.collection_name = "TestCollection"

        result = importer.copy_video(video)

        self.assertTrue(result)
        # Destination should have the file
        dest_file = self.dest_dir / "TestCollection" / "7597399138594065687" / "7597399138594065687.mp4"
        self.assertTrue(dest_file.exists())

    def test_copy_video_copies_metadata(self):
        """Test that metadata files are copied."""
        self.create_test_video("TestCollection", "7597399138594065687", with_metadata=True)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=False)
        importer.analyze()

        video = importer.videos["7597399138594065687"]
        importer.copy_video(video)

        # Check that metadata was copied
        dest_dir = self.dest_dir / "TestCollection" / "7597399138594065687"
        self.assertTrue((dest_dir / "7597399138594065687.info.json").exists())
        self.assertTrue((dest_dir / "caption.txt").exists())

    def test_copy_video_without_collection(self):
        """Test that videos without collection are skipped."""
        self.create_test_video("TestCollection", "7597399138594065687", with_metadata=False)

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=False)
        videos = importer.find_videos_in_source()
        video = videos[0]
        video.collection_name = None

        result = importer.copy_video(video)

        self.assertFalse(result)

    def test_copy_video_sanitizes_collection_name(self):
        """Test that collection names are sanitized in destination path."""
        self.create_test_video("Test/Collection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=False)
        videos = importer.find_videos_in_source()
        video = videos[0]
        video.collection_name = "Test/Collection"

        result = importer.copy_video(video)

        self.assertTrue(result)
        # Should use sanitized name
        dest_file = self.dest_dir / "Test_Collection" / "7597399138594065687" / "7597399138594065687.mp4"
        self.assertTrue(dest_file.exists())


class TestExecuteImport(TestVideoImporter):
    """Tests for execute_import method."""

    def test_execute_import_empty(self):
        """Test executing import with no videos."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=True)
        importer.analyze()

        success, failed = importer.execute_import()

        self.assertEqual(success, 0)
        self.assertEqual(failed, 0)

    def test_execute_import_dry_run(self):
        """Test executing import in dry run mode."""
        self.create_test_video("TestCollection", "7597399138594065687")
        self.create_test_video("TestCollection", "7597399138594065688")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=True)
        importer.analyze()

        success, failed = importer.execute_import()

        self.assertEqual(success, 2)
        self.assertEqual(failed, 0)

        # Files should not be copied
        dest_file = self.dest_dir / "TestCollection" / "7597399138594065687" / "7597399138594065687.mp4"
        self.assertFalse(dest_file.exists())

    def test_execute_import_actual(self):
        """Test executing actual import."""
        self.create_test_video("TestCollection", "7597399138594065687")
        self.create_test_video("TestCollection", "7597399138594065688")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=False)
        importer.analyze()

        success, failed = importer.execute_import()

        self.assertEqual(success, 2)
        self.assertEqual(failed, 0)

        # Files should be copied
        dest_file1 = self.dest_dir / "TestCollection" / "7597399138594065687" / "7597399138594065687.mp4"
        dest_file2 = self.dest_dir / "TestCollection" / "7597399138594065688" / "7597399138594065688.mp4"
        self.assertTrue(dest_file1.exists())
        self.assertTrue(dest_file2.exists())


class TestVideoInfo(unittest.TestCase):
    """Tests for VideoInfo dataclass."""

    def test_video_info_defaults(self):
        """Test VideoInfo default values."""
        video = VideoInfo(
            video_id="123",
            source_path=Path("/source"),
            video_file=Path("/source/123.mp4"),
        )

        self.assertIsNone(video.info_json_path)
        self.assertIsNone(video.caption_path)
        self.assertIsNone(video.author)
        self.assertIsNone(video.collection_name)
        self.assertFalse(video.deleted_from_tiktok)
        self.assertFalse(video.already_imported)


class TestImportReport(unittest.TestCase):
    """Tests for ImportReport dataclass."""

    def test_import_report_defaults(self):
        """Test ImportReport default values."""
        report = ImportReport()

        self.assertEqual(report.total_videos_found, 0)
        self.assertEqual(report.videos_to_import, 0)
        self.assertEqual(len(report.by_collection), 0)
        self.assertEqual(len(report.videos_to_import_list), 0)


class TestImportMarker(TestVideoImporter):
    """Tests for import marker file creation."""

    def test_import_creates_marker_file(self):
        """Test that import creates import_info.json marker file."""
        self.create_test_video("TestCollection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=False)
        importer.analyze()

        video = importer.videos["7597399138594065687"]
        importer.copy_video(video)

        # Check that marker file was created
        marker_file = self.dest_dir / "TestCollection" / "7597399138594065687" / "import_info.json"
        self.assertTrue(marker_file.exists())

    def test_import_marker_contains_required_fields(self):
        """Test that import marker contains all required fields."""
        self.create_test_video("TestCollection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=False)
        importer.analyze()

        video = importer.videos["7597399138594065687"]
        importer.copy_video(video)

        marker_file = self.dest_dir / "TestCollection" / "7597399138594065687" / "import_info.json"
        with open(marker_file, 'r') as f:
            marker_data = json.load(f)

        # Check required fields
        self.assertEqual(marker_data["imported_from"], "TTDownloader")
        self.assertIn("import_date", marker_data)
        self.assertIn("source_path", marker_data)
        self.assertIn("original_filename", marker_data)
        self.assertIn("id_was_generated", marker_data)
        self.assertIn("inferred_collection", marker_data)
        self.assertIn("had_metadata", marker_data)

    def test_dry_run_does_not_create_marker(self):
        """Test that dry run does not create marker file."""
        self.create_test_video("TestCollection", "7597399138594065687")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir), dry_run=True)
        importer.analyze()

        video = importer.videos["7597399138594065687"]
        importer.copy_video(video)

        # Marker file should not exist
        marker_file = self.dest_dir / "TestCollection" / "7597399138594065687" / "import_info.json"
        self.assertFalse(marker_file.exists())


class TestGeneratedVideoId(TestVideoImporter):
    """Tests for generated video ID functionality."""

    def test_generate_video_id_returns_consistent_id(self):
        """Test that generated IDs are consistent for the same file."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        id1 = importer.generate_video_id(Path("/some/path/video.mp4"))
        id2 = importer.generate_video_id(Path("/some/path/video.mp4"))

        self.assertEqual(id1, id2)

    def test_generate_video_id_starts_with_g(self):
        """Test that generated IDs start with 'g' prefix."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        video_id = importer.generate_video_id(Path("/some/path/video.mp4"))

        self.assertTrue(video_id.startswith('g'))

    def test_generate_video_id_is_19_chars(self):
        """Test that generated IDs are 19 characters long."""
        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))

        video_id = importer.generate_video_id(Path("/some/path/video.mp4"))

        self.assertEqual(len(video_id), 19)

    def test_find_videos_generates_id_for_description_filenames(self):
        """Test that videos with description filenames get generated IDs."""
        # Create video with description-based filename (no video ID)
        video_dir = self.source_dir / "Food" / "Creator"
        video_dir.mkdir(parents=True)
        (video_dir / "Delicious recipe tutorial.mp4").write_text("video")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        self.assertTrue(videos[0].id_generated)
        self.assertTrue(videos[0].video_id.startswith('g'))


class TestFavoritesPathInference(TestVideoImporter):
    """Tests for Favorites collection path inference."""

    def test_infer_favorites_from_saved_data_path(self):
        """Test inferring Favorites collection from Saved/data/Favorites/videos structure."""
        # Create the typical TTDownloader structure
        video_dir = self.source_dir / "Saved" / "data" / "Favorites" / "videos"
        video_dir.mkdir(parents=True)
        (video_dir / "7597399138594065687.mp4").write_text("video")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        importer.infer_collection_from_path(videos[0])

        self.assertEqual(videos[0].collection_name, "Favorites")

    def test_infer_collection_from_top_level_folder(self):
        """Test inferring collection from top-level folder like Food."""
        video_dir = self.source_dir / "Food" / "CreatorName"
        video_dir.mkdir(parents=True)
        (video_dir / "7597399138594065687.mp4").write_text("video")

        importer = VideoImporter(str(self.source_dir), str(self.dest_dir))
        videos = importer.find_videos_in_source()

        self.assertEqual(len(videos), 1)
        importer.infer_collection_from_path(videos[0])

        self.assertEqual(videos[0].collection_name, "Food")


class TestSourceListFeature(TestVideoImporter):
    """Tests for the --source-list feature for fast SMB imports."""

    def test_find_videos_from_list_basic(self):
        """Test reading video filenames from a text file."""
        # Create a source list file
        list_file = Path(self.temp_dir) / "video_list.txt"
        list_file.write_text("7597399138594065687.mp4\n7458733418646457632.mp4\n")

        importer = VideoImporter(
            str(self.source_dir),
            str(self.dest_dir),
            source_list_path=str(list_file)
        )

        videos = importer.find_videos_from_list()

        self.assertEqual(len(videos), 2)
        self.assertEqual(videos[0].video_id, "7597399138594065687")
        self.assertEqual(videos[1].video_id, "7458733418646457632")

    def test_find_videos_from_list_skips_hidden_files(self):
        """Test that hidden files are skipped in source list."""
        list_file = Path(self.temp_dir) / "video_list.txt"
        list_file.write_text(".DS_Store\n7597399138594065687.mp4\n.hidden.mp4\n")

        importer = VideoImporter(
            str(self.source_dir),
            str(self.dest_dir),
            source_list_path=str(list_file)
        )

        videos = importer.find_videos_from_list()

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].video_id, "7597399138594065687")

    def test_find_videos_from_list_skips_non_video_files(self):
        """Test that non-video files are skipped in source list."""
        list_file = Path(self.temp_dir) / "video_list.txt"
        list_file.write_text("7597399138594065687.mp4\nsome_image.jpg\nreadme.txt\n")

        importer = VideoImporter(
            str(self.source_dir),
            str(self.dest_dir),
            source_list_path=str(list_file)
        )

        videos = importer.find_videos_from_list()

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].video_id, "7597399138594065687")

    def test_find_videos_from_list_handles_empty_lines(self):
        """Test that empty lines are ignored in source list."""
        list_file = Path(self.temp_dir) / "video_list.txt"
        list_file.write_text("\n7597399138594065687.mp4\n\n\n7458733418646457632.mp4\n")

        importer = VideoImporter(
            str(self.source_dir),
            str(self.dest_dir),
            source_list_path=str(list_file)
        )

        videos = importer.find_videos_from_list()

        self.assertEqual(len(videos), 2)

    def test_analyze_uses_source_list_when_provided(self):
        """Test that analyze() uses source list file when provided."""
        # Create a source list file
        list_file = Path(self.temp_dir) / "video_list.txt"
        list_file.write_text("7597399138594065687.mp4\n")

        importer = VideoImporter(
            str(self.source_dir),
            str(self.dest_dir),
            source_list_path=str(list_file)
        )

        report = importer.analyze()

        self.assertEqual(report.total_videos_found, 1)

    def test_source_list_generates_ids_for_description_filenames(self):
        """Test that description-named files get generated IDs from source list."""
        list_file = Path(self.temp_dir) / "video_list.txt"
        list_file.write_text("some_description_video.mp4\n")

        importer = VideoImporter(
            str(self.source_dir),
            str(self.dest_dir),
            source_list_path=str(list_file)
        )

        videos = importer.find_videos_from_list()

        self.assertEqual(len(videos), 1)
        self.assertTrue(videos[0].video_id.startswith('g'))
        self.assertTrue(videos[0].id_generated)


if __name__ == '__main__':
    unittest.main()
