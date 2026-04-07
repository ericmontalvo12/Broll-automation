#!/usr/bin/env python3
"""
Content Mate v2.2 — Scraper Module
Replaces: n8n Schedule scraping → TwitterAPI.io Search → Airtable Ideas

Scrapes tweets with videos from X handles stored in the X table,
deduplicates against existing Ideas, and creates new Idea records.
"""

import json
import subprocess
import time
from datetime import datetime, timedelta
from airtable_utils import AirtableClient, api_get, curl_get

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def scrape_handle(twitter_api_key: str, handle: str, since_days: int = 4) -> list:
    """Search TwitterAPI.io for recent tweets with videos from a handle."""
    from urllib.parse import quote
    since = (datetime.utcnow() - timedelta(days=since_days)).strftime("%Y-%m-%d_%H:%M:%S") + "_UTC"
    query = f"from:{handle} filter:videos lang:en since:{since}"
    url = (
        f"https://api.twitterapi.io/twitter/tweet/advanced_search"
        f"?queryType=Latest&query={quote(query)}"
    )
    try:
        result = subprocess.run(
            ["curl", "-s", url, "-H", f"X-API-Key: {twitter_api_key}"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        tweets = data.get("tweets", [])
        log(f"  @{handle}: {len(tweets)} tweets with videos")
        return tweets
    except Exception as e:
        log(f"  @{handle}: search failed: {e}")
        return []


def get_existing_links(at: AirtableClient, table_ideas: str) -> set:
    """Get all existing tweet links in Ideas to avoid duplicates."""
    records = at.search_all(table_ideas)
    links = set()
    for r in records:
        link = r.get("fields", {}).get("Link", "")
        if link:
            links.add(link.strip().lower())
    return links


def create_idea_record(at: AirtableClient, table_ideas: str, tweet: dict, is_retweet: bool = False, retweet_data: dict = None) -> dict:
    """Create an Idea record from a tweet."""
    author = tweet.get("author", {})
    media = tweet.get("extendedEntities", {}).get("media", [{}])[0]
    video_info = media.get("video_info", {})
    aspect_ratio = video_info.get("aspect_ratio", [0, 0])
    duration_ms = video_info.get("duration_millis", 0)

    fields = {
        "Name": author.get("userName", "unknown"),
        "Link": tweet.get("url", ""),
        "Date": tweet.get("createdAt", ""),
        "Text": tweet.get("text", ""),
        "Views": tweet.get("viewCount", 0),
        "Retweets": tweet.get("retweetCount", 0),
        "IsRetweet": str(is_retweet),
        "Ratio": f"[{aspect_ratio[0]},{aspect_ratio[1]}]" if len(aspect_ratio) >= 2 else "",
        "Video (sec)": duration_ms / 1000 if duration_ms else 0,
    }

    if is_retweet and retweet_data:
        fields["Retweet Handle"] = retweet_data.get("author", {}).get("userName", "")
        fields["Retweet Link"] = retweet_data.get("url", "")
        fields["Retweet Text"] = retweet_data.get("text", "")
        fields["Retweet Views"] = retweet_data.get("viewCount", 0)

    return at.create_record(table_ideas, fields)


def delete_duplicates(at: AirtableClient, table_ideas: str):
    """Find and delete duplicate Ideas based on Link field."""
    records = at.search_all(table_ideas)
    seen = {}
    to_delete = []

    for r in records:
        link = r.get("fields", {}).get("Link", "").strip().lower()
        if not link:
            continue
        if link in seen:
            to_delete.append(r["id"])
        else:
            seen[link] = r["id"]

    for rid in to_delete:
        try:
            at.delete_record(table_ideas, rid)
        except Exception:
            pass

    if to_delete:
        log(f"Deleted {len(to_delete)} duplicate Ideas")


def run_scraper(config: dict):
    """Main scraper function. Scrapes all X handles and creates Ideas."""
    at = AirtableClient(config)
    twitter_key = config["twitter_api_key"]
    table_x = config["table_x"]
    table_ideas = config["table_ideas"]

    log("=== Scraper: Starting ===")

    # Get all X handles
    handles = at.search_all(table_x)
    log(f"Found {len(handles)} X handles to scrape")

    # Get existing links to avoid duplicates
    existing = get_existing_links(at, table_ideas)
    log(f"Found {len(existing)} existing Ideas")

    created = 0
    for handle_rec in handles:
        handle = handle_rec.get("fields", {}).get("Handle", "")
        if not handle:
            continue

        tweets = scrape_handle(twitter_key, handle)

        for tweet in tweets:
            url = tweet.get("url", "").strip().lower()
            if not url or url in existing:
                continue

            # Check it has video
            media = tweet.get("extendedEntities", {}).get("media", [{}])[0]
            if not media.get("video_info"):
                continue

            try:
                create_idea_record(at, table_ideas, tweet)
                existing.add(url)
                created += 1
            except Exception as e:
                log(f"  Failed to create idea: {e}")

            time.sleep(0.2)  # Rate limit

    # Clean up duplicates
    delete_duplicates(at, table_ideas)

    log(f"=== Scraper: Done. Created {created} new Ideas ===")
    return created


if __name__ == "__main__":
    from config import get_airtable_token, load_config
    token = get_airtable_token()
    cfg = load_config(token)
    run_scraper(cfg)
