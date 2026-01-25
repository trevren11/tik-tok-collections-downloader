#!/usr/bin/env python3
"""
TikTok Collections Fetcher

Fetches your TikTok collections/favorites using browser automation.
"""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    path = Path(config_path)

    if not path.exists():
        print(f"Error: Config file not found: {config_path}")
        print("Please copy config.example.json to config.json and add your cookies.")
        sys.exit(1)

    with open(path) as f:
        return json.load(f)


def get_collections_with_browser(sessionid: str) -> tuple[list, list]:
    """
    Use Playwright to fetch collections from TikTok.

    Args:
        sessionid: TikTok session ID cookie

    Returns:
        Tuple of (collections list, all API responses)
    """
    collections = []
    api_responses = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        context.add_cookies([
            {"name": "sessionid", "value": sessionid, "domain": ".tiktok.com", "path": "/"},
            {"name": "sessionid_ss", "value": sessionid, "domain": ".tiktok.com", "path": "/"},
        ])

        page = context.new_page()

        def handle_response(response):
            url = response.url
            # Only capture collection_list API responses
            if "collection_list" in url:
                try:
                    data = response.json()
                    api_responses.append({"url": url, "data": data})
                    # Extract collections from this response
                    if "collectionList" in data:
                        for coll in data["collectionList"]:
                            # Avoid duplicates
                            if not any(c.get("collectionId") == coll.get("collectionId") for c in collections):
                                collections.append(coll)
                except Exception:
                    pass

        page.on("response", handle_response)

        print("Navigating to TikTok...")
        page.goto("https://www.tiktok.com/", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # The collection_list API gets called automatically when logged in
        # Wait a bit more to ensure all requests complete
        page.wait_for_timeout(2000)

        browser.close()

    return collections, api_responses


def print_collections(collections: list):
    """Pretty print collections list."""
    if not collections:
        print("\nNo collections found.")
        return

    print(f"\n{'='*60}")
    print(f"Found {len(collections)} collection(s)")
    print(f"{'='*60}\n")

    # Sort by video count descending
    sorted_collections = sorted(collections, key=lambda x: int(x.get("total", 0)), reverse=True)

    for i, coll in enumerate(sorted_collections, 1):
        name = coll.get("name", "Unnamed")
        coll_id = coll.get("collectionId", "N/A")
        total = coll.get("total", "0")

        print(f"{i}. {name}")
        print(f"   ID: {coll_id}")
        print(f"   Videos: {total}")
        print()


def main():
    """Main entry point."""
    print("TikTok Collections Fetcher")
    print("-" * 40)

    config = load_config()

    # Environment variable overrides config (useful for Docker/Unraid)
    sessionid = os.environ.get("TIKTOK_SESSION_ID") or config.get("sessionid", "")

    if not sessionid:
        print("Error: No sessionid found in TIKTOK_SESSION_ID env var or config.json")
        sys.exit(1)

    try:
        print(f"\nUsing sessionid: {sessionid[:10]}...")
        collections, api_responses = get_collections_with_browser(sessionid)

        print_collections(collections)

        # Save collections to JSON
        output_path = Path("collections.json")
        with open(output_path, "w") as f:
            json.dump(collections, f, indent=2)
        print(f"Collections saved to: {output_path}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
