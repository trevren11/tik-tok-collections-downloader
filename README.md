# TikTok Collections Downloader

Download and organize your TikTok saved videos by collection, including full metadata and captions.

## Overview

This tool uses your TikTok session cookies to access your personal collections (saved/favorited videos) and download them with their metadata. TikTok's official API doesn't expose collections, so we use authenticated session cookies from your browser.

## Features

- [x] List all your TikTok collections
- [ ] Download videos from collections
- [ ] Save metadata (captions, author info, stats)
- [ ] Organize into folders by collection name

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
4. Find and copy these cookie values:
   - `sessionid`
   - `sessionid_ss`
   - `sid_tt`
   - `sid_guard`
   - `tt_chain_token`
   - `tt_csrf_token`
   - `msToken`

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
