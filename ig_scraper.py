#!/usr/bin/env python3
"""
Content Mate v2.2 — Instagram Scraper Module
Scrapes competitor Instagram Reels using Apify.

Pulls top-performing Reels from competitor accounts,
stores them in Airtable for inspiration and analysis.
"""

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from airtable_utils import AirtableClient, api_request

APIFY_API = "https://api.apify.com/v2"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def run_apify_actor(config: dict, actor_id: str, input_data: dict) -> list:
    """Run an Apify actor and wait for results."""
    api_key = config.get("apify_api_key", "")
    if not api_key:
        raise ValueError("No Apify API key found in config")

    # Start the actor run
    url = f"{APIFY_API}/acts/{actor_id}/runs?token={api_key}"
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", url,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(input_data)],
        capture_output=True, text=True
    )
    run_data = json.loads(result.stdout)
    run_id = run_data.get("data", {}).get("id")

    if not run_id:
        log(f"  Failed to start Apify actor: {result.stdout[:200]}")
        return []

    log(f"  Apify run started: {run_id}")

    # Poll for completion (max 5 minutes)
    for _ in range(60):
        time.sleep(5)
        status_url = f"{APIFY_API}/actor-runs/{run_id}?token={api_key}"
        status_result = subprocess.run(
            ["curl", "-s", status_url],
            capture_output=True, text=True
        )
        status_data = json.loads(status_result.stdout)
        state = status_data.get("data", {}).get("status")

        if state == "SUCCEEDED":
            log(f"  Apify run completed!")
            break
        elif state in ("FAILED", "ABORTED", "TIMED-OUT"):
            log(f"  Apify run failed: {state}")
            return []

        log(f"  Apify status: {state}...")
    else:
        log("  Apify run timed out")
        return []

    # Get results from dataset
    dataset_id = status_data.get("data", {}).get("defaultDatasetId")
    if not dataset_id:
        return []

    dataset_url = f"{APIFY_API}/datasets/{dataset_id}/items?token={api_key}"
    dataset_result = subprocess.run(
        ["curl", "-s", dataset_url],
        capture_output=True, text=True
    )
    return json.loads(dataset_result.stdout)


def scrape_ig_profile(config: dict, username: str, max_reels: int = 20) -> list:
    """Scrape Instagram Reels from a profile using Apify."""
    # Using apify/instagram-reel-scraper actor
    actor_id = "apify~instagram-reel-scraper"

    input_data = {
        "usernames": [username],
        "resultsLimit": max_reels,
        "sortBy": "recent"
    }

    log(f"  Scraping @{username} for Reels...")
    return run_apify_actor(config, actor_id, input_data)


def get_existing_ig_links(at: AirtableClient, table_id: str) -> set:
    """Get all existing Instagram links to avoid duplicates."""
    records = at.search_all(table_id)
    links = set()
    for r in records:
        link = r.get("fields", {}).get("Link", "")
        if link:
            links.add(link.strip().lower())
    return links


def create_ig_idea_record(at: AirtableClient, table_id: str, reel: dict) -> dict:
    """Create an Idea record from an Instagram Reel."""
    fields = {
        "Name": reel.get("ownerUsername", "unknown"),
        "Link": reel.get("url", ""),
        "Date": reel.get("timestamp", ""),
        "Text": reel.get("caption", ""),
        "Views": reel.get("playCount", 0),
        "Likes": reel.get("likesCount", 0),
        "Comments": reel.get("commentsCount", 0),
        "Source": "Instagram",
        "Video URL": reel.get("videoUrl", ""),
        "Thumbnail": reel.get("displayUrl", ""),
        "Video (sec)": reel.get("videoDuration", 0),
    }
    return at.create_record(table_id, fields)


def download_reel(reel: dict, output_path: str) -> str:
    """Download a Reel video."""
    video_url = reel.get("videoUrl", "")
    if not video_url:
        raise ValueError("No video URL in reel data")

    subprocess.run(["curl", "-s", "-L", "-o", output_path, video_url], check=True)
    log(f"  Downloaded: {output_path}")
    return output_path


def run_ig_scraper(config: dict, max_per_account: int = 10):
    """Main IG scraper function. Scrapes all competitor accounts from Setup table."""
    at = AirtableClient(config)
    table_ideas = config["table_ideas"]

    # Read comma-separated usernames from Setup table field "IG Competitors"
    competitors_str = config.get("ig_competitors", "")

    if not competitors_str:
        log("ERROR: No IG competitors configured.")
        log("Add 'IG Competitors' field to Setup table with comma-separated usernames.")
        log("Example: garyvee, hormozi, therock")
        return 0

    # Parse comma-separated list
    usernames = [u.strip().lstrip("@") for u in competitors_str.split(",") if u.strip()]

    log("=== IG Scraper: Starting ===")
    log(f"Found {len(usernames)} Instagram competitors to scrape")

    if not usernames:
        log("No competitors found. Add usernames to 'IG Competitors' field in Setup.")
        return 0

    # Get existing links to avoid duplicates
    existing = get_existing_ig_links(at, table_ideas)
    log(f"Found {len(existing)} existing IG ideas")

    created = 0
    for username in usernames:
        try:
            reels = scrape_ig_profile(config, username, max_per_account)
            log(f"  @{username}: found {len(reels)} Reels")

            for reel in reels:
                url = reel.get("url", "").strip().lower()
                if not url or url in existing:
                    continue

                try:
                    create_ig_idea_record(at, table_ideas, reel)
                    existing.add(url)
                    created += 1
                except Exception as e:
                    log(f"  Failed to create IG idea: {e}")

                time.sleep(0.2)  # Rate limit

        except Exception as e:
            log(f"  @{username}: scrape failed: {e}")

    log(f"=== IG Scraper: Done. Created {created} new IG ideas ===")
    return created


def parse_username(input_str: str) -> str:
    """Extract username from various input formats."""
    # Remove @ prefix
    username = input_str.lstrip("@")

    # Extract from URL: instagram.com/username or instagram.com/username/
    if "instagram.com" in username:
        parts = username.split("instagram.com/")[-1].split("/")[0].split("?")[0]
        username = parts

    return username.strip()


def scrape_single_creator(config: dict, username_input: str, max_reels: int = 10):
    """Scrape Reels from a single Instagram creator."""
    username = parse_username(username_input)

    log(f"=== IG Scraper: Scraping @{username} ===")

    reels = scrape_ig_profile(config, username, max_reels)

    if not reels:
        log("No Reels found.")
        return []

    log(f"\nFound {len(reels)} Reels from @{username}:\n")

    for i, reel in enumerate(reels, 1):
        views = reel.get("playCount", 0)
        likes = reel.get("likesCount", 0)
        caption = reel.get("caption", "")[:80]
        url = reel.get("url", "")

        print(f"{i}. {views:,} views | {likes:,} likes")
        print(f"   {caption}...")
        print(f"   {url}\n")

    # Download and analyze top video
    if reels:
        top_reel = max(reels, key=lambda r: r.get("playCount", 0))
        log(f"\nTop performing Reel: {top_reel.get('playCount', 0):,} views")
        log(f"URL: {top_reel.get('url', '')}")

    return reels


if __name__ == "__main__":
    import sys
    from config import get_airtable_token, load_config

    token = get_airtable_token()
    cfg = load_config(token)

    if len(sys.argv) > 1:
        # Scrape specific user
        scrape_single_creator(cfg, sys.argv[1])
    else:
        # Scrape all competitors
        run_ig_scraper(cfg)
