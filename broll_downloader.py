#!/usr/bin/env python3
"""
B-Roll Downloader for Content Mate v2.2
Downloads workout, food, and lifestyle videos from Pexels API.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from airtable_utils import AirtableClient, api_request

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


PEXELS_SEARCH_TERMS = {
    "workout": ["gym workout", "weightlifting", "man exercising", "fitness training", "bodybuilding"],
    "food": ["healthy food", "steak dinner", "grilled meat", "protein meal", "salmon fillet"],
    "lifestyle": ["sunrise workout", "coffee morning", "male confidence", "strong man", "nutrition"],
}

OUTPUT_DIR = Path(__file__).resolve().parent / "broll"
OUTPUT_DIR.mkdir(exist_ok=True)


def search_pexels(api_key, query, per_page=5):
    import requests
    from urllib.parse import urlencode
    url = f"https://api.pexels.com/videos/search?{urlencode({'query': query, 'per_page': per_page, 'orientation': 'portrait'})}"
    log(f"  Pexels search: {query}")
    
    response = requests.get(url, headers={"Authorization": api_key}, timeout=30)
    log(f"  HTTP {response.status_code}")
    if response.status_code != 200:
        log(f"  Error: {response.text[:200]}")
        return []
    return response.json().get("videos", [])


def download_pexels_video(api_key, video_id, output_path):
    import requests
    url = f"https://api.pexels.com/videos/videos/{video_id}"
    headers = {"Authorization": api_key}
    result = api_request(url, headers=headers)
    
    video_files = result.get("video_files", [])
    log(f"  Video files: {len(video_files)} found")
    mp4s = [v for v in video_files if v.get("file_type") == "video/mp4"]
    if not mp4s:
        return None
    
    mp4s.sort(key=lambda v: v.get("width", 0) * v.get("height", 0), reverse=True)
    if not mp4s:
        log(f"  No MP4 files found in: {[v.get('file_type') for v in video_files]}")
        return None
    
    video_url = mp4s[0].get("link")
    
    if "?" not in video_url:
        video_url += f"?api_key={api_key}"
    
    log(f"  Downloading from: {video_url[:60]}...")
    
    response = requests.get(video_url, headers={
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Client-ID {api_key}"
    }, stream=True, timeout=60)
    if response.status_code != 200:
        log(f"  HTTP {response.status_code}: {response.text[:100]}")
        return None
    
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return output_path


def add_to_airtable(at, table_id, category, search_term, video_path, video_data):
    duration = video_data.get("duration", 0)
    width = video_data.get("width", 1080)
    height = video_data.get("height", 1920)
    orientation = "Portrait" if height > width else "Landscape"
    
    record = {
        "Category": category,
        "Search Term": search_term,
        "Title": video_data.get("url", "").split("/")[-1][:100],
        "Pexels ID": str(video_data.get("id", "")),
        "Duration (sec)": duration,
        "Orientation": orientation,
        "Status": "New",
    }
    
    created = at.create_record(table_id, record)
    log(f"  Added to Airtable: {created['id']}")
    return created


def ensure_broll_table(at, config):
    table_id = config.get("table_broll", "")
    if table_id:
        return table_id
    
    base_id = config.get("base_id", "")
    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    headers = {"Authorization": f"Bearer {config['airtable_token']}"}
    result = api_request(url, headers=headers)
    
    for table in result.get("tables", []):
        if table.get("name") == "B-Roll":
            return table.get("id")
    
    body = {
        "tables": [{
            "name": "B-Roll",
            "fields": [
                {"name": "Category", "type": "singleSelect", "options": {"choices": [{"name": c} for c in PEXELS_SEARCH_TERMS.keys()]}},
                {"name": "Search Term", "type": "singleLineText"},
                {"name": "Title", "type": "singleLineText"},
                {"name": "Pexels ID", "type": "number"},
                {"name": "Duration (sec)", "type": "number"},
                {"name": "Orientation", "type": "singleSelect", "options": {"choices": [{"name": "Portrait"}, {"name": "Landscape"}]}},
                {"name": "Status", "type": "singleSelect", "options": {"choices": [{"name": "Ready"}, {"name": "Used"}, {"name": "Error"}]}},
                {"name": "Video File", "type": "url"},
            ]
        }]
    }
    
    result = api_request(url, body, method="POST", headers=headers)
    new_table = result.get("tables", [{}])[0]
    log(f"Created B-Roll table: {new_table.get('id')}")
    return new_table.get("id")


def run_broll_download(config, category=None, videos_per_term=1):
    at = AirtableClient(config)
    pexels_key = config.get("pexels_api_key", "")
    
    log(f"Pexels key loaded: {pexels_key[:20] if pexels_key else 'EMPTY'}...")
    
    if not pexels_key:
        log("ERROR: Pexels API key not found in Setup table")
        return
    
    table_id = ensure_broll_table(at, config)
    if not table_id:
        log("ERROR: Could not create/find B-Roll table")
        return
    
    categories = [category] if category else list(PEXELS_SEARCH_TERMS.keys())
    
    total_downloaded = 0
    max_per_run = 2
    
    for cat in categories:
        if total_downloaded >= max_per_run:
            break
        if cat not in PEXELS_SEARCH_TERMS:
            log(f"Unknown category: {cat}")
            continue
        
        log(f"=== Downloading {cat} videos ===")
        for term in PEXELS_SEARCH_TERMS[cat]:
            if total_downloaded >= max_per_run:
                break
            log(f"Searching: {term}")
            videos = search_pexels(pexels_key, term, per_page=videos_per_term)
            
            if not videos:
                log(f"  No results for: {term}")
                continue
            
            log(f"  Found {len(videos)} videos")
            
            for i, video in enumerate(videos[:videos_per_term]):
                if total_downloaded >= max_per_run:
                    break
                video_id = video.get("id")
                filename = f"{cat}_{video_id}.mp4"
                output_path = OUTPUT_DIR / filename
                
                if output_path.exists():
                    log(f"  [{i+1}] Already downloaded: {filename}")
                    continue
                
                log(f"  [{i+1}] Downloading: {video_id} ({video.get('duration', 0)}s)")
                try:
                    result = download_pexels_video(pexels_key, video_id, output_path)
                    if result:
                        add_to_airtable(at, table_id, cat, term, str(output_path), video)
                        total_downloaded += 1
                        log(f"  Saved: {filename}")
                    else:
                        log(f"  Failed to get download URL")
                except Exception as e:
                    log(f"  Error: {e}")
                
                time.sleep(1)
    
    log(f"=== B-Roll download complete: {total_downloaded} videos ===")


if __name__ == "__main__":
    import sys
    from config import get_airtable_token, load_config
    
    token = get_airtable_token()
    cfg = load_config(token)
    
    category = sys.argv[1] if len(sys.argv) > 1 else None
    run_broll_download(cfg, category)
