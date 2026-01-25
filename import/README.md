# TikTok Video Import Tool

Import previously downloaded TikTok videos (from TTDownloader or similar tools) into the organized collection structure used by this project.

## Features

- **Dry run by default** - See what would be imported without copying anything
- **Collection inference** - Automatically determines collection from folder structure
- **Duplicate detection** - Skips videos already in destination
- **Import markers** - Creates `import_info.json` in each imported video folder for tracking
- **Flexible filtering** - Filter by collection, limit count, or deleted-only videos

## Usage

### Basic Dry Run (Recommended First Step)

```bash
# See what would be imported without copying anything
python3 import/import_videos.py \
    "/Volumes/media/TikTok/Saved/data/Favorites/videos" \
    "/Volumes/media/TikTok-Organized/<USER>/collections"
```

### Verbose Dry Run (See Details)

```bash
python3 import/import_videos.py -v \
    "/Volumes/media/TikTok/Saved/data/Favorites/videos" \
    "/Volumes/media/TikTok-Organized/<USER>/collections"
```

### Import First 5 Videos (Test Import)

```bash
python3 import/import_videos.py --execute --limit 5 \
    "/Volumes/media/TikTok/Saved/data/Favorites/videos" \
    "/Volumes/media/TikTok-Organized/<USER>/collections"
```

### Import All Videos

```bash
python3 import/import_videos.py --execute \
    "/Volumes/media/TikTok/Saved/data/Favorites/videos" \
    "/Volumes/media/TikTok-Organized/<USER>/collections"
```

### Import Only Videos from a Specific Collection

```bash
python3 import/import_videos.py --execute --collection "Food" \
    "/Volumes/media/TikTok" \
    "/Volumes/media/TikTok-Organized/<USER>/collections"
```

### Import Only Deleted Videos

```bash
python3 import/import_videos.py --execute --deleted-only \
    "/Volumes/media/TikTok/Saved/data/Favorites/videos" \
    "/Volumes/media/TikTok-Organized/<USER>/collections"
```

### Fast Import with Source List (for SMB/Network Storage)

Scanning network directories can be slow. Generate a file list once, then use it for fast repeated runs:

```bash
# Step 1: Generate the file list (slow, but only once)
ls "/Volumes/media/TikTok/Saved/data/Favorites/videos/" > /tmp/favorites_list.txt

# Step 2: Use the list for fast imports
python3 import/import_videos.py -v --source-list /tmp/favorites_list.txt \
    --reconcile "/Volumes/media/TikTok-Organized/<USER>/collections/videos.json" \
    "/Volumes/media/TikTok/Saved/data/Favorites/videos" \
    "/Volumes/media/TikTok-Organized/<USER>/collections"
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `source` | Source directory containing downloaded videos |
| `destination` | Destination collections directory |
| `--execute` | Actually copy files (default is dry-run) |
| `-v, --verbose` | Show detailed output |
| `--limit N` | Only import first N videos (useful for testing) |
| `--collection NAME` | Only import videos matching collection name |
| `--deleted-only` | Only import videos marked as deleted from TikTok |
| `--source-list FILE` | Read video filenames from a text file instead of scanning (faster for SMB) |

## Import Marker File

Each imported video gets an `import_info.json` file containing:

```json
{
  "imported_from": "TTDownloader",
  "import_date": "2025-01-25T12:00:00.000000",
  "source_path": "/original/path/to/video.mp4",
  "original_filename": "7458733418646457632.mp4",
  "id_was_generated": false,
  "inferred_collection": "Favorites",
  "had_metadata": false
}
```

This allows you to:
- Identify which videos were imported vs downloaded by the main tool
- Filter/process imported videos separately later
- Track the original source location
- See in the UI that a video was imported (check for `import_info.json`)

## Source Folder Structures Supported

### TTDownloader Favorites
```
/TikTok/Saved/data/Favorites/videos/
├── 7458733418646457632.mp4
├── 7454252796334935301.mp4
└── ...
```
Videos are assigned to "Favorites" collection.

### Organized by Collection/Creator
```
/TikTok/Food/
├── CreatorName1/
│   └── video_description.mp4
├── CreatorName2/
│   └── another_video.mp4
└── ...
```
Videos are assigned to "Food" collection (top-level folder).

## Destination Structure

Videos are imported to:
```
<destination>/<collection_name>/<video_id>/
├── <video_id>.mp4
├── import_info.json       # Import marker (indicates TTDownloader origin)
├── <video_id>.info.json   # If source had metadata
└── caption.txt            # If source had caption
```

Example: A Favorites video `7458733418646457632.mp4` gets copied to:
```
/Volumes/media/TikTok-Organized/<USER>/collections/Favorites/7458733418646457632/
```

## Local Testing

For quick testing without SMB latency, copy a few videos locally first:

```bash
# Create local test directories
mkdir -p /tmp/tiktok_test_source/Favorites
mkdir -p /tmp/tiktok_test_dest

# Copy a few videos for testing
cp "/Volumes/media/TikTok/Saved/data/Favorites/videos/6819294004094487814.mp4" \
   /tmp/tiktok_test_source/Favorites/

# Run dry run on local files
python3 import/import_videos.py -v /tmp/tiktok_test_source /tmp/tiktok_test_dest

# Actually import
python3 import/import_videos.py --execute /tmp/tiktok_test_source /tmp/tiktok_test_dest

# Check result
ls -la /tmp/tiktok_test_dest/Favorites/6819294004094487814/
```

## Running Tests

```bash
cd import && python3 -m unittest test_import_videos -v
```
