#!/usr/bin/env python3
"""
Content Mate v2.2 — Main Entry Point
Replaces n8n entirely. Run any part of the pipeline from the command line.

Usage:
    python3 content_mate.py scrape-ig           # Scrape Instagram competitors from Airtable
    python3 content_mate.py analyze <video>     # Extract on-screen text from video (OCR)
    python3 content_mate.py create              # Create video from best idea
    python3 content_mate.py create <idea_id>    # Create video from specific idea
    python3 content_mate.py publish             # Publish all "Schedule" videos
    python3 content_mate.py auto                # Full pipeline: scrape-ig + create 5 + publish
    python3 content_mate.py status              # Show pipeline status
"""

import sys
import argparse
from datetime import datetime
from config import get_airtable_token, load_config
from airtable_utils import AirtableClient


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def show_status(config: dict):
    """Show current pipeline status from Airtable."""
    at = AirtableClient(config)

    statuses = ["Scripting", "Get X Video", "Voice", "Avatar",
                "Combine Videos", "Caption", "Review", "Schedule", "Published", "No"]

    log("=== Content Mate v2.2 — Pipeline Status ===")
    print()

    for status in statuses:
        records = at.search(config["table_create"], formula=f'{{Status}} = "{status}"')
        count = len(records)
        if count > 0:
            print(f"  {status:20s}: {count}")
            if status in ("Review", "Schedule") and count <= 5:
                for r in records:
                    name = r.get("fields", {}).get("Name", "?")
                    print(f"    → {name}")

    # Ideas status
    print()
    unscored = at.search(config["table_ideas"], formula="AND({Source Score}='', {Text}!='')", max_records=1)
    scored = at.search(config["table_ideas"], formula="{Source Score}>=5", max_records=100)
    total = at.search(config["table_ideas"], max_records=1000)
    print(f"  Ideas total:       {len(total)}")
    print(f"  Ideas scored 5+:   {len(scored)}")
    print()


def cmd_scrape_ig(config: dict):
    from ig_scraper import run_ig_scraper
    run_ig_scraper(config)


def cmd_analyze(config: dict, video_path: str):
    from video_ocr import extract_text_from_video, analyze_competitor_video, print_analysis
    if video_path.startswith("http"):
        result = analyze_competitor_video(video_path, config)
    else:
        result = extract_text_from_video(video_path)
    print_analysis(result)


def cmd_create(config: dict, idea_id: str = None):
    from creator import run_creator
    run_creator(config, idea_id)


def cmd_publish(config: dict):
    from publisher import run_publisher
    run_publisher(config)


def cmd_auto(config: dict, count: int = 5):
    """Full auto pipeline: scrape-ig → create N videos → publish scheduled."""
    log("=== Content Mate v2.2 — Full Auto Pipeline ===")

    # Step 1: Scrape Instagram
    log("--- Step 1: Scraping Instagram ---")
    from ig_scraper import run_ig_scraper
    run_ig_scraper(config)

    # Step 2: Create videos
    log(f"--- Step 2: Creating {count} videos ---")
    from creator import run_creator
    for i in range(count):
        log(f"--- Creating video {i+1}/{count} ---")
        result = run_creator(config)
        if not result:
            log(f"  No more ideas available. Created {i} videos.")
            break

    # Step 3: Publish scheduled
    log("--- Step 3: Publishing scheduled videos ---")
    from publisher import run_publisher
    run_publisher(config)

    log("=== Full Auto Pipeline Complete ===")


def main():
    parser = argparse.ArgumentParser(
        description="Content Mate v2.2 — AI Shorts Pipeline (no n8n required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  scrape-ig           Scrape Instagram Reels from competitors in Airtable
  analyze <video>     Extract on-screen text from video (local path or URL)
  create [idea_id]    Create video from best idea (or specific idea)
  publish             Publish all "Schedule" videos
  auto [--count N]    Full pipeline: scrape-ig + create N + publish (default: 5)
  status              Show pipeline status
        """
    )
    parser.add_argument("command", choices=["scrape-ig", "analyze", "create", "publish", "auto", "status"],
                       help="Pipeline command to run")
    parser.add_argument("target", nargs="?", default=None,
                       help="Target: idea_id (for create) or video path/URL (for analyze)")
    parser.add_argument("--count", type=int, default=5,
                       help="Number of videos to create in auto mode (default: 5)")

    args = parser.parse_args()

    # Load config
    token = get_airtable_token()
    config = load_config(token)

    if args.command == "scrape-ig":
        cmd_scrape_ig(config)
    elif args.command == "analyze":
        if not args.target:
            print("Error: analyze requires a video path or URL")
            print("Usage: python content_mate.py analyze <video_path_or_url>")
            sys.exit(1)
        cmd_analyze(config, args.target)
    elif args.command == "create":
        cmd_create(config, args.target)
    elif args.command == "publish":
        cmd_publish(config)
    elif args.command == "auto":
        cmd_auto(config, args.count)
    elif args.command == "status":
        show_status(config)


if __name__ == "__main__":
    main()
