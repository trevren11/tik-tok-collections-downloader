#!/usr/bin/env python3
"""
Import previously downloaded TikTok videos into the organized collection structure.

This script scans a source directory for downloaded TikTok videos, reads their
metadata to determine collection assignments, and copies them to the proper
collection folders in the destination directory.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VideoInfo:
    """Information about a video found in the source directory."""
    video_id: str
    source_path: Path
    video_file: Path
    info_json_path: Optional[Path] = None
    caption_path: Optional[Path] = None

    # Metadata extracted from .info.json
    author: Optional[str] = None
    description: Optional[str] = None
    collection_id: Optional[str] = None
    collection_name: Optional[str] = None
    upload_date: Optional[str] = None

    # Original filename (useful when ID was generated)
    original_filename: Optional[str] = None
    # Whether ID was generated vs extracted
    id_generated: bool = False

    # Status flags
    deleted_from_tiktok: bool = False
    already_imported: bool = False
    destination_path: Optional[Path] = None


@dataclass
class ImportReport:
    """Summary of the import operation."""
    total_videos_found: int = 0
    videos_with_metadata: int = 0
    videos_with_collection: int = 0
    videos_deleted_from_tiktok: int = 0
    videos_already_imported: int = 0
    videos_to_import: int = 0
    videos_without_collection: int = 0

    by_collection: dict = field(default_factory=dict)
    videos_to_import_list: list = field(default_factory=list)
    videos_without_collection_list: list = field(default_factory=list)
    videos_already_imported_list: list = field(default_factory=list)


class VideoImporter:
    """Handles importing videos from a source directory to organized collections."""

    VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mkv', '.mov', '.avi'}

    def __init__(self, source_dir: str, dest_dir: str, dry_run: bool = True, verbose: bool = False,
                 videos_json_path: Optional[str] = None, source_list_path: Optional[str] = None):
        self.source_dir = Path(source_dir)
        self.dest_dir = Path(dest_dir)
        self.dry_run = dry_run
        self.verbose = verbose
        self.videos: dict[str, VideoInfo] = {}
        self.report = ImportReport()
        self.videos_json_data: Optional[dict] = None
        self.source_list_path = Path(source_list_path) if source_list_path else None

        # Load videos.json if provided for collection lookup
        if videos_json_path:
            self._load_videos_json(Path(videos_json_path))

    def _load_videos_json(self, path: Path) -> None:
        """Load videos.json for collection lookup."""
        if path.exists():
            try:
                self.log(f"Loading videos.json from {path}...")
                with open(path, 'r', encoding='utf-8') as f:
                    self.videos_json_data = json.load(f)
                self.log(f"Loaded {len(self.videos_json_data)} videos from videos.json for collection lookup")
            except (json.JSONDecodeError, IOError) as e:
                self.log(f"Warning: Could not load videos.json: {e}")

    def log(self, message: str, verbose_only: bool = False):
        """Print a log message."""
        if verbose_only and not self.verbose:
            return
        print(message)

    def sanitize_collection_name(self, name: str) -> str:
        """Sanitize collection name for use as folder name."""
        return "".join(c if c.isalnum() or c in " -_" else "_" for c in name)

    def extract_video_id(self, filename: str) -> Optional[str]:
        """Extract video ID from filename. TikTok video IDs are typically 19-digit numbers."""
        # Try to find a 17-20 digit number in the filename
        match = re.search(r'(\d{17,20})', filename)
        if match:
            return match.group(1)
        return None

    def generate_video_id(self, file_path: Path) -> str:
        """Generate a unique ID for videos without a proper TikTok video ID.

        Uses a hash of the file path to create a consistent, unique identifier.
        """
        # Use the relative path to generate a consistent ID
        path_str = str(file_path)
        hash_obj = hashlib.sha256(path_str.encode())
        # Use first 19 characters to match TikTok ID length (prefixed with 'g' to indicate generated)
        return 'g' + hash_obj.hexdigest()[:18]

    def find_videos_in_source(self) -> list[VideoInfo]:
        """Scan source directory for video files and their metadata."""
        self.log(f"Scanning source directory: {self.source_dir}")
        videos = []
        skipped_no_id = 0

        if not self.source_dir.exists():
            self.log(f"ERROR: Source directory does not exist: {self.source_dir}")
            return videos

        # Walk through all subdirectories
        for root, dirs, files in os.walk(self.source_dir):
            root_path = Path(root)

            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in files:
                # Skip hidden files
                if filename.startswith('.'):
                    continue

                file_path = root_path / filename

                # Check if it's a video file
                if file_path.suffix.lower() not in self.VIDEO_EXTENSIONS:
                    continue

                # Skip partial downloads
                if '.part' in filename:
                    continue

                # Try to extract video ID from filename
                video_id = self.extract_video_id(filename)
                id_generated = False

                if not video_id:
                    # Generate an ID for videos without one (like description-named files)
                    video_id = self.generate_video_id(file_path)
                    id_generated = True
                    skipped_no_id += 1
                    self.log(f"  Generated ID {video_id} for: {filename}", verbose_only=True)

                # Create VideoInfo object
                video_info = VideoInfo(
                    video_id=video_id,
                    source_path=root_path,
                    video_file=file_path,
                    original_filename=filename,
                    id_generated=id_generated,
                )

                # Look for associated metadata files
                # Check for .info.json in same directory
                filename_base = filename.rsplit('.', 1)[0]
                info_json_candidates = [
                    root_path / f"{video_id}.info.json",
                    root_path / f"{filename_base}.info.json",
                    file_path.with_suffix('.info.json'),
                ]

                for info_path in info_json_candidates:
                    if info_path.exists():
                        video_info.info_json_path = info_path
                        break

                # Check for caption.txt
                caption_candidates = [
                    root_path / "caption.txt",
                    root_path / f"{video_id}_caption.txt",
                    root_path / f"{filename_base}_caption.txt",
                ]

                for caption_path in caption_candidates:
                    if caption_path.exists():
                        video_info.caption_path = caption_path
                        break

                videos.append(video_info)

        self.log(f"Found {len(videos)} video files ({skipped_no_id} with generated IDs)")
        return videos

    def find_videos_from_list(self) -> list[VideoInfo]:
        """Read video filenames from a text file instead of scanning the source directory.

        This is much faster when source is on SMB/network storage.
        The file should contain one filename per line (just the basename, not full path).
        """
        videos = []
        skipped_no_id = 0

        if not self.source_list_path or not self.source_list_path.exists():
            self.log(f"ERROR: Source list file does not exist: {self.source_list_path}")
            return videos

        self.log(f"Reading video list from: {self.source_list_path}")

        with open(self.source_list_path, 'r', encoding='utf-8') as f:
            filenames = [line.strip() for line in f if line.strip()]

        self.log(f"Found {len(filenames)} entries in source list")

        for filename in filenames:
            # Skip hidden files
            if filename.startswith('.'):
                continue

            # Check if it looks like a video file
            file_path = self.source_dir / filename
            if file_path.suffix.lower() not in self.VIDEO_EXTENSIONS:
                continue

            # Skip partial downloads
            if '.part' in filename:
                continue

            # Try to extract video ID from filename
            video_id = self.extract_video_id(filename)
            id_generated = False

            if not video_id:
                # Generate an ID for videos without one (like description-named files)
                video_id = self.generate_video_id(file_path)
                id_generated = True
                skipped_no_id += 1
                self.log(f"  Generated ID {video_id} for: {filename}", verbose_only=True)

            # Create VideoInfo object
            # Note: We construct the path but don't verify it exists (that's the point of using a list)
            video_info = VideoInfo(
                video_id=video_id,
                source_path=self.source_dir,
                video_file=file_path,
                original_filename=filename,
                id_generated=id_generated,
            )

            # For list-based scanning, we don't look for metadata files
            # (would require SMB access which defeats the purpose)
            # Collection will be inferred from videos.json or path

            videos.append(video_info)

        self.log(f"Processed {len(videos)} video files from list ({skipped_no_id} with generated IDs)")
        return videos

    def load_metadata(self, video: VideoInfo) -> None:
        """Load metadata from .info.json file into VideoInfo."""
        if not video.info_json_path or not video.info_json_path.exists():
            return

        try:
            with open(video.info_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            video.author = data.get('uploader') or data.get('creator') or data.get('uploader_id')
            video.description = data.get('description') or data.get('title')
            video.upload_date = data.get('upload_date')

            # Try to find collection info in various places
            # Some downloaders store this in different fields
            video.collection_name = (
                data.get('playlist_title') or
                data.get('playlist') or
                data.get('collection_name') or
                data.get('album')
            )
            video.collection_id = (
                data.get('playlist_id') or
                data.get('collection_id')
            )

            # Check availability status
            availability = data.get('availability')
            if availability and availability != 'public':
                video.deleted_from_tiktok = True

        except (json.JSONDecodeError, IOError) as e:
            self.log(f"  Error reading metadata for {video.video_id}: {e}", verbose_only=True)

    def infer_collection_from_path(self, video: VideoInfo) -> None:
        """Try to infer collection name from the file path structure.

        First checks videos.json for the authoritative collection, then falls back
        to path-based inference.

        Handles various structures:
        - /TikTok/Food/CreatorName/video.mp4 -> "Food"
        - /TikTok/Saved/data/Favorites/videos/video_id.mp4 -> "Favorites"
        - /TikTok/CollectionName/video_id/video.mp4 -> "CollectionName"
        """
        if video.collection_name:
            return

        # First, check videos.json for the authoritative collection
        if self.videos_json_data and video.video_id in self.videos_json_data:
            tracked = self.videos_json_data[video.video_id]
            if tracked.get('collection_name'):
                video.collection_name = tracked['collection_name']
                video.collection_id = tracked.get('collection_id')
                self.log(f"  Found collection '{video.collection_name}' in videos.json for {video.video_id}", verbose_only=True)
                return

        # Fall back to path-based inference
        try:
            rel_path = video.source_path.relative_to(self.source_dir)
            parts = rel_path.parts
        except ValueError:
            parts = video.source_path.parts

        if not parts:
            return

        # Special handling for "Saved/data/Favorites/videos" structure
        if len(parts) >= 3 and parts[0] == "Saved" and "Favorites" in parts:
            video.collection_name = "Favorites"
            self.log(f"  Inferred collection 'Favorites' from path for {video.video_id}", verbose_only=True)
            return

        # For structures like "Food/CreatorName/video.mp4", use top-level folder
        # Skip folders that look like video IDs or special names
        skip_names = {'data', 'videos', 'covers', '.appdata', 'Saved'}

        for part in parts:
            # Skip if it looks like just a video ID folder
            if re.match(r'^\d{17,20}$', part):
                continue
            # Skip known non-collection folders
            if part in skip_names:
                continue
            # Use this as collection name
            video.collection_name = part
            self.log(f"  Inferred collection '{part}' from path for {video.video_id}", verbose_only=True)
            return

    def check_if_already_imported(self, video: VideoInfo) -> bool:
        """Check if video already exists in destination."""
        if not video.collection_name:
            return False

        sanitized_name = self.sanitize_collection_name(video.collection_name)
        dest_collection_path = self.dest_dir / sanitized_name / video.video_id
        video.destination_path = dest_collection_path

        # Check if video file exists in destination
        for ext in self.VIDEO_EXTENSIONS:
            if (dest_collection_path / f"{video.video_id}{ext}").exists():
                video.already_imported = True
                return True

        return False

    def scan_destination_videos(self) -> set[str]:
        """Scan destination directory to get set of existing video IDs."""
        existing_ids = set()

        if not self.dest_dir.exists():
            return existing_ids

        dirs_scanned = 0
        for root, dirs, files in os.walk(self.dest_dir):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            dirs_scanned += 1
            if dirs_scanned % 100 == 0:
                print(f"  Scanned {dirs_scanned} directories, found {len(existing_ids)} videos...", end='\r')

            for filename in files:
                if filename.startswith('.'):
                    continue
                if Path(filename).suffix.lower() in self.VIDEO_EXTENSIONS:
                    video_id = self.extract_video_id(filename)
                    if video_id:
                        existing_ids.add(video_id)
                    # Also check for generated IDs (start with 'g')
                    elif filename.startswith('g') and len(filename) >= 19:
                        # Could be a generated ID filename
                        potential_id = filename.rsplit('.', 1)[0]
                        if len(potential_id) == 19 and potential_id.startswith('g'):
                            existing_ids.add(potential_id)

        # Clear the progress line
        if dirs_scanned >= 100:
            print(" " * 60, end='\r')

        return existing_ids

    def find_recoverable_deleted_videos(self, source_ids: set[str]) -> list[VideoInfo]:
        """Find deleted videos from videos.json that exist in source and aren't downloaded.

        This is much faster than full scanning - uses videos.json metadata to skip
        destination scanning entirely.
        """
        if not self.videos_json_data:
            self.log("ERROR: videos.json required for fast deleted mode")
            return []

        recoverable = []
        for video_id, data in self.videos_json_data.items():
            # Skip if already downloaded
            if data.get('downloaded'):
                continue

            # Check if deleted from TikTok
            is_deleted = (
                data.get('deleted_from_tiktok') or
                data.get('availability') not in (None, 'public') or
                data.get('status') == 'deleted'
            )
            if not is_deleted:
                continue

            # Check if we have it in source
            if video_id not in source_ids:
                continue

            # Create VideoInfo for this recoverable video
            video_info = VideoInfo(
                video_id=video_id,
                source_path=self.source_dir,
                video_file=self.source_dir / f"{video_id}.mp4",
                original_filename=f"{video_id}.mp4",
                collection_name=data.get('collection_name'),
                collection_id=data.get('collection_id'),
                deleted_from_tiktok=True,
            )
            recoverable.append(video_info)

        return recoverable

    def analyze_fast_deleted(self) -> ImportReport:
        """Fast analysis mode - only find deleted videos that can be recovered.

        Skips destination scanning entirely, trusts videos.json downloaded field.
        """
        self.report = ImportReport()

        # Build set of video IDs from source list
        if not self.source_list_path or not self.source_list_path.exists():
            self.log("ERROR: --source-list required for fast deleted mode")
            return self.report

        self.log(f"Reading source list from: {self.source_list_path}")
        with open(self.source_list_path, 'r', encoding='utf-8') as f:
            filenames = [line.strip() for line in f if line.strip()]

        # Extract video IDs from filenames
        source_ids = set()
        for filename in filenames:
            video_id = self.extract_video_id(filename)
            if video_id:
                source_ids.add(video_id)

        self.log(f"Found {len(source_ids)} video IDs in source list")

        # Find recoverable deleted videos
        videos = self.find_recoverable_deleted_videos(source_ids)
        self.report.total_videos_found = len(videos)
        self.report.videos_deleted_from_tiktok = len(videos)
        self.report.videos_to_import = len(videos)
        self.report.videos_to_import_list = videos

        # Group by collection
        for video in videos:
            if video.collection_name:
                self.report.videos_with_collection += 1
                if video.collection_name not in self.report.by_collection:
                    self.report.by_collection[video.collection_name] = []
                self.report.by_collection[video.collection_name].append(video)
            else:
                self.report.videos_without_collection += 1
                self.report.videos_without_collection_list.append(video)

            self.videos[video.video_id] = video

        return self.report

    def analyze_recover_failed(self, queue_path: Path) -> ImportReport:
        """Recover failed downloads that exist in source (favorites).

        Reads download_queue.json, finds failed videos that exist in source,
        and prepares them for import.
        """
        self.report = ImportReport()

        # Load download queue
        if not queue_path.exists():
            self.log(f"ERROR: download_queue.json not found at {queue_path}")
            return self.report

        self.log(f"Loading download queue from {queue_path}...")
        with open(queue_path, 'r', encoding='utf-8') as f:
            queue = json.load(f)

        failed = queue.get('failed', [])
        self.log(f"Found {len(failed)} failed videos in queue")

        # Build set of video IDs from source list
        if not self.source_list_path or not self.source_list_path.exists():
            self.log("ERROR: --source-list required for recover-failed mode")
            return self.report

        self.log(f"Reading source list from: {self.source_list_path}")
        with open(self.source_list_path, 'r', encoding='utf-8') as f:
            filenames = [line.strip() for line in f if line.strip()]

        source_ids = set()
        for filename in filenames:
            video_id = self.extract_video_id(filename)
            if video_id:
                source_ids.add(video_id)

        self.log(f"Found {len(source_ids)} video IDs in source list")

        # Find failed videos that exist in source
        videos = []
        for item in failed:
            if isinstance(item, dict):
                video_id = item.get('id')
                collection_name = item.get('collection')
            else:
                video_id = item
                collection_name = None

            if video_id not in source_ids:
                continue

            # Create VideoInfo for this recoverable video
            video_info = VideoInfo(
                video_id=video_id,
                source_path=self.source_dir,
                video_file=self.source_dir / f"{video_id}.mp4",
                original_filename=f"{video_id}.mp4",
                collection_name=collection_name,
                deleted_from_tiktok=True,  # Failed downloads are usually deleted
            )
            videos.append(video_info)

        self.log(f"Found {len(videos)} failed videos recoverable from source")

        self.report.total_videos_found = len(videos)
        self.report.videos_deleted_from_tiktok = len(videos)
        self.report.videos_to_import = len(videos)
        self.report.videos_to_import_list = videos

        # Group by collection
        for video in videos:
            if video.collection_name:
                self.report.videos_with_collection += 1
                if video.collection_name not in self.report.by_collection:
                    self.report.by_collection[video.collection_name] = []
                self.report.by_collection[video.collection_name].append(video)
            else:
                self.report.videos_without_collection += 1
                self.report.videos_without_collection_list.append(video)

            self.videos[video.video_id] = video

        return self.report

    def update_download_queue(self, queue_path: Path, imported_ids: set[str]) -> int:
        """Remove successfully imported videos from the failed queue.

        Returns the number of entries removed.
        """
        if not queue_path.exists():
            return 0

        with open(queue_path, 'r', encoding='utf-8') as f:
            queue = json.load(f)

        failed = queue.get('failed', [])
        original_count = len(failed)

        # Filter out imported videos
        new_failed = []
        for item in failed:
            video_id = item.get('id') if isinstance(item, dict) else item
            if video_id not in imported_ids:
                new_failed.append(item)

        queue['failed'] = new_failed
        removed = original_count - len(new_failed)

        if removed > 0 and not self.dry_run:
            with open(queue_path, 'w', encoding='utf-8') as f:
                json.dump(queue, f, indent=2)
            self.log(f"Removed {removed} entries from failed queue")

        return removed

    def analyze(self) -> ImportReport:
        """Analyze source and destination to determine what needs to be imported."""
        self.report = ImportReport()

        # Find all videos in source (use list file if provided, otherwise scan)
        if self.source_list_path:
            videos = self.find_videos_from_list()
        else:
            videos = self.find_videos_in_source()
        self.report.total_videos_found = len(videos)

        # Scan destination for existing videos
        self.log(f"Scanning destination directory: {self.dest_dir}")
        existing_video_ids = self.scan_destination_videos()
        self.log(f"Found {len(existing_video_ids)} existing videos in destination")

        # Process each video
        for video in videos:
            # Load metadata
            self.load_metadata(video)

            if video.info_json_path:
                self.report.videos_with_metadata += 1

            # Try to infer collection from path if not in metadata
            self.infer_collection_from_path(video)

            if video.collection_name:
                self.report.videos_with_collection += 1

            if video.deleted_from_tiktok:
                self.report.videos_deleted_from_tiktok += 1

            # Check if already imported (by video ID)
            if video.video_id in existing_video_ids:
                video.already_imported = True
                self.report.videos_already_imported += 1
                self.report.videos_already_imported_list.append(video)
                continue

            # Also check by destination path
            self.check_if_already_imported(video)
            if video.already_imported:
                self.report.videos_already_imported += 1
                self.report.videos_already_imported_list.append(video)
                continue

            # Categorize for import
            if video.collection_name:
                self.report.videos_to_import += 1
                self.report.videos_to_import_list.append(video)

                # Track by collection
                if video.collection_name not in self.report.by_collection:
                    self.report.by_collection[video.collection_name] = []
                self.report.by_collection[video.collection_name].append(video)
            else:
                self.report.videos_without_collection += 1
                self.report.videos_without_collection_list.append(video)

            self.videos[video.video_id] = video

        return self.report

    def print_report(self) -> None:
        """Print a summary report of the analysis."""
        print("\n" + "="*60)
        print("IMPORT ANALYSIS REPORT")
        print("="*60)
        print(f"\nSource: {self.source_dir}")
        print(f"Destination: {self.dest_dir}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")

        print(f"\n--- Summary ---")
        print(f"Total videos found in source: {self.report.total_videos_found}")
        print(f"Videos with metadata (.info.json): {self.report.videos_with_metadata}")
        print(f"Videos with collection info: {self.report.videos_with_collection}")
        print(f"Videos marked as deleted from TikTok: {self.report.videos_deleted_from_tiktok}")
        print(f"Videos already in destination: {self.report.videos_already_imported}")
        print(f"Videos ready to import: {self.report.videos_to_import}")
        print(f"Videos without collection (need manual review): {self.report.videos_without_collection}")

        if self.report.by_collection:
            print(f"\n--- By Collection ---")
            for collection_name, videos in sorted(self.report.by_collection.items()):
                deleted_count = sum(1 for v in videos if v.deleted_from_tiktok)
                deleted_str = f" ({deleted_count} deleted from TikTok)" if deleted_count else ""
                print(f"  {collection_name}: {len(videos)} videos{deleted_str}")

        if self.report.videos_without_collection_list and self.verbose:
            print(f"\n--- Videos Without Collection ---")
            for video in self.report.videos_without_collection_list[:20]:
                print(f"  {video.video_id}: {video.video_file}")
            if len(self.report.videos_without_collection_list) > 20:
                print(f"  ... and {len(self.report.videos_without_collection_list) - 20} more")

        if self.report.videos_to_import_list and self.verbose:
            print(f"\n--- Videos to Import ---")
            for video in self.report.videos_to_import_list[:30]:
                deleted_str = " [DELETED]" if video.deleted_from_tiktok else ""
                print(f"  {video.video_id} -> {video.collection_name}{deleted_str}")
            if len(self.report.videos_to_import_list) > 30:
                print(f"  ... and {len(self.report.videos_to_import_list) - 30} more")

        print("\n" + "="*60)

    def copy_video(self, video: VideoInfo) -> bool:
        """Copy a video and its metadata to the destination."""
        if not video.collection_name:
            self.log(f"  Skipping {video.video_id}: no collection assigned")
            return False

        sanitized_name = self.sanitize_collection_name(video.collection_name)
        dest_folder = self.dest_dir / sanitized_name / video.video_id

        if self.dry_run:
            self.log(f"  [DRY RUN] Would copy {video.video_id} to {dest_folder}")
            return True

        try:
            # Create destination folder
            dest_folder.mkdir(parents=True, exist_ok=True)

            # Copy video file
            dest_video = dest_folder / f"{video.video_id}{video.video_file.suffix}"
            shutil.copy2(video.video_file, dest_video)
            self.log(f"  Copied video: {dest_video}")

            # Copy metadata if exists
            if video.info_json_path and video.info_json_path.exists():
                dest_info = dest_folder / f"{video.video_id}.info.json"
                shutil.copy2(video.info_json_path, dest_info)

            # Copy or create caption
            if video.caption_path and video.caption_path.exists():
                dest_caption = dest_folder / "caption.txt"
                shutil.copy2(video.caption_path, dest_caption)
            elif video.description:
                dest_caption = dest_folder / "caption.txt"
                with open(dest_caption, 'w', encoding='utf-8') as f:
                    f.write(video.description)

            # Create import marker file
            self._create_import_marker(video, dest_folder)

            return True

        except (IOError, OSError) as e:
            self.log(f"  ERROR copying {video.video_id}: {e}")
            return False

    def _create_import_marker(self, video: VideoInfo, dest_folder: Path) -> None:
        """Create a marker file indicating this video was imported from TTDownloader."""
        import datetime

        marker_data = {
            "imported_from": "TTDownloader",
            "import_date": datetime.datetime.now().isoformat(),
            "source_path": str(video.video_file),
            "original_filename": video.original_filename,
            "id_was_generated": video.id_generated,
            "inferred_collection": video.collection_name,
            "had_metadata": video.info_json_path is not None,
        }

        marker_file = dest_folder / "import_info.json"
        with open(marker_file, 'w', encoding='utf-8') as f:
            json.dump(marker_data, f, indent=2)

    def reconcile_with_videos_json(self, videos_json_path: Path) -> dict:
        """Update videos.json to mark imported videos as downloaded.

        Returns dict with counts of updated records.
        """
        import datetime

        if not videos_json_path.exists():
            self.log(f"videos.json not found at {videos_json_path}")
            return {"updated": 0, "not_found": 0}

        # Load existing videos.json
        with open(videos_json_path, 'r', encoding='utf-8') as f:
            videos_data = json.load(f)

        updated = 0
        not_found = 0

        for video in self.report.videos_to_import_list:
            if video.video_id in videos_data:
                # Update existing entry
                entry = videos_data[video.video_id]
                sanitized_name = self.sanitize_collection_name(video.collection_name)
                dest_path = self.dest_dir / sanitized_name / video.video_id / f"{video.video_id}{video.video_file.suffix}"

                entry["downloaded"] = True
                entry["download_path"] = str(dest_path)
                entry["downloaded_at"] = datetime.datetime.now().isoformat()
                entry["imported_from_ttdownloader"] = True

                updated += 1
                self.log(f"  Updated: {video.video_id} ({entry.get('collection_name', 'unknown')})", verbose_only=True)
            else:
                not_found += 1
                self.log(f"  Not in videos.json: {video.video_id}", verbose_only=True)

        if updated > 0 and not self.dry_run:
            # Save updated videos.json
            with open(videos_json_path, 'w', encoding='utf-8') as f:
                json.dump(videos_data, f, indent=2)
            self.log(f"Saved {updated} updates to videos.json")

        return {"updated": updated, "not_found": not_found}

    def execute_import(self) -> tuple[int, int]:
        """Execute the import operation. Returns (success_count, failure_count)."""
        if not self.report.videos_to_import_list:
            self.log("No videos to import.")
            return 0, 0

        success = 0
        failed = 0

        self.log(f"\n{'[DRY RUN] ' if self.dry_run else ''}Importing {len(self.report.videos_to_import_list)} videos...")

        for video in self.report.videos_to_import_list:
            if self.copy_video(video):
                success += 1
            else:
                failed += 1

        self.log(f"\nImport complete: {success} succeeded, {failed} failed")
        return success, failed


def main():
    parser = argparse.ArgumentParser(
        description='Import previously downloaded TikTok videos into organized collections.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (default) - see what would be imported
  python import_videos.py /Volumes/media/TikTok /Volumes/media/TikTok-Organized/collections

  # Verbose dry run with details
  python import_videos.py -v /source /dest

  # Actually copy files (use --execute)
  python import_videos.py --execute /source /dest
        """
    )

    parser.add_argument('source', help='Source directory containing downloaded TikTok videos')
    parser.add_argument('destination', help='Destination directory for organized collections')
    parser.add_argument('--execute', action='store_true',
                        help='Actually copy files (default is dry-run)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed output')
    parser.add_argument('--deleted-only', action='store_true',
                        help='Only import videos that are deleted from TikTok')
    parser.add_argument('--collection', type=str,
                        help='Only import videos from a specific collection')
    parser.add_argument('--limit', type=int, default=0,
                        help='Limit number of videos to import (0 = no limit)')
    parser.add_argument('--reconcile', type=str, metavar='VIDEOS_JSON',
                        help='Update videos.json to mark imported videos as downloaded')
    parser.add_argument('--source-list', type=str, metavar='FILE',
                        help='Read video filenames from a text file instead of scanning (much faster for SMB)')
    parser.add_argument('--fast-deleted', action='store_true',
                        help='Fast mode: only recover deleted videos using videos.json (skips destination scan)')
    parser.add_argument('--recover-failed', type=str, metavar='QUEUE_JSON',
                        help='Recover failed downloads from download_queue.json that exist in source')

    args = parser.parse_args()

    dry_run = not args.execute

    importer = VideoImporter(
        source_dir=args.source,
        dest_dir=args.destination,
        dry_run=dry_run,
        verbose=args.verbose,
        videos_json_path=args.reconcile,
        source_list_path=args.source_list,
    )

    # Analyze (use appropriate mode)
    if args.recover_failed:
        if not args.source_list:
            print("ERROR: --recover-failed requires --source-list")
            return 1
        report = importer.analyze_recover_failed(Path(args.recover_failed))
    elif args.fast_deleted:
        if not args.reconcile:
            print("ERROR: --fast-deleted requires --reconcile to specify videos.json path")
            return 1
        report = importer.analyze_fast_deleted()
    else:
        report = importer.analyze()

    # Apply filters if specified
    if args.deleted_only:
        report.videos_to_import_list = [v for v in report.videos_to_import_list if v.deleted_from_tiktok]
        report.videos_to_import = len(report.videos_to_import_list)

    if args.collection:
        report.videos_to_import_list = [v for v in report.videos_to_import_list
                                         if v.collection_name and args.collection.lower() in v.collection_name.lower()]
        report.videos_to_import = len(report.videos_to_import_list)

    if args.limit > 0:
        report.videos_to_import_list = report.videos_to_import_list[:args.limit]
        report.videos_to_import = len(report.videos_to_import_list)

    # Print report
    importer.print_report()

    # Execute import
    if report.videos_to_import > 0:
        success, failed = importer.execute_import()

        if not dry_run:
            print(f"\nFinal result: {success} videos imported, {failed} failed")

        # Reconcile with videos.json if requested
        if args.reconcile:
            videos_json_path = Path(args.reconcile)
            print(f"\nReconciling with {videos_json_path}...")
            reconcile_result = importer.reconcile_with_videos_json(videos_json_path)
            if dry_run:
                print(f"[DRY RUN] Would update {reconcile_result['updated']} entries in videos.json")
                print(f"[DRY RUN] {reconcile_result['not_found']} videos not found in videos.json")
            else:
                print(f"Updated {reconcile_result['updated']} entries in videos.json")
                print(f"{reconcile_result['not_found']} videos not found in videos.json (not tracked)")

        # Update download queue if recovering failed videos
        if args.recover_failed:
            queue_path = Path(args.recover_failed)
            imported_ids = {v.video_id for v in report.videos_to_import_list}
            print(f"\nUpdating download queue at {queue_path}...")
            removed = importer.update_download_queue(queue_path, imported_ids)
            if dry_run:
                print(f"[DRY RUN] Would remove {removed} entries from failed queue")
            else:
                print(f"Removed {removed} entries from failed queue")
    else:
        print("\nNo videos to import.")

    return 0 if report.videos_to_import == 0 or (not dry_run and failed == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
