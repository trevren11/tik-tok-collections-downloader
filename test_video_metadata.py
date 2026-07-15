#!/usr/bin/env python3
"""
Test script to explore TikTok video metadata and find full captions/descriptions.

Usage:
    python test_video_metadata.py <video_url_or_id>
    python test_video_metadata.py 7160063596070833451
    python test_video_metadata.py https://www.tiktok.com/@britscookin/video/7160063596070833451
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
    # If it's just digits, it's already an ID
    if url_or_id.isdigit():
        return url_or_id

    # Try to extract from URL
    match = re.search(r'/video/(\d+)', url_or_id)
    if match:
        return match.group(1)

    # Try another pattern
    match = re.search(r'(\d{19})', url_or_id)
    if match:
        return match.group(1)

    return url_or_id


def fetch_subtitles(subtitle_url: str) -> tuple[str, str]:
    """Fetch WebVTT subtitles and return (raw_vtt, clean_text)."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.tiktok.com/'
    }
    try:
        resp = requests.get(subtitle_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return "", ""

        raw_vtt = resp.text

        # Parse WebVTT to extract just the text
        lines = raw_vtt.split('\n')
        text_lines = []
        for line in lines:
            line = line.strip()
            # Skip WEBVTT header, timestamps, and empty lines
            if not line or line == 'WEBVTT' or '-->' in line:
                continue
            # Skip numeric cue identifiers
            if line.isdigit():
                continue
            text_lines.append(line)

        clean_text = ' '.join(text_lines)
        return raw_vtt, clean_text
    except Exception as e:
        print(f"  Error fetching subtitles: {e}")
        return "", ""


def _extract_video_info(video_info: dict, results: dict, source_prefix: str):
    """Extract text content from a video info dict."""
    desc = video_info.get("desc", "")
    if desc:
        print(f"  desc: {desc[:100]}..." if len(desc) > 100 else f"  desc: {desc}")
        results["combined_text"].append({"source": f"{source_prefix}_desc", "text": desc})

    # Check for contents array (sub-captions, recipe steps, etc.)
    contents = video_info.get("contents", [])
    if contents:
        print(f"  Found {len(contents)} content item(s)")
        for i, content in enumerate(contents):
            text = content.get("desc", content.get("text", ""))
            if text:
                print(f"    content[{i}]: {text[:100]}..." if len(text) > 100 else f"    content[{i}]: {text}")
                results["combined_text"].append({"source": f"{source_prefix}_contents[{i}]", "text": text})

    # Check for imagePost data (for photo carousels with text)
    image_post = video_info.get("imagePost", {})
    if image_post:
        images = image_post.get("images", [])
        print(f"  Found imagePost with {len(images)} images")
        for i, img in enumerate(images):
            title = img.get("title", "")
            if title:
                print(f"    image[{i}] title: {title[:100]}..." if len(title) > 100 else f"    image[{i}] title: {title}")
                results["combined_text"].append({"source": f"{source_prefix}_image[{i}]", "text": title})

    # Check for stickers (text overlays)
    stickers = video_info.get("stickersOnItem", [])
    if stickers:
        print(f"  Found {len(stickers)} sticker(s)")
        for i, sticker in enumerate(stickers):
            sticker_text = sticker.get("stickerText", [])
            if sticker_text:
                joined = " ".join(sticker_text) if isinstance(sticker_text, list) else str(sticker_text)
                print(f"    sticker[{i}]: {joined[:100]}..." if len(joined) > 100 else f"    sticker[{i}]: {joined}")
                results["combined_text"].append({"source": f"{source_prefix}_sticker[{i}]", "text": joined})

    # Check for suggestedWords
    suggested = video_info.get("suggestedWords", [])
    if suggested:
        print(f"  Suggested words: {suggested}")
        results["combined_text"].append({"source": f"{source_prefix}_suggested", "text": " ".join(suggested)})

    # Check for subtitles/captions (auto-generated speech-to-text)
    video = video_info.get("video", {})
    subtitle_infos = video.get("subtitleInfos", [])
    if subtitle_infos and source_prefix == "universal":  # Only fetch once
        print(f"  Found {len(subtitle_infos)} subtitle track(s)")
        for i, sub in enumerate(subtitle_infos):
            url = sub.get("Url", "")
            lang = sub.get("LanguageCodeName", "unknown")
            source = sub.get("Source", "unknown")
            print(f"    subtitle[{i}]: {lang} ({source})")

            if url:
                raw_vtt, clean_text = fetch_subtitles(url)
                if clean_text:
                    print(f"    Fetched {len(clean_text)} chars of subtitle text")
                    results["combined_text"].append({
                        "source": f"{source_prefix}_subtitles_{lang}",
                        "text": clean_text
                    })
                    results["subtitles_raw"] = raw_vtt


def fetch_video_metadata(sessionid: str, video_id: str, author: str = None) -> dict:
    """
    Fetch detailed video metadata using various TikTok APIs.

    Returns dict with all found metadata from different sources.
    """
    results = {
        "video_id": video_id,
        "sources": {},
        "combined_text": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Denver",
        )

        context.add_cookies([
            {"name": "sessionid", "value": sessionid, "domain": ".tiktok.com", "path": "/"},
            {"name": "sessionid_ss", "value": sessionid, "domain": ".tiktok.com", "path": "/"},
        ])

        page = context.new_page()

        # First, navigate to TikTok to establish session
        print("Establishing session...")
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # Method 1: Try the customtdk API for AI summary (fastest method)
        print("\n[Method 1] Trying /api/customtdk/item/ for AI summary...")
        try:
            customtdk_response = page.evaluate("""
                async (videoId) => {
                    const url = new URL('https://www.tiktok.com/api/customtdk/item/');
                    url.searchParams.set('itemId', videoId);
                    url.searchParams.set('aid', '1988');

                    try {
                        const response = await fetch(url.toString(), {
                            method: 'GET',
                            credentials: 'include',
                            headers: { 'Accept': 'application/json' }
                        });
                        return await response.json();
                    } catch (e) {
                        return { error: e.toString() };
                    }
                }
            """, video_id)

            if customtdk_response and 'error' not in customtdk_response:
                results["sources"]["customtdk"] = customtdk_response
                tdk = customtdk_response.get("itemCustomTDK", {})

                if tdk:
                    print("  Found customTDK data")
                    # AI-generated article/summary
                    article = tdk.get("article", "")
                    if article:
                        print(f"  article: {article[:100]}...")
                        results["combined_text"].append({
                            "source": "customtdk_article",
                            "text": article
                        })
                    # AI-generated title
                    title = tdk.get("title", "")
                    if title:
                        print(f"  title: {title}")
                        results["combined_text"].append({
                            "source": "customtdk_title",
                            "text": title
                        })
                    # AI-generated description
                    desc = tdk.get("desc", "")
                    if desc:
                        print(f"  desc: {desc[:100]}...")
                        results["combined_text"].append({
                            "source": "customtdk_desc",
                            "text": desc
                        })
                    # Keywords
                    keywords = tdk.get("keywords", "")
                    if keywords:
                        print(f"  keywords: {keywords[:100]}...")
            else:
                print(f"  Error: {customtdk_response.get('error', 'Unknown') if customtdk_response else 'No response'}")

        except Exception as e:
            print(f"  Exception: {e}")

        # Method 2: Try the video detail API directly
        print("\n[Method 2] Trying /api/item/detail/ API...")
        try:
            detail_response = page.evaluate("""
                async (videoId) => {
                    const url = new URL('https://www.tiktok.com/api/item/detail/');
                    url.searchParams.set('itemId', videoId);
                    url.searchParams.set('aid', '1988');

                    try {
                        const response = await fetch(url.toString(), {
                            method: 'GET',
                            credentials: 'include',
                            headers: { 'Accept': 'application/json' }
                        });
                        return await response.json();
                    } catch (e) {
                        return { error: e.toString() };
                    }
                }
            """, video_id)

            if detail_response and 'error' not in detail_response:
                results["sources"]["api_item_detail"] = detail_response

                # Extract useful fields
                item_info = detail_response.get("itemInfo", {}).get("itemStruct", {})
                if item_info:
                    print("  Found video in API response")
                    _extract_video_info(item_info, results, "api")
            else:
                print(f"  Error: {detail_response.get('error', 'Unknown') if detail_response else 'No response'}")

        except Exception as e:
            print(f"  Exception: {e}")

        # Method 3: Try navigating to the video page and extracting data
        print("\n[Method 3] Navigating to video page...")
        video_url = f"https://www.tiktok.com/@{author}/video/{video_id}" if author else f"https://www.tiktok.com/@placeholder/video/{video_id}"
        print(f"  URL: {video_url}")

        try:
            page.goto(video_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)  # Wait longer for JS to populate

            # Extract data from page's JavaScript state
            page_data = page.evaluate("""
                () => {
                    const result = {
                        found_keys: []
                    };

                    // Try SIGI_STATE
                    if (window.SIGI_STATE) {
                        result.sigi_state = window.SIGI_STATE;
                        result.found_keys.push('SIGI_STATE');
                    }

                    // Try __NEXT_DATA__
                    if (window.__NEXT_DATA__) {
                        result.next_data = window.__NEXT_DATA__;
                        result.found_keys.push('__NEXT_DATA__');
                    }

                    // Try __DEFAULT_SCOPE__
                    if (window.__DEFAULT_SCOPE__) {
                        result.default_scope = window.__DEFAULT_SCOPE__;
                        result.found_keys.push('__DEFAULT_SCOPE__');
                    }

                    // Try to find script tags with video data
                    const scripts = document.querySelectorAll('script[id="__UNIVERSAL_DATA_FOR_REHYDRATION__"]');
                    if (scripts.length > 0) {
                        try {
                            result.universal_data = JSON.parse(scripts[0].textContent);
                            result.found_keys.push('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                        } catch (e) {
                            result.universal_parse_error = e.toString();
                        }
                    }

                    // Also check for SIGI_STATE in script tags
                    const allScripts = document.querySelectorAll('script');
                    for (const script of allScripts) {
                        const text = script.textContent || '';
                        if (text.includes('SIGI_STATE') && text.includes('"ItemModule"')) {
                            const match = text.match(/window\['SIGI_STATE'\]=(.+);/);
                            if (match) {
                                try {
                                    result.sigi_state_parsed = JSON.parse(match[1]);
                                    result.found_keys.push('SIGI_STATE_PARSED');
                                } catch (e) {}
                            }
                        }
                    }

                    // List all window keys that might contain data
                    result.window_keys = Object.keys(window).filter(k =>
                        k.includes('DATA') || k.includes('STATE') || k.includes('SCOPE') ||
                        k.includes('UNIVERSAL') || k.includes('HYDRAT')
                    );

                    return result;
                }
            """)

            print(f"  Found data keys: {page_data.get('found_keys', [])}")
            print(f"  Relevant window keys: {page_data.get('window_keys', [])}")

            results["sources"]["page_data"] = page_data

            # Try to extract video info from SIGI_STATE
            sigi = page_data.get("sigi_state") or page_data.get("sigi_state_parsed")
            if sigi:
                item_module = sigi.get("ItemModule", {})
                if video_id in item_module:
                    video_info = item_module[video_id]
                    print("  Found video in SIGI_STATE.ItemModule")
                    _extract_video_info(video_info, results, "sigi")

            # Try __DEFAULT_SCOPE__
            default_scope = page_data.get("default_scope", {})
            video_detail = default_scope.get("webapp.video-detail", {})
            if video_detail:
                item_info = video_detail.get("itemInfo", {}).get("itemStruct", {})
                if item_info:
                    print("  Found video in __DEFAULT_SCOPE__")
                    _extract_video_info(item_info, results, "default_scope")

            # Try __UNIVERSAL_DATA_FOR_REHYDRATION__
            universal = page_data.get("universal_data", {})
            if universal:
                # Navigate the structure to find video data
                default_scope_uni = universal.get("__DEFAULT_SCOPE__", {})
                video_detail_uni = default_scope_uni.get("webapp.video-detail", {})
                if video_detail_uni:
                    item_info = video_detail_uni.get("itemInfo", {}).get("itemStruct", {})
                    if item_info:
                        print("  Found video in __UNIVERSAL_DATA_FOR_REHYDRATION__")
                        _extract_video_info(item_info, results, "universal")

        except Exception as e:
            print(f"  Exception: {e}")

        # Method 4: Try to expand description and look for info cards
        print("\n[Method 4] Looking for expandable content / info cards...")
        try:
            # Look for "See more", "Read more", expand buttons, or info card elements
            expand_selectors = [
                '[data-e2e="video-desc"] button',
                '[data-e2e="browse-video-desc"] button',
                'button:has-text("more")',
                'span:has-text("more")',
                '[class*="InfoCard"]',
                '[class*="info-card"]',
                '[class*="expand"]',
                '[class*="recipe"]',
                '[class*="summary"]',
            ]

            for selector in expand_selectors:
                try:
                    count = page.locator(selector).count()
                    if count > 0:
                        print(f"    Found {count} element(s) matching: {selector}")
                        # Try to click it
                        page.locator(selector).first.click()
                        page.wait_for_timeout(2000)
                except Exception:
                    pass

            # Now look for any expanded content or info card text
            info_card_data = page.evaluate("""
                () => {
                    const results = [];

                    // Look for elements that might contain expanded description
                    const selectors = [
                        '[data-e2e="video-desc"]',
                        '[data-e2e="browse-video-desc"]',
                        '[class*="DivVideoInfoContainer"]',
                        '[class*="InfoCard"]',
                        '[class*="info-card"]',
                        '[class*="description"]',
                        '[class*="caption"]',
                    ];

                    for (const sel of selectors) {
                        const elements = document.querySelectorAll(sel);
                        for (const el of elements) {
                            const text = el.innerText?.trim();
                            if (text && text.length > 100) {
                                results.push({
                                    selector: sel,
                                    text: text,
                                    className: el.className
                                });
                            }
                        }
                    }

                    // Also check for any large text blocks that might be AI summaries
                    const allDivs = document.querySelectorAll('div');
                    for (const div of allDivs) {
                        const text = div.innerText?.trim();
                        // Look for AI-generated content (starts with title like "Delicious...")
                        if (text && text.includes('Craving a comforting')) {
                            results.push({
                                selector: 'div (AI summary)',
                                text: text,  // Get full text
                                className: div.className
                            });
                        }
                    }

                    return results;
                }
            """)

            if info_card_data:
                print(f"  Found {len(info_card_data)} content block(s)")
                for item in info_card_data:
                    print(f"    {item['selector']}: {item['text'][:100]}...")
                    if len(item['text']) > 200:
                        results["combined_text"].append({
                            "source": "info_card",
                            "text": item['text']
                        })
                results["sources"]["info_card"] = info_card_data
            else:
                print("  No expanded content found")

        except Exception as e:
            print(f"  Exception: {e}")

        # Method 5: Check for schema.org structured data (ld+json)
        print("\n[Method 5] Checking for schema.org structured data...")
        try:
            structured_data = page.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    const data = [];
                    for (const script of scripts) {
                        try {
                            data.push(JSON.parse(script.textContent));
                        } catch (e) {}
                    }
                    return data;
                }
            """)

            if structured_data:
                results["sources"]["structured_data"] = structured_data
                print(f"  Found {len(structured_data)} ld+json block(s)")
                for i, block in enumerate(structured_data):
                    block_type = block.get("@type", "unknown")
                    print(f"    Block {i}: @type={block_type}")

                    # Look for description or articleBody in schema
                    for field in ["description", "articleBody", "text", "recipe", "recipeInstructions"]:
                        if field in block:
                            text = block[field]
                            if isinstance(text, str) and len(text) > 50:
                                print(f"    {field}: {text[:100]}...")
                                results["combined_text"].append({
                                    "source": f"schema_{field}",
                                    "text": text
                                })
            else:
                print("  No ld+json structured data found")

        except Exception as e:
            print(f"  Exception: {e}")

        # Method 6: Try the /oembed endpoint (public, no auth needed)
        print("\n[Method 6] Trying /oembed endpoint...")
        try:
            oembed_url = f"https://www.tiktok.com/oembed?url={video_url}"
            oembed_response = page.evaluate("""
                async (url) => {
                    try {
                        const response = await fetch(url);
                        return await response.json();
                    } catch (e) {
                        return { error: e.toString() };
                    }
                }
            """, oembed_url)

            if oembed_response and 'error' not in oembed_response:
                results["sources"]["oembed"] = oembed_response
                title = oembed_response.get("title", "")
                author_name = oembed_response.get("author_name", "")
                print(f"  title: {title[:100]}..." if len(title) > 100 else f"  title: {title}")
                print(f"  author: {author_name}")
            else:
                print(f"  Error: {oembed_response.get('error', 'Unknown')}")

        except Exception as e:
            print(f"  Exception: {e}")

        browser.close()

    return results


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    video_input = sys.argv[1]
    video_id = extract_video_id(video_input)

    # Check if author was provided in URL
    author = None
    if "@" in video_input:
        match = re.search(r'@([^/]+)', video_input)
        if match:
            author = match.group(1)

    print(f"Video ID: {video_id}")
    if author:
        print(f"Author: @{author}")
    print("-" * 60)

    config = load_config()
    sessionid = config.get("sessionid", "")

    if not sessionid:
        print("Error: No sessionid found in config.json")
        sys.exit(1)

    results = fetch_video_metadata(sessionid, video_id, author)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if results["combined_text"]:
        print("\nAll text content found:")
        for item in results["combined_text"]:
            print(f"\n--- {item['source']} ---")
            print(item["text"])
    else:
        print("\nNo additional text content found beyond the basic description.")

    # Save full results to JSON for inspection
    output_file = f"video_metadata_{video_id}.json"
    with open(output_file, "w") as f:
        # Build output with all relevant data
        output = {
            "video_id": results["video_id"],
            "combined_text": results["combined_text"],
            "sources_keys": list(results["sources"].keys()),
        }

        # Extract item_info from various sources
        for source_name in ["api_item_detail", "page_data"]:
            if source_name not in results["sources"]:
                continue

            source = results["sources"][source_name]

            # Try different paths to find item info
            item_info = None
            if source_name == "api_item_detail":
                item_info = source.get("itemInfo", {}).get("itemStruct", {})
            elif source_name == "page_data":
                # From SIGI_STATE
                sigi = source.get("sigi_state") or source.get("sigi_state_parsed")
                if sigi and video_id in sigi.get("ItemModule", {}):
                    item_info = sigi["ItemModule"][video_id]
                # From __DEFAULT_SCOPE__
                if not item_info:
                    ds = source.get("default_scope", {}).get("webapp.video-detail", {})
                    item_info = ds.get("itemInfo", {}).get("itemStruct", {})
                # From __UNIVERSAL_DATA_FOR_REHYDRATION__
                if not item_info:
                    uni = source.get("universal_data", {}).get("__DEFAULT_SCOPE__", {})
                    uni_vd = uni.get("webapp.video-detail", {})
                    item_info = uni_vd.get("itemInfo", {}).get("itemStruct", {})

            if item_info:
                output[f"{source_name}_item_info"] = {
                    "desc": item_info.get("desc"),
                    "contents": item_info.get("contents"),
                    "stickersOnItem": item_info.get("stickersOnItem"),
                    "textExtra": item_info.get("textExtra"),
                    "challenges": item_info.get("challenges"),
                    "imagePost": item_info.get("imagePost"),
                    "suggestedWords": item_info.get("suggestedWords"),
                }

        # Include page_data debug info
        if "page_data" in results["sources"]:
            pd = results["sources"]["page_data"]
            output["page_data_debug"] = {
                "found_keys": pd.get("found_keys", []),
                "window_keys": pd.get("window_keys", []),
            }

        json.dump(output, f, indent=2)

    print(f"\nFull results saved to: {output_file}")

    # Also save the raw page_data for deep debugging if needed
    raw_file = f"video_metadata_{video_id}_raw.json"
    with open(raw_file, "w") as f:
        json.dump(results["sources"], f, indent=2, default=str)
    print(f"Raw data saved to: {raw_file}")


if __name__ == "__main__":
    main()
