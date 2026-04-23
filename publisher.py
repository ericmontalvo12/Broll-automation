#!/usr/bin/env python3
"""
Content Mate v2.2 — Publisher Module
Replaces: n8n Publish Schedule → Blotato → 9 platforms

Finds records with Status="Schedule", generates platform-specific captions,
uploads via Blotato to all 9 platforms, updates status to Published.
"""

import json
import random
import subprocess
import time
from datetime import datetime
from airtable_utils import AirtableClient, api_request, api_get

BLOTATO_API = "https://backend.blotato.com/v2"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── Caption Generation ──────────────────────────────────────────────────────

CAPTION_SYSTEM_PROMPT = """You are a caption generator that returns ONLY a single valid JSON object with these keys:
"Instagram caption", "Facebook caption", "Twitter caption", "TikTok caption", "YouTube short caption", "YouTube short title", "LinkedIn caption", "Bluesky caption", "Threads caption", "Pinterest caption".

Goal
Create concise, platform-tailored captions for a short-form video. The user will provide a YouTube or short-form script as input. Extract the hook, the core benefit, and 1 to 2 concrete specifics. Focus entirely on delivering value, clarity, and insight. Do NOT include engagement prompts or calls to action. Never Include Hashtags.

Platform styles:
1. Instagram: 80-120 chars, hook + benefit, 1 emoji max
2. Facebook: 100-160 chars, friendly, value-focused
3. Twitter: 80-120 chars, tight hook + 1 detail
4. TikTok: 60-100 chars, high-energy hook
5. YouTube short caption: 100-150 chars, value statement
6. YouTube short title: 40-60 chars, outcome-led, strong verb
7. LinkedIn: 140-200 chars, professional, no emojis
8. Bluesky: 80-120 chars, conversational
9. Threads: 80-120 chars, casual
10. Pinterest: 100-150 chars, curiosity-driven

Return format:
{"Instagram caption": "...", "Facebook caption": "...", "Twitter caption": "...", "TikTok caption": "...", "YouTube short caption": "...", "YouTube short title": "...", "LinkedIn caption": "...", "Bluesky caption": "...", "Threads caption": "...", "Pinterest caption": "..."}"""


def generate_captions(config: dict, script: str, source_text: str) -> dict:
    """Generate platform-specific captions using Claude."""
    import anthropic

    api_key = config.get("anthropic_api_key", "")
    if not api_key:
        raise ValueError("No Claude API key found in config")

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=CAPTION_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": (
                f"{script}\n\n{source_text}\n\n"
                "Make this into SEO optimized objects for each platform. "
                "For the Youtube Title, make sure to add the update name as the first word(s). "
                "NEVER use Hashtags\n\n"
                "Return ONLY valid JSON, no other text."
            )}
        ]
    )
    content = response.content[0].text
    return json.loads(content)


# ── Blotato Publishing ──────────────────────────────────────────────────────

def upload_media_to_blotato(config: dict, video_url: str) -> str:
    """Upload media to Blotato and return the public media URL."""
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BLOTATO_API}/media",
         "-H", f"Authorization: Bearer {config['blotato_api_key']}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"url": video_url})],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    media_url = data.get("url", "")
    log(f"  Blotato media: {media_url[:80]}...")
    return media_url


def blotato_post(config: dict, body: dict) -> dict:
    """Send a post request to Blotato."""
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BLOTATO_API}/posts",
         "-H", f"Authorization: Bearer {config['blotato_api_key']}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body)],
        capture_output=True, text=True
    )
    return json.loads(result.stdout) if result.stdout else {}


def publish_to_all_platforms(config: dict, captions: dict, media_url: str):
    """Publish to all 9 platforms via Blotato. Returns dict of platform → result."""
    yt_caption = captions.get("YouTube short caption", "")
    yt_title = captions.get("YouTube short title", "")
    fb_caption = captions.get("Facebook caption", "")

    results = {}

    # YouTube
    resp = blotato_post(config, {"post": {
        "accountId": config["youtube_account_id"],
        "content": {"text": f"{yt_caption} #short", "mediaUrls": [media_url], "platform": "youtube"},
        "target": {"targetType": "youtube", "title": yt_title,
                   "privacyStatus": "public", "shouldNotifySubscribers": False}
    }})
    results["YouTube"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} YouTube: {results['YouTube'][:50]}")
    time.sleep(1)

    # TikTok
    resp = blotato_post(config, {"post": {
        "accountId": config["tiktok_account_id"],
        "content": {"text": yt_caption, "mediaUrls": [media_url], "platform": "tiktok"},
        "target": {"targetType": "tiktok", "privacyLevel": "PUBLIC_TO_EVERYONE",
                   "disabledComments": False, "disabledDuet": False, "disabledStitch": False,
                   "isBrandedContent": False, "isYourBrand": False, "isAiGenerated": True}
    }})
    results["TikTok"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} TikTok: {results['TikTok'][:50]}")
    time.sleep(1)

    # Facebook
    resp = blotato_post(config, {"post": {
        "accountId": config["facebook_account_id"],
        "content": {"text": fb_caption, "mediaUrls": [media_url], "platform": "facebook"},
        "target": {"targetType": "facebook", "pageId": config["facebook_page_id"]}
    }})
    results["Facebook"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} Facebook: {results['Facebook'][:50]}")
    time.sleep(1)

    # Instagram
    resp = blotato_post(config, {"post": {
        "accountId": config["instagram_account_id"],
        "content": {"text": yt_caption, "mediaUrls": [media_url], "platform": "instagram"},
        "target": {"targetType": "instagram"}
    }})
    results["Instagram"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} Instagram: {results['Instagram'][:50]}")
    time.sleep(1)

    # LinkedIn
    resp = blotato_post(config, {"post": {
        "accountId": config["linkedin_account_id"],
        "content": {"text": yt_caption, "mediaUrls": [media_url], "platform": "linkedin"},
        "target": {"targetType": "linkedin"}
    }})
    results["LinkedIn"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} LinkedIn: {results['LinkedIn'][:50]}")
    time.sleep(1)

    # X/Twitter
    resp = blotato_post(config, {"post": {
        "accountId": config["x_account_id"],
        "content": {"text": f"{yt_caption} ", "mediaUrls": [media_url], "platform": "twitter"},
        "target": {"targetType": "twitter"}
    }})
    results["X"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} X/Twitter: {results['X'][:50]}")
    time.sleep(1)

    # Pinterest
    resp = blotato_post(config, {"post": {
        "accountId": config["pinterest_account_id"],
        "content": {"text": yt_caption, "mediaUrls": [media_url], "platform": "pinterest"},
        "target": {"targetType": "pinterest", "boardId": config["pinterest_board_id"]}
    }})
    results["Pinterest"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} Pinterest: {results['Pinterest'][:50]}")
    time.sleep(1)

    # Bluesky
    resp = blotato_post(config, {"post": {
        "accountId": config["bluesky_account_id"],
        "content": {"text": yt_caption, "mediaUrls": [media_url], "platform": "bluesky"},
        "target": {"targetType": "bluesky"}
    }})
    results["Bluesky"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} Bluesky: {results['Bluesky'][:50]}")
    time.sleep(1)

    # Threads
    resp = blotato_post(config, {"post": {
        "accountId": config["threads_account_id"],
        "content": {"text": yt_caption, "mediaUrls": [media_url], "platform": "threads"},
        "target": {"targetType": "threads"}
    }})
    results["Threads"] = resp.get("postSubmissionId", resp.get("message", "failed"))
    log(f"  {'V' if 'postSubmissionId' in resp else 'X'} Threads: {results['Threads'][:50]}")

    return results


# ── Telegram Notification ──────────────────────────────────────────────────

def send_telegram(config: dict, message: str):
    """Send Telegram notification."""
    token = config.get("telegram_token", "")
    chat_id = config.get("telegram_chat_id", "")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        api_request(url, {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }, method="POST")
    except Exception as e:
        log(f"  Telegram failed: {e}")


# ── Main Publisher Pipeline ─────────────────────────────────────────────────

def run_publisher(config: dict):
    """Find all Schedule records and publish them."""
    at = AirtableClient(config)

    log("=== Publisher: Starting ===")

    # Find records with Status = Schedule (matches n8n formula exactly)
    records = at.search(
        config["table_create"],
        formula='IF(FIND("Schedule", {Status}), 1, 0)',
        sort_field="Date Created",
        sort_dir="desc",
        max_records=1
    )

    if not records:
        log("No records with Status='Schedule' found")
        return 0

    published = 0
    for rec in records:
        fields = rec.get("fields", {})
        record_id = rec["id"]
        name = fields.get("Name", "?")
        script = fields.get("YT Short Script", "")
        source_text = fields.get("Source Text", "")
        video_url = fields.get("Caption Drive", "")

        if not video_url:
            log(f"  Skipping {name}: no video URL")
            continue

        log(f"Publishing: {name}")

        # Generate captions
        log("  Generating captions...")
        captions = generate_captions(config, script, source_text)
        yt_title = captions.get("YouTube short title", name)

        # Upload media to Blotato
        log("  Uploading to Blotato...")
        media_url = upload_media_to_blotato(config, video_url)

        # Publish to all platforms
        log("  Publishing to platforms...")
        results = publish_to_all_platforms(config, captions, media_url)

        # Update Airtable
        at.update_record(config["table_create"], record_id, {
            "Status": "Published",
            "Publish Time": datetime.now().isoformat(),
        })

        # Get counts for telegram
        schedule_count = len(at.search(config["table_create"], formula='{Status} = "Schedule"'))
        review_count = len(at.search(config["table_create"], formula='{Status} = "Review"'))
        published_count = len(at.search(config["table_create"], formula='{Status} = "Published"'))

        # Send Telegram notification
        emojis = ['🔥', '✨', '🚀', '🎬', '💫', '🤯', '🎉', '🥳', '💡', '⚡️']
        msg = (
            f"{random.choice(emojis)} Video Published\n"
            f"{yt_title}\n\n"
            f"Schedule / Review / Published: {schedule_count} / {review_count} / {published_count}"
        )
        send_telegram(config, msg)

        published += 1
        log(f"  Published: {name}")

    log(f"=== Publisher: Done. Published {published} videos ===")
    return published


if __name__ == "__main__":
    from config import get_airtable_token, load_config
    token = get_airtable_token()
    cfg = load_config(token)
    run_publisher(cfg)
