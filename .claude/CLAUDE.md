# TikTok Collections Downloader

## Project Overview
A tool to download and organize TikTok saved videos by collection, including metadata and captions.

## Tech Stack
- Python 3.11
- playwright (browser automation)
- yt-dlp (video downloading)
- requests (API calls)
- Docker for containerization

## Development

### Running Tests
```bash
python -m unittest discover -s tests -v
```

### Building Docker Image
```bash
docker build -t tiktok-collections .
```

## Important Guidelines

### Keep README.md Updated
When making changes that affect:
- Setup instructions
- Configuration options
- CLI commands or options
- Docker usage
- Any user-facing behavior

**Always update README.md to reflect those changes.**

### Configuration
- Only `sessionid` cookie is required (not multiple cookies)
- Config file: `config.json` (see `config.example.json`)
- Environment variables can override config in Docker

### File Structure
- `tiktok_monitor.py` - Main monitoring/download script
- `tiktok_collections.py` - Collections API client
- `viewer.html` - Web viewer interface
- `tests/` - Unit tests
