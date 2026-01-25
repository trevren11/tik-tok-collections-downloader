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

# Sync interval in minutes (default: 30)
SYNC_INTERVAL=15
```

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

## Security Notes

- **Never share your `config.json`** - it contains session credentials
- Session cookies expire periodically - you may need to refresh them
- This tool only reads your data; it doesn't post or modify anything

## Disclaimer

This tool uses unofficial/internal TikTok APIs. Use responsibly and in accordance with TikTok's Terms of Service. This is for personal backup of your own saved content.
