# TikTok Collections Downloader

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=flat&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/trevren11)

Download and organize your TikTok saved videos by collection, including full metadata and captions.

## Overview

This tool uses your TikTok session cookies to access your personal collections (saved/favorited videos) and download them with their metadata. TikTok's official API doesn't expose collections, so we use authenticated session cookies from your browser.

## Features

- [x] List all your TikTok collections
- [x] Download videos from collections
- [x] Download favorited videos (not in any collection)
- [x] Save metadata (captions, author info, stats)
- [x] Organize into folders by collection name
- [x] Monitor for new videos (watch mode)
- [x] Download queue with state persistence
- [x] Web viewer to browse downloaded videos

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get Your TikTok Session Cookies

You need to extract cookies from your browser while logged into TikTok:

#### Option A: Browser DevTools (Recommended)

1. Go to [tiktok.com](https://www.tiktok.com) and log in
2. Open DevTools (F12 or right-click > Inspect)
3. Go to **Application** tab > **Cookies** > `https://www.tiktok.com`
4. Find and copy the `sessionid` cookie value

#### Option B: Cookie Export Extension

Use a browser extension like "Get cookies.txt" (Chrome) or "cookies.txt" (Firefox) to export cookies.

### 3. Configure

Copy the example config and add your cookies:

```bash
cp config.example.json config.json
```

Edit `config.json` with your cookie values.

## Usage

### List Collections

```bash
python tiktok_collections.py
```

This will display all your collections with their IDs and video counts.

### Monitor & Download

The main script `tiktok_monitor.py` handles syncing, downloading, and monitoring:

```bash
# Sync collections and videos, then download all
python tiktok_monitor.py

# Just sync (fetch collections and videos, update queue)
python tiktok_monitor.py --sync

# Just download (process the download queue)
python tiktok_monitor.py --download

# Watch mode - sync and download every N minutes
python tiktok_monitor.py --watch --interval 60

# Check current status
python tiktok_monitor.py --status
```

#### Options

| Option | Description |
|--------|-------------|
| `--sync` | Fetch collections and videos, update download queue |
| `--download` | Process pending downloads |
| `--watch` | Run sync + download periodically |
| `--status` | Show current sync/download status |
| `--interval, -i` | Watch interval in minutes (default: 60) |
| `--limit, -l` | Limit downloads per run |
| `--collection-limit` | Limit collections to sync |
| `--video-limit` | Limit videos per collection |
| `--full-sync` | Force full sync of all collections (fetch ALL pages, not just recent ~30) |
| `--fetch-all-favorites` | Fetch ALL favorited videos using API pagination |
| `--update-metadata` | Backfill enriched metadata (AI summaries, subtitles) for all downloaded videos |
| `--delete VIDEO_ID` | Delete specific video(s) by ID |
| `--delete-all` | Delete all downloaded videos |

#### Examples

```bash
# Download first 10 videos only
python tiktok_monitor.py --download --limit 10

# Sync only the first 2 collections, 50 videos each
python tiktok_monitor.py --sync --collection-limit 2 --video-limit 50

# Monitor every 30 minutes
python tiktok_monitor.py --watch -i 30

# Delete a specific video
python tiktok_monitor.py --delete 7597399138594065687

# Delete multiple videos
python tiktok_monitor.py --delete 7597399138594065687 7596230214078991638

# Delete all downloaded videos
python tiktok_monitor.py --delete-all

# Full sync - fetch ALL videos in ALL collections (not just recent ~30)
python tiktok_monitor.py --sync --full-sync

# Fetch ALL favorites (uses API pagination, more reliable than scroll-based)
python tiktok_monitor.py --fetch-all-favorites

# Backfill AI-generated metadata for previously downloaded videos
python tiktok_monitor.py --update-metadata
```

### Web Viewer

Browse your downloaded videos with the web viewer:

```bash
python viewer.py
```

Open http://localhost:8425 in your browser to:
- Browse collections
- Watch videos with metadata displayed
- See download status

### Run Tests

```bash
python -m unittest tests.test_monitor -v
```

## Docker

Run both the downloader and web viewer together using Docker:

### Quick Start

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Configuration

Create a `.env` file or set environment variables:

```bash
# Path to your downloads directory
DOWNLOAD_DIR=/path/to/your/downloads

# Sync interval in minutes (default: 120)
SYNC_INTERVAL=15

# Number of parallel downloads (default: 3)
MAX_PARALLEL=3

# Force full sync of all collections (fetch ALL pages, not just recent ~30)
FULL_SYNC=true

# Fetch ALL favorites on startup (one-time operation, may take a while)
FETCH_ALL_FAVORITES=true
```

These can also be set in `config.json`:

```json
{
  "sessionid": "YOUR_SESSIONID_HERE",
  "download_dir": "./downloads",
  "max_parallel": 3
}
```

**Rate Limiting**: The downloader automatically handles rate limiting with exponential backoff. When TikTok returns HTTP 429/530 errors, it will:
- Automatically increase delay between downloads
- Keep rate-limited videos in the queue for retry
- Gradually reduce delay after successful downloads

### docker-compose.yml

```yaml
version: '3.8'

services:
  tiktok-downloader:
    build: .
    container_name: tiktok-collections
    restart: unless-stopped
    ports:
      - "8425:8425"
    volumes:
      - ./config.json:/app/config/config.json:ro
      - ${DOWNLOAD_DIR:-./downloads}:/app/downloads
    environment:
      - SYNC_INTERVAL=${SYNC_INTERVAL:-30}
      - MAX_PARALLEL=${MAX_PARALLEL:-3}
```

The container will:
- Start the web viewer on port 8425
- Run the monitor in watch mode (sync + download periodically)
- Store all data in the mounted downloads directory

### Manual Docker Commands

```bash
# Build image
docker build -t tiktok-collections .

# Run with custom settings
docker run -d \
  -p 8425:8425 \
  -v $(pwd)/config.json:/app/config/config.json:ro \
  -v /path/to/downloads:/app/downloads \
  -e SYNC_INTERVAL=30 \
  --name tiktok-collections \
  tiktok-collections

# Run one-off sync
docker run --rm \
  -v $(pwd)/config.json:/app/config/config.json:ro \
  -v /path/to/downloads:/app/downloads \
  tiktok-collections python tiktok_monitor.py --sync
```

## How It Works

TikTok stores your collections/favorites server-side and exposes them through internal API endpoints. By providing your session cookies, this tool can:

1. Authenticate as your logged-in session
2. Query the internal API for your collections list
3. Fetch video details including captions/descriptions
4. Download videos with metadata preserved

## Architecture

### Directory Structure

After running the downloader, your data directory will look like:

```
downloads/
├── json/                          # Metadata files
│   ├── collections.json           # Collection metadata
│   ├── videos.json                # Video metadata
│   ├── download_queue.json        # Download state (pending/completed/failed)
│   ├── available_collections.json # Reference for exclude_collections config
│   ├── data.js                    # Data for web viewer
│   └── viewer.html                # Web viewer interface
├── Recipes/                       # Collection folder (sanitized name)
│   └── 7597399138594065687/       # Video folder (video ID)
│       ├── 7597399138594065687.mp4
│       ├── 7597399138594065687.info.json
│       └── caption.txt
├── Music/
│   └── .../
├── Favorites/                     # Saved videos not assigned to a collection
│   └── .../
└── .../
```

### Processing Flow

The downloader processes each collection completely before moving to the next:

```
┌─────────────────────────────────────────────────────────────┐
│                       SYNC MODE                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Fetch all collections from TikTok API                   │
│                                                              │
│  2. For each collection:                                    │
│     ┌──────────────────────────────────────────────────┐   │
│     │  a. Fetch videos for this collection              │   │
│     │  b. Queue new videos (collection-specific)        │   │
│     │  c. Download ALL queued videos for THIS collection│   │
│     │  d. Move to next collection                       │   │
│     └──────────────────────────────────────────────────┘   │
│                                                              │
│  3. Process favorites (special collection)                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

This per-collection approach:
- Keeps the download queue smaller and more manageable
- Makes progress more predictable (complete one collection at a time)
- Reduces memory usage from large JSON files

### Watch Mode

In watch mode, the downloader runs periodically with background processing:

```
┌─────────────────────────────────────────────────────────────┐
│                      WATCH MODE                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐    ┌─────────────────────────────┐    │
│  │  Background     │    │  Main Thread                │    │
│  │  Download       │◄───┤  Periodic Sync              │    │
│  │  Worker         │    │  (adds to queue)            │    │
│  └─────────────────┘    └─────────────────────────────┘    │
│         │                                                    │
│         ▼                                                    │
│  Processes pending queue continuously                       │
│  (resumes on restart from saved state)                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Rate Limiting

Downloads use automatic exponential backoff when rate limited:

- **On 429/530 errors**: Delay doubles (1s → 2s → 4s → ... → 60s max)
- **On success**: Delay halves (60s → 30s → 15s → ... → 0)
- **Rate-limited videos**: Stay in queue for automatic retry

### Migration from Previous Versions

If upgrading from a version that stored JSON files in the download root:
- Files are **automatically migrated** to the `json/` subfolder on first run
- No manual action required
- Video files remain in place (only metadata files move)

## Security Notes

- **Never share your `config.json`** - it contains session credentials
- Session cookies expire periodically - you may need to refresh them
- This tool only reads your data; it doesn't post or modify anything

## Disclaimer

This tool uses unofficial/internal TikTok APIs. Use responsibly and in accordance with TikTok's Terms of Service. This is for personal backup of your own saved content.
