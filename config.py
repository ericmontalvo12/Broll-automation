#!/usr/bin/env python3
"""
Content Mate v2.2 — Config Module
Reads all configuration from the Airtable Setup table.
No .env files needed — everything lives in Airtable.
"""

import json
import ssl
import certifi
from urllib.request import Request, urlopen
from pathlib import Path

SSL_CTX = ssl.create_default_context(cafile=certifi.where())
PROJECT_DIR = Path(__file__).resolve().parent
VIDEOS_DIR = PROJECT_DIR / "videos"
VIDEOS_DIR.mkdir(exist_ok=True)

# The master Airtable token is the only thing needed locally.
# Everything else is read from the Setup table.
MASTER_BASE_ID = "appiylDeyIoveRx9L"
SETUP_TABLE_ID = "tbl9lERWgvsDYc0GD"


def _api_get(url, headers=None):
    req = Request(url, headers=headers or {})
    resp = urlopen(req, context=SSL_CTX)
    return json.loads(resp.read())


def _api_request(url, data=None, method="GET", headers=None):
    h = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=h, method=method)
    resp = urlopen(req, context=SSL_CTX)
    return json.loads(resp.read())


def load_config(airtable_token: str) -> dict:
    """Load config from the Setup table. Returns a flat dict of all fields."""
    url = f"https://api.airtable.com/v0/{MASTER_BASE_ID}/{SETUP_TABLE_ID}?filterByFormula={{Active}}"
    data = _api_get(url, {"Authorization": f"Bearer {airtable_token}"})
    records = data.get("records", [])
    if not records:
        raise RuntimeError("No active config found in Setup table")
    fields = records[0].get("fields", {})

    # Build config dict with clean key names
    config = {
        # Airtable
        "airtable_token": airtable_token,
        "base_id": fields.get("Airtable Base ID", MASTER_BASE_ID),
        "table_create": fields.get("Table Create ID", ""),
        "table_ideas": fields.get("Table Ideas ID", ""),
        "table_x": fields.get("Table X ID", ""),
        "table_avatars": fields.get("Table Avatars ID", ""),
        "table_music": fields.get("Table Music ID", ""),

        # API Keys
        "twitter_api_key": fields.get("TwitterAPI Key", ""),
        "openai_api_key": fields.get("OpenAI API Key", ""),
        "anthropic_api_key": fields.get("Claude API API Key", ""),
        "elevenlabs_api_key": fields.get("ElevenLabs API Key", ""),
        "replicate_api_token": fields.get("Replicate API Token", ""),
        "blotato_api_key": fields.get("Blotato API Key", ""),
        "google_drive_folder_id": fields.get("Google Drive Folder ID", ""),
        "pexels_api_key": fields.get("Pexels API Key", ""),
        "table_broll": fields.get("Table B-Roll ID", ""),

        # Blotato Account IDs
        "youtube_account_id": fields.get("YouTube Account ID", ""),
        "instagram_account_id": fields.get("Instagram Account ID", ""),
        "tiktok_account_id": fields.get("TikTok Account ID", ""),
        "facebook_account_id": fields.get("Facebook Account ID", ""),
        "x_account_id": fields.get("X Account ID", ""),
        "pinterest_account_id": fields.get("Pinterest Account ID", ""),
        "linkedin_account_id": fields.get("Linkedin Account ID", ""),
        "bluesky_account_id": fields.get("Bluesky Account ID", ""),
        "threads_account_id": fields.get("Threads Account ID", ""),
        "facebook_page_id": fields.get("Facebook Page ID", ""),
        "pinterest_board_id": fields.get("Pinterest Board ID", ""),

        # Auto-posting
        "auto_post_platforms": fields.get("Auto Post Platforms", ""),

        # Telegram
        "telegram_token": fields.get("Telegram Access Token", ""),
        "telegram_chat_id": fields.get("Telegram Chat ID", ""),

        # Local paths
        "videos_dir": str(VIDEOS_DIR),
    }
    return config


def get_airtable_token() -> str:
    """Get the Airtable token. Checks env file in project root, then parent dirs."""
    search_paths = [
        PROJECT_DIR / ".env",
        PROJECT_DIR.parent.parent / ".env",
    ]
    for env_path in search_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("AIRTABLE_PERSONAL_ACCESS_TOKEN="):
                        return line.split("=", 1)[1].strip()
    raise RuntimeError("No AIRTABLE_PERSONAL_ACCESS_TOKEN found in .env")


def get_blotato_api_key() -> str:
    """Get the Blotato API key from .env."""
    search_paths = [
        PROJECT_DIR / ".env",
        PROJECT_DIR.parent.parent / ".env",
    ]
    for env_path in search_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("BLOTATO_API_KEY="):
                        return line.split("=", 1)[1].strip()
    return ""


def get_env_var(key: str, default: str = "") -> str:
    """Get any env var from .env file."""
    search_paths = [
        PROJECT_DIR / ".env",
        PROJECT_DIR.parent.parent / ".env",
    ]
    for env_path in search_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key}="):
                        return line.split("=", 1)[1].strip()
    return default
