#!/usr/bin/env python3
"""
Competitor Post Scraper — TikTok + Instagram
Finds viral posts from competitor accounts, recreates them with Claude,
then runs them through the existing video pipeline.

Plug-in ready: set COMPETITOR_API_PROVIDER to "apify" (default) or "rapidapi".

Config (env vars or Airtable Setup table fields):
  COMPETITOR_API_PROVIDER        — "apify" or "rapidapi"
  COMPETITOR_API_KEY             — your Apify or RapidAPI token
  COMPETITOR_TIKTOK_HANDLES      — comma-separated: primal.viking,hubermanlab
  COMPETITOR_INSTAGRAM_HANDLES   — comma-separated: primal.viking
  COMPETITOR_VIRAL_THRESHOLD     — min views to count as viral (default: 10000)
  COMPETITOR_MAX_PER_HANDLE      — max posts to fetch per account (default: 20)
"""

import json
import os
import subprocess
import time
from datetime import datetime
from airtable_utils import AirtableClient


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── Apify ─────────────────────────────────────────────────────────────────────

def _apify_run(api_key: str, actor_id: str, input_data: dict, timeout: int = 90) -> list:
    """Run an Apify actor (sync) and return dataset items."""
    url = (
        f"https://api.apify.com/v2/acts/{actor_id}"
        f"/run-sync-get-dataset-items?token={api_key}&timeout={timeout}"
    )
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(input_data), url],
            capture_output=True, text=True, timeout=timeout + 15
        )
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else data.get("items", [])
    except Exception as e:
        log(f"  Apify error ({actor_id}): {e}")
        return []


def _scrape_tiktok_apify(api_key: str, handles: list, max_per: int) -> list:
    log(f"  Apify TikTok: {handles}")
    raw = _apify_run(api_key, "clockworks~tiktok-scraper", {
        "profiles": handles,
        "resultsType": "videos",
        "maxPostsPerUser": max_per,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    })
    out = []
    for item in raw:
        out.append({
            "_platform": "tiktok",
            "_handle": item.get("authorMeta", {}).get("name", ""),
            "id": item.get("id", ""),
            "desc": item.get("desc", item.get("text", "")),
            "views": item.get("videoMeta", {}).get("playCount", item.get("playCount", 0)),
            "likes": item.get("diggCount", 0),
            "url": item.get("webVideoUrl", ""),
        })
    log(f"  TikTok: {len(out)} posts")
    return out


def _scrape_instagram_apify(api_key: str, handles: list, max_per: int) -> list:
    log(f"  Apify Instagram: {handles}")
    direct_urls = [f"https://www.instagram.com/{h.lstrip('@')}/" for h in handles]
    raw = _apify_run(api_key, "apify~instagram-scraper", {
        "directUrls": direct_urls,
        "resultsType": "posts",
        "resultsLimit": max_per * max(len(handles), 1),
    })
    out = []
    for item in raw:
        if not (item.get("videoViewCount") or item.get("type") in ("Video", "GraphVideo")):
            continue
        out.append({
            "_platform": "instagram",
            "_handle": item.get("ownerUsername", ""),
            "id": item.get("id", ""),
            "desc": item.get("caption", ""),
            "views": item.get("videoViewCount", item.get("likesCount", 0)),
            "likes": item.get("likesCount", 0),
            "url": item.get("url", ""),
        })
    log(f"  Instagram: {len(out)} video posts")
    return out


# ── RapidAPI ──────────────────────────────────────────────────────────────────

def _rapidapi_get(api_key: str, host: str, path: str, params: dict = None) -> dict:
    from urllib.parse import urlencode
    url = f"https://{host}{path}"
    if params:
        url += "?" + urlencode(params)
    try:
        result = subprocess.run(
            ["curl", "-s",
             "-H", f"X-RapidAPI-Key: {api_key}",
             "-H", f"X-RapidAPI-Host: {host}", url],
            capture_output=True, text=True
        )
        return json.loads(result.stdout)
    except Exception:
        return {}


def _scrape_tiktok_rapidapi(api_key: str, handles: list, max_per: int) -> list:
    log(f"  RapidAPI TikTok: {handles}")
    host = "tiktok-api23.p.rapidapi.com"
    out = []
    for handle in handles:
        handle = handle.lstrip("@")
        data = _rapidapi_get(api_key, host, "/api/user/posts", {
            "uniqueId": handle, "count": max_per,
        })
        for v in data.get("itemList", []):
            out.append({
                "_platform": "tiktok",
                "_handle": handle,
                "id": v.get("id", ""),
                "desc": v.get("desc", ""),
                "views": v.get("stats", {}).get("playCount", 0),
                "likes": v.get("stats", {}).get("diggCount", 0),
                "url": f"https://www.tiktok.com/@{handle}/video/{v.get('id', '')}",
            })
        time.sleep(0.5)
    log(f"  TikTok: {len(out)} posts")
    return out


def _scrape_instagram_rapidapi(api_key: str, handles: list, max_per: int) -> list:
    log(f"  RapidAPI Instagram: {handles}")
    host = "instagram-scraper-api2.p.rapidapi.com"
    out = []
    for handle in handles:
        handle = handle.lstrip("@")
        data = _rapidapi_get(api_key, host, "/v1/posts", {"username_or_id_or_url": handle})
        for item in data.get("data", {}).get("items", [])[:max_per]:
            if item.get("media_type") != 2:  # 2 = video/reel
                continue
            cap = item.get("caption") or {}
            out.append({
                "_platform": "instagram",
                "_handle": handle,
                "id": item.get("id", ""),
                "desc": cap.get("text", "") if isinstance(cap, dict) else str(cap),
                "views": item.get("play_count", item.get("like_count", 0)),
                "likes": item.get("like_count", 0),
                "url": f"https://www.instagram.com/p/{item.get('code', '')}/",
            })
        time.sleep(0.5)
    log(f"  Instagram: {len(out)} video posts")
    return out


# ── Scrape dispatcher ──────────────────────────────────────────────────────────

def scrape_competitor_posts(config: dict) -> list:
    """Scrape TikTok and Instagram competitor posts. Returns normalized list."""
    provider = config.get("competitor_api_provider", "apify").lower()
    api_key = config.get("competitor_api_key", "")
    tiktok_handles = [h.strip() for h in config.get("competitor_tiktok_handles", "").split(",") if h.strip()]
    instagram_handles = [h.strip() for h in config.get("competitor_instagram_handles", "").split(",") if h.strip()]
    max_per = int(config.get("competitor_max_per_handle", 20))

    all_posts = []
    if provider == "apify":
        if tiktok_handles:
            all_posts += _scrape_tiktok_apify(api_key, tiktok_handles, max_per)
        if instagram_handles:
            all_posts += _scrape_instagram_apify(api_key, instagram_handles, max_per)
    elif provider == "rapidapi":
        if tiktok_handles:
            all_posts += _scrape_tiktok_rapidapi(api_key, tiktok_handles, max_per)
        if instagram_handles:
            all_posts += _scrape_instagram_rapidapi(api_key, instagram_handles, max_per)
    else:
        log(f"  Unknown provider '{provider}'. Use 'apify' or 'rapidapi'.")

    return all_posts


# ── Claude Recreation ─────────────────────────────────────────────────────────

RECREATION_PROMPT = """\
You are a viral short-form content writer for Rock Mountain Performance (@rockmountainperformance), \
a testosterone support brand for men who read labels and want research-backed formulas.

A competitor account posted this viral content. Your job: extract the HOOK STRUCTURE and CONCEPT, \
then recreate it with entirely different words and our branding.

COMPETITOR POST:
Platform: {platform}
Account: @{handle}
Views: {views:,}
Likes: {likes:,}
Caption/Description:
{desc}

TASK: Identify what made this viral (list format, "signs of X," shocking stat, challenge, etc.) \
and apply that exact structure to testosterone/hormonal health content for Rock Mountain Performance.

RULES:
- Completely new sentences — nothing verbatim from the original
- Tie everything to testosterone, hormonal health, or men's performance
- Mention Peak Performance supplement naturally in the caption
- Brand tone: measured, credible, direct — not bro-science or "alpha" language
- Claims must use cautious language: "may support," "is linked to," "research suggests"
- No emojis in on-screen text. Never name the competitor account.
- Follow the exact output format below

OUTPUT FORMAT — two sections separated by the exact delimiter ---CAPTION---

SECTION 1: ON-SCREEN TEXT
- First line: bold hook (format: **HOOK:** Your hook here)
- Then 4-8 short punchy lines or a numbered list (each under 50 characters)
- Final line: CTA — "Follow @rockmountainperformance" or "Comment TESTOSTERONE"

---CAPTION---

SECTION 2: CAPTION (150-350 words)
- Open by expanding the hook into a grabbing first line
- Educate with specific facts about testosterone or biology
- Naturally tie to Peak Performance by @rockmountainperformance (clinical doses, disclosed label)
- Close with: Follow @rockmountainperformance
- Final line: #Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance

Start immediately with **HOOK:** — no preamble.\
"""


def recreate_with_claude(api_key: str, post: dict) -> str:
    """Use Claude to recreate a viral competitor post concept for RMP."""
    prompt = RECREATION_PROMPT.format(
        platform=post.get("_platform", "social media"),
        handle=post.get("_handle", "competitor"),
        views=int(post.get("views", 0)),
        likes=int(post.get("likes", 0)),
        desc=(post.get("desc", "") or "")[:1200],
    )
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        log(f"  Claude recreation failed: {e}")
        return ""


# ── Deduplication via Ideas table ─────────────────────────────────────────────

def get_processed_urls(at: AirtableClient, table_ideas: str) -> set:
    """Return all competitor post URLs already stored in Ideas (to avoid re-processing)."""
    urls = set()
    if not table_ideas:
        return urls
    try:
        records = at.search_all(table_ideas)
        for r in records:
            link = r.get("fields", {}).get("Link", "").strip().lower()
            if link:
                urls.add(link)
    except Exception:
        pass
    return urls


def mark_as_processed(at: AirtableClient, table_ideas: str, post: dict):
    """Save a minimal record to Ideas so this competitor post is not re-processed."""
    if not table_ideas:
        return
    fields = {
        "Name": f"Competitor {post.get('_platform', '').title()} @{post.get('_handle', '')}",
        "Link": post.get("url", ""),
        "Text": (post.get("desc", "") or "")[:500],
        "Views": int(post.get("views", 0)),
    }
    try:
        at.create_record(table_ideas, fields)
    except Exception as e:
        log(f"  Warning: could not log to Ideas table: {e}")


# ── Category detection ─────────────────────────────────────────────────────────

def detect_category(desc: str) -> str:
    desc_lower = (desc or "").lower()
    if any(w in desc_lower for w in ["food", "eat", "diet", "meat", "steak", "protein", "egg", "nutrition"]):
        return "food"
    if any(w in desc_lower for w in ["workout", "gym", "lift", "exercise", "training", "muscle"]):
        return "workout"
    return "lifestyle"


# ── Main ───────────────────────────────────────────────────────────────────────

def run_competitor_scraper(config: dict) -> int:
    """
    Find viral competitor posts → recreate with Claude → run through video pipeline.
    Returns number of videos created.
    """
    from simple_creator import run_creator

    api_key = config.get("competitor_api_key", "")
    anthropic_key = config.get("anthropic_api_key", "")
    table_ideas = config.get("table_ideas", "")
    viral_threshold = int(config.get("competitor_viral_threshold", 10000))
    tiktok_handles = config.get("competitor_tiktok_handles", "")
    instagram_handles = config.get("competitor_instagram_handles", "")

    if not api_key:
        log("  No COMPETITOR_API_KEY — skipping")
        return 0
    if not anthropic_key:
        log("  No Claude API key — cannot recreate scripts")
        return 0
    if not tiktok_handles and not instagram_handles:
        log("  No competitor handles configured — skipping")
        return 0

    log("=== Competitor Scraper: Starting ===")
    log(f"  Provider: {config.get('competitor_api_provider', 'apify')}")
    log(f"  Viral threshold: {viral_threshold:,} views")

    at = AirtableClient(config)
    processed = get_processed_urls(at, table_ideas)
    log(f"  Already processed: {len(processed)} posts")

    all_posts = scrape_competitor_posts(config)
    log(f"  Total scraped: {len(all_posts)} posts")

    # Filter: viral only, not already processed, must have some description
    viral = [
        p for p in all_posts
        if int(p.get("views", 0)) >= viral_threshold
        and p.get("url", "").strip().lower() not in processed
        and p.get("desc", "")
    ]
    viral.sort(key=lambda p: int(p.get("views", 0)), reverse=True)
    log(f"  Viral & new: {len(viral)} posts")

    created = 0
    for post in viral[:3]:  # Top 3 per run to control API cost
        log(f"\n  @{post.get('_handle')} [{post.get('_platform')}] — {int(post.get('views', 0)):,} views")
        log(f"  Desc: {str(post.get('desc', ''))[:120]}...")

        script = recreate_with_claude(anthropic_key, post)
        if not script:
            log("  Skipping — recreation failed")
            continue

        if "---CAPTION---" not in script:
            log("  Skipping — Claude did not return expected format")
            continue

        log(f"  Recreated: {script[:80]}...")

        category = detect_category(post.get("desc", ""))
        log(f"  Running pipeline (category={category})...")

        try:
            record_id = run_creator(config, category=category, competitor_script=script)
            if record_id:
                created += 1
                mark_as_processed(at, table_ideas, post)
                log(f"  Done: {record_id}")
        except Exception as e:
            log(f"  Pipeline error: {e}")

        time.sleep(2)

    log(f"\n=== Competitor Scraper: Done. Created {created} videos ===")
    return created


if __name__ == "__main__":
    from config import get_airtable_token, load_config, get_env_var

    token = get_airtable_token()
    cfg = load_config(token)

    # Override with env vars when set
    for env_var, cfg_key in [
        ("COMPETITOR_API_PROVIDER", "competitor_api_provider"),
        ("COMPETITOR_API_KEY", "competitor_api_key"),
        ("COMPETITOR_TIKTOK_HANDLES", "competitor_tiktok_handles"),
        ("COMPETITOR_INSTAGRAM_HANDLES", "competitor_instagram_handles"),
        ("COMPETITOR_VIRAL_THRESHOLD", "competitor_viral_threshold"),
        ("COMPETITOR_MAX_PER_HANDLE", "competitor_max_per_handle"),
        ("BLOTATO_API_KEY", "blotato_api_key"),
        ("BLOTATO_INSTAGRAM_ACCOUNT_ID", "instagram_account_id"),
        ("BLOTATO_TIKTOK_ACCOUNT_ID", "tiktok_account_id"),
        ("AUTO_POST_PLATFORMS", "auto_post_platforms"),
    ]:
        val = get_env_var(env_var)
        if val:
            cfg[cfg_key] = val

    run_competitor_scraper(cfg)
