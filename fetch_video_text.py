#!/usr/bin/env python3
"""
Fast TikTok video text fetcher - uses only API calls, no page rendering.

Usage:
    python fetch_video_text.py <video_id>
    python fetch_video_text.py 7160063596070833451
"""

import json
import re
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from URL or return as-is if already an ID."""
    if url_or_id.isdigit():
        return url_or_id
    match = re.search(r'/video/(\d+)', url_or_id)
    if match:
        return match.group(1)
    match = re.search(r'(\d{19})', url_or_id)
    if match:
        return match.group(1)
    return url_or_id


def fetch_subtitles(subtitle_url: str) -> str:
    """Fetch WebVTT subtitles and return clean text."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.tiktok.com/'
    }
    try:
        resp = requests.get(subtitle_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return ""

        lines = resp.text.split('\n')
        text_lines = []
        for line in lines:
            line = line.strip()
            if not line or line == 'WEBVTT' or '-->' in line or line.isdigit():
                continue
            text_lines.append(line)
        return ' '.join(text_lines)
    except Exception:
        return ""


def fetch_video_text(sessionid: str, video_id: str) -> dict:
    """
    Fast fetch of video text using only API calls.

    Returns dict with:
        - ai_title: AI-generated title
        - ai_article: AI-generated summary/recipe
        - ai_desc: AI-generated SEO description
        - original_desc: Original creator description
        - subtitles: Speech-to-text transcript
        - stickers: Text overlays on video
    """
    result = {
        "video_id": video_id,
        "ai_title": "",
        "ai_article": "",
        "ai_desc": "",
        "ai_keywords": [],
        "original_desc": "",
        "subtitles": "",
        "stickers": [],
        "suggested_words": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        context.add_cookies([
            {"name": "sessionid", "value": sessionid, "domain": ".tiktok.com", "path": "/"},
        ])

        page = context.new_page()

        # Establish session
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # API 1: /api/customtdk/item/ - AI summary (fast)
        customtdk = page.evaluate("""
            async (videoId) => {
                const url = new URL('https://www.tiktok.com/api/customtdk/item/');
                url.searchParams.set('itemId', videoId);
                url.searchParams.set('aid', '1988');
                try {
                    const resp = await fetch(url.toString(), { credentials: 'include' });
                    return await resp.json();
                } catch (e) {
                    return { error: e.toString() };
                }
            }
        """, video_id)

        if customtdk and "itemCustomTDK" in customtdk:
            tdk = customtdk["itemCustomTDK"]
            result["ai_title"] = tdk.get("title", "")
            result["ai_article"] = tdk.get("article", "")
            result["ai_desc"] = tdk.get("desc", "")
            result["ai_keywords"] = tdk.get("keywords", [])

        # API 2: /api/item/detail/ - Original desc + subtitle URLs
        detail = page.evaluate("""
            async (videoId) => {
                const url = new URL('https://www.tiktok.com/api/item/detail/');
                url.searchParams.set('itemId', videoId);
                url.searchParams.set('aid', '1988');
                try {
                    const resp = await fetch(url.toString(), { credentials: 'include' });
                    return await resp.json();
                } catch (e) {
                    return { error: e.toString() };
                }
            }
        """, video_id)

        if detail and "itemInfo" in detail:
            item = detail["itemInfo"].get("itemStruct", {})
            result["original_desc"] = item.get("desc", "")
            result["suggested_words"] = item.get("suggestedWords", [])

            # Stickers
            for sticker in item.get("stickersOnItem", []):
                text = sticker.get("stickerText", [])
                if text:
                    result["stickers"].append(" ".join(text) if isinstance(text, list) else str(text))

            # Subtitles
            video = item.get("video", {})
            subtitle_infos = video.get("subtitleInfos", [])
            if subtitle_infos:
                url = subtitle_infos[0].get("Url", "")
                if url:
                    result["subtitles"] = fetch_subtitles(url)

        browser.close()

    return result


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    video_input = sys.argv[1]
    video_id = extract_video_id(video_input)
    print(f"Fetching text for video: {video_id}")

    config = load_config()
    sessionid = config.get("sessionid", "")
    if not sessionid:
        print("Error: No sessionid in config.json")
        sys.exit(1)

    result = fetch_video_text(sessionid, video_id)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    if result["ai_title"]:
        print(f"\n[AI Title]\n{result['ai_title']}")

    if result["ai_article"]:
        print(f"\n[AI Article/Summary]\n{result['ai_article']}")

    if result["original_desc"]:
        print(f"\n[Original Description]\n{result['original_desc']}")

    if result["subtitles"]:
        print(f"\n[Subtitles (speech-to-text)]\n{result['subtitles']}")

    if result["stickers"]:
        print(f"\n[Stickers]\n{', '.join(result['stickers'])}")

    # Save to JSON
    output_file = f"video_text_{video_id}.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved to: {output_file}")


if __name__ == "__main__":
    main()
