#!/usr/bin/env python3
"""
Content Mate v2.2 — Creator Module
Replaces: n8n auto-create flow

Pipeline: Idea → Tweet fetch → Research → Script → Voice → Avatar lipsync →
          Combine videos → Add music → Captions (local Whisper) → Review

Each step updates Airtable status so you can see progress.

URL strategy:
- Avatar/Music URLs: Replicate file upload (permanent)
- 3s voice clip: Airtable attachment (temporary, only needed for one lipsync job)
- Captions: Local faster-whisper (no API needed)
"""

import json
import os
import random
import subprocess
import time
import base64
from datetime import datetime
from pathlib import Path
from airtable_utils import AirtableClient, api_get, api_request, curl_get

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── File Upload Utilities ───────────────────────────────────────────────────

def upload_to_replicate(config: dict, file_path: str) -> str:
    """Upload a file to Replicate and return a URL (auth-required, 24h expiry).
    Used for lipsync input files where temporary access is fine."""
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://api.replicate.com/v1/files",
         "-H", f"Authorization: Bearer {config['replicate_api_token']}",
         "-F", f"content=@{file_path}"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    file_url = data.get("urls", {}).get("get", "") or data.get("url", "")
    filename = os.path.basename(file_path)
    log(f"  Uploaded to Replicate: {filename}")
    return file_url


def upload_public(file_path: str) -> str:
    """Upload a file and return a public URL (no auth needed).
    Used for Airtable attachments and final video delivery."""
    filename = os.path.basename(file_path)
    result = subprocess.run(
        ["curl", "-s", "-F", "reqtype=fileupload",
         "-F", f"fileToUpload=@{file_path}",
         "https://catbox.moe/user/api.php"],
        capture_output=True, text=True
    )
    url = result.stdout.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"Upload failed: {result.stdout[:200]}")
    log(f"  Uploaded public: {filename} → {url}")
    return url


def upload_to_airtable_attachment(at: AirtableClient, config: dict,
                                   table_id: str, record_id: str,
                                   field_name: str, file_path: str) -> str:
    """Upload a file as an Airtable attachment and return the temporary URL.
    Good for files that only need to be accessible for a few hours (lipsync input)."""
    # Read file and encode as base64 data URL for Airtable
    # Actually, Airtable attachments need a URL to fetch from.
    # We'll use a different approach: upload via Replicate for the URL,
    # then attach that URL to Airtable.

    # For small files like 3s voice clips, we can use a temporary hosting approach
    # Upload to Replicate (works for any file)
    url = upload_to_replicate(config, file_path)

    # Update Airtable with the URL
    at.update_record(table_id, record_id, {
        field_name: url,
    })

    return url


# ── Step 1: Pick best idea ──────────────────────────────────────────────────

def pick_broll(at: AirtableClient, config: dict) -> dict:
    """Pick a random unprocessed B-Roll video."""
    table_id = config.get("table_broll", "")
    if not table_id:
        return None
    
    formula = "{Status}='Ready'"
    records = at.search(
        table_id,
        formula=formula,
        sort_field="Created",
        sort_dir="asc",
        max_records=1
    )
    return records[0] if records else None


def pick_idea(at: AirtableClient, config: dict, idea_record_id: str = None) -> dict:
    """Pick the best unprocessed idea, or a specific one."""
    if idea_record_id:
        return at.get_record(config["table_ideas"], idea_record_id)

    # Check for B-Roll first (testosterone brand mode)
    broll = pick_broll(at, config)
    if broll:
        log(f"  Selected B-Roll: {broll.get('fields', {}).get('Title', broll['id'])}")
        return broll

    # Strict filter (matches n8n view): 10-200s video, 20K+ views, horizontal, last 7 days, unused
    strict_formula = (
        "AND("
        "{Video (sec)}>10, "
        "{Video (sec)}<200, "
        "OR({Views}>20000, {Retweet Views}>20000), "
        "FIND('Horizontal', {Ratiox}), "
        "{Status}='', "
        "IS_AFTER({Date}, DATEADD(TODAY(), -7, 'days'))"
        ")"
    )
    records = at.search(
        config["table_ideas"],
        formula=strict_formula,
        sort_field="Views",
        sort_dir="desc",
        max_records=1
    )
    if records:
        f = records[0].get("fields", {})
        log(f"  Matched strict filter: {f.get('Views', 0):,} views, {f.get('Video (sec)', 0):.0f}s")
        return records[0]

    # Relaxed fallback: drop date filter, keep video length + views + status
    log("  No strict matches (last 7 days). Trying relaxed filter...")
    relaxed_formula = (
        "AND("
        "{Video (sec)}>10, "
        "{Video (sec)}<200, "
        "OR({Views}>20000, {Retweet Views}>20000), "
        "{Status}=''"
        ")"
    )
    records = at.search(
        config["table_ideas"],
        formula=relaxed_formula,
        sort_field="Views",
        sort_dir="desc",
        max_records=1
    )
    if records:
        f = records[0].get("fields", {})
        log(f"  Matched relaxed filter: {f.get('Views', 0):,} views, {f.get('Video (sec)', 0):.0f}s")
        return records[0]

    log("No qualifying ideas found. Run the scraper first.")
    return None


# ── Step 2: Create record + fetch tweet data ────────────────────────────────

def fetch_tweet(config: dict, tweet_url: str) -> dict:
    """Fetch full tweet data from TwitterAPI.io."""
    import re
    match = re.search(r'status/(\d+)', tweet_url)
    if not match:
        raise ValueError(f"Could not extract tweet ID from: {tweet_url}")

    tweet_id = match.group(1)
    url = f"https://api.twitterapi.io/twitter/tweets?tweet_ids={tweet_id}"
    result = subprocess.run(
        ["curl", "-s", url, "-H", f"X-API-Key: {config['twitter_api_key']}"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    tweets = data.get("tweets", [])
    if not tweets:
        raise ValueError(f"Tweet not found: {tweet_id}")
    return tweets[0]


def download_video(tweet: dict, output_path: str) -> str:
    """Download the video from a tweet or B-Roll."""
    media = tweet.get("extendedEntities", {}).get("media", [{}])[0]
    variants = media.get("video_info", {}).get("variants", [])

    mp4s = [v for v in variants if v.get("url", "").endswith(".mp4") or "video/mp4" in v.get("content_type", "")]
    if not mp4s:
        raise ValueError("No MP4 video found in tweet")

    mp4s.sort(key=lambda v: v.get("bitrate", 0), reverse=True)
    video_url = mp4s[0]["url"]

    subprocess.run(["curl", "-s", "-L", "-o", output_path, video_url], check=True)
    log(f"  Downloaded video: {output_path}")
    return output_path


def download_broll_video(broll: dict, output_path: str) -> str:
    """Download B-Roll video from local path or URL."""
    fields = broll.get("fields", {})
    
    # Check for local file path first
    local_path = fields.get("Local Path", "")
    if local_path and Path(local_path).exists():
        import shutil
        shutil.copy2(local_path, output_path)
        log(f"  Copied local B-Roll: {output_path}")
        return output_path
    
    # Check for video file URL
    video_url = fields.get("Video File", "") or fields.get("B-Roll URL", "")
    if not video_url:
        raise ValueError("No B-Roll URL found")
    
    subprocess.run(["curl", "-s", "-L", "-o", output_path, video_url], check=True)
    log(f"  Downloaded B-Roll: {output_path}")
    return output_path


# ── Step 3: Research + Script generation ────────────────────────────────────

def research_tweet(config: dict, tweet_text: str, author: str) -> str:
    """Use GPT-4o-mini-search to find more info about the tweet."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['openai_api_key']}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "gpt-4o-mini-search-preview-2025-03-11",
        "messages": [
            {"role": "user", "content": (
                f"find out more information about:\n{tweet_text}\n\n"
                f"Posted by {author} on x.\n\n"
                "They may have announced something or an update?\n"
                "I want you to find as many facts and information about it.\n\n"
                "Come back with at least 500 words"
            )}
        ]
    }
    result = api_request(url, body, method="POST", headers=headers)
    return result["choices"][0]["message"]["content"]


WPS = 2.4  # Words per second speaking rate

SCRIPT_SYSTEM_PROMPT = """You are a viral YouTube Shorts scriptwriter.
• Read the target length (seconds) and compute WORD_BUDGET = floor(seconds * WPS). Default WPS = {wps}.
• Output one script only, no pre/post text.
• Never exceed WORD_BUDGET words. If your draft is longer, compress before replying.
• 6th-grade reading level.
• Start with a jaw-dropping, "breaking news" style hook. Never use phrases that announce a company's actions (e.g., "Today we're showing", "We're expanding", "X company just launched/dropped"). Instead, immediately reveal an *unbelievable but true discovery* or a *secret* that *already exists* or *is now possible* for the viewer. This discovery must *immediately and tangibly transform the viewer's daily life* in a universally relatable way. It must spark intense curiosity by hinting at a dramatic, *experiential* shift, making them feel like they're about to gain a superpower or unlock a hidden truth. Focus entirely on *their immediate, personal, tangible gain*.
• Dive into compelling details: Elaborate with specific, verifiable facts, focusing on the *novelty* and *direct, tangible, experiential impact*. Paint a vivid *before and after* picture for the average person, using concrete, relatable scenarios that show what it *looks like, feels like, or enables* in *their* daily life. Explain precisely how this personally and immediately changes *their* routine, solves a common problem *they didn't even know could be solved*, or redefines *their* future possibilities. Briefly explain *how* it works in simple terms, if relevant. Emphasize the *feeling* of this change and the *new, almost magical possibilities* it unlocks.
• Maintain an energetic, conversational, and slightly hyperbolic tone: Inject excitement and wonder, making the information feel urgent and extraordinary, but always grounded in relatable benefits, avoiding misleading claims.
• Conclude with a truly shocking or mind-bending statement: This final sentence must deliver a powerful, unexpected twist or a profound, *personally relevant* implication that redefines *your* understanding of reality, leaving them stunned, questioning everything, and thinking long after the video ends. It should feel like a glimpse into a future they never imagined."""


def generate_script(config: dict, tweet_text: str, research_text: str, duration_sec: float) -> str:
    """Generate a YT Shorts script using O3. Word count matches source video duration."""
    target_sec = min(duration_sec, 45)
    word_budget = int(target_sec * WPS)

    log(f"  Target: {target_sec:.1f}s × {WPS} WPS = {word_budget} word budget")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['openai_api_key']}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "o3",
        "messages": [
            {"role": "system", "content": SCRIPT_SYSTEM_PROMPT.format(wps=WPS)},
            {"role": "user", "content": (
                f"The hook of the intro is usually found in this text, which is the viral X post we're using as inspiration:\n"
                f"{tweet_text}\n\n"
                f"Source Text body:\n{research_text}\n\n"
                f"Target length: seconds: {target_sec}\n\n"
                "Note: Never go over 45 Seconds\n\n"
                f"(Optional) Speaking rate override: {WPS} words per second."
            )}
        ]
    }
    result = api_request(url, body, method="POST", headers=headers)
    script = result["choices"][0]["message"]["content"]

    actual_words = len(script.split())
    log(f"  Script: {actual_words} words (budget was {word_budget})")
    if actual_words < word_budget * 0.5:
        log(f"  WARNING: Script is {actual_words} words but budget was {word_budget}. May be too short.")

    return script


TESTOSTERONE_SCRIPT_PROMPT = """You are a viral YouTube Shorts scriptwriter for Rock Mountain Performance (@rockmountainperformance), a transparent, research-aligned testosterone support brand.

BRAND IDENTITY:
- Built for men who verify. A testosterone support formula you can audit.
- Tone: Clear, clinical-lite, masculine, skeptical, controlled. Not aggressive or "alpha."
- Product: Peak Performance — clinical doses, fully disclosed labels, batch tested, 30-day guarantee.
- Brand sounds like: "Read the label." / "Check the dose." / "Judge the formula, not the claim."
- Brand enemy: Underdosed, hidden, overclaimed formulas.

Key themes: evidence-based testosterone support, hormonal health, heavy compound lifts, nutrient-dense diet, sleep and recovery, cold exposure, transparency in supplements.

FORBIDDEN: Never use "primal," "viking," "alpha male," "beef organs," or competitor names.

Rules:
• Target length: {target_sec:.0f} seconds (approx {word_budget} words at 2.4 WPS)
• 6th grade reading level
• Direct, educated, controlled, credible tone
• NO clickbait phrases like "You won't believe" or "This one thing"
• Start with a bold, evidence-based claim or question
• Include 1-2 specific facts about testosterone, hormones, or biology
• Use cautious language: "supports," "is linked to," "may increase"
• End with a CTA: follow @rockmountainperformance or comment a keyword

Example structure for {category} content:
- HOOK (3s): Direct statement about {category}
- PROOF (10s): Specific fact or mechanism about {category} and testosterone
- TRANSFORMATION (10s): What optimized hormonal health looks like
- CTA (3s): Follow @rockmountainperformance

Write ONE script now. No preambles. Start immediately with the script."""

TESTOSTERONE_SCRIPTS = {
    "workout": [
        "The fastest way to support your testosterone is not the gym. It is what you do after you lift. Your muscles recover in the 48 hours following a session. That is when testosterone does its work. Men who prioritize sleep and nutrient-dense food alongside heavy training see better hormonal outcomes than those who just grind. Recovery matters. Sleep 8 hours. Eat real food. Lift heavy compounds. This is evidence-based training.",
        "Stop doing cardio before weights. When you do cardio first, you may be depleting the hormonal resources your body needs for heavy resistance training. Train compounds first while your testosterone levels are highest in the morning. Squat. Deadlift. Press. Save cardio for after. This one change can make a measurable difference over a year.",
    ],
    "food": [
        "Red meat does not just build muscle. It supports testosterone production. Studies show beef provides zinc, cholesterol, and saturated fat — all precursors your body uses to synthesize testosterone. Without these building blocks, your endocrine system is working with less. Stop fearing dietary fat. Read the research. Eat the steak.",
        "Most men are not eating enough quality protein. The average man needs roughly 1 gram per pound of bodyweight to support muscle protein synthesis. That is biology. Beef, eggs, and salmon provide the amino acids and micronutrients your hormonal system requires. Check what you are actually consuming. The dose matters — in your food and in your supplements.",
    ],
    "lifestyle": [
        "Your testosterone levels peak in the morning. Morning sunlight on your skin supports vitamin D production, which is directly linked to testosterone synthesis. Get 10 to 20 minutes of direct sun exposure before noon. No sunglasses. Just you and the light. This is one of the simplest evidence-based habits for hormonal health.",
        "Cold exposure may support testosterone production. Research suggests that brief cold water exposure activates the HPG axis, the system responsible for hormonal signaling. Ending your shower with 60 seconds of cold water is a low-cost habit with potential hormonal benefits. Comfort is not always your friend.",
    ],
}


def generate_testosterone_script(config: dict, category: str, duration_sec: float) -> str:
    """Generate a testosterone brand script for B-Roll video."""
    target_sec = min(duration_sec, 45)
    word_budget = int(target_sec * WPS)
    
    log(f"  Testosterone script for {category}: {target_sec:.0f}s ({word_budget} words)")
    
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['openai_api_key']}",
        "Content-Type": "application/json"
    }
    
    body = {
        "model": "o3-mini",
        "messages": [
            {"role": "system", "content": TESTOSTERONE_SCRIPT_PROMPT.format(
                target_sec=target_sec,
                word_budget=word_budget,
                category=category
            )},
            {"role": "user", "content": f"Write a powerful testosterone-focused script for a {category} video. Duration: {target_sec:.0f} seconds."}
        ]
    }
    result = api_request(url, body, method="POST", headers=headers)
    return result["choices"][0]["message"]["content"]


# ── Step 4: Voice generation (ElevenLabs) ───────────────────────────────────

def generate_voice(config: dict, script: str, voice_id: str, output_path: str) -> str:
    """Generate voiceover using ElevenLabs TTS."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    body = {
        "text": script.replace("\n", " "),
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.9,
            "similarity_boost": 0.3,
            "style": 1,
            "use_speaker_boost": True,
            "speed": 1
        }
    }

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", url,
         "-H", f"xi-api-key: {config['elevenlabs_api_key']}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body),
         "-o", output_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"ElevenLabs TTS failed: {result.stderr}")

    log(f"  Generated voice: {output_path}")
    return output_path


def extract_3s_voice(full_voice_path: str, output_path: str) -> str:
    """Extract first 3 seconds of voiceover for lipsync."""
    subprocess.run([
        "ffmpeg", "-y", "-ss", "0", "-t", "3",
        "-i", full_voice_path, "-acodec", "copy", output_path
    ], capture_output=True, check=True)
    log(f"  Extracted 3s voice: {output_path}")
    return output_path


# ── Step 5: Avatar lipsync (Replicate/PixVerse) ────────────────────────────

def ensure_avatar_url(at: AirtableClient, config: dict, avatar: dict) -> str:
    """Get avatar video URL. Uses existing Drive/Replicate link, or uploads if needed."""
    fields = avatar.get("fields", {})

    # Check if Avatar link already exists (Drive or Replicate URL)
    avatar_link = fields.get("Avatar link", "") or ""
    if avatar_link:
        return avatar_link

    # Check for Airtable attachment as fallback
    avatar_attachments = fields.get("Avatar Animated", []) or fields.get("5s Vertical Vid", [])
    if not avatar_attachments:
        raise ValueError("No avatar video found in Avatars table")

    # Download from Airtable attachment, upload to Replicate for permanent URL
    temp_path = str(Path(config["videos_dir"]) / f"_temp_avatar_{avatar['id']}.mp4")
    att_url = avatar_attachments[0].get("url", "")
    subprocess.run(["curl", "-s", "-L", "-o", temp_path, att_url], check=True)

    permanent_url = upload_to_replicate(config, temp_path)
    at.update_record(config["table_avatars"], avatar["id"], {"Avatar link": permanent_url})
    os.remove(temp_path)

    return permanent_url


def ensure_music_url(at: AirtableClient, config: dict, music: dict) -> str:
    """Ensure music has a permanent Replicate URL. Upload if needed."""
    fields = music.get("fields", {})

    music_link = fields.get("Music Link", "") or ""
    if music_link and ("replicate" in music_link or "drive.google" in music_link):
        return music_link

    # Download from Airtable attachment, upload to Replicate
    music_attachments = fields.get("Music mp3", [])
    if not music_attachments:
        return ""

    temp_path = str(Path(config["videos_dir"]) / f"_temp_music_{music['id']}.mp3")
    att_url = music_attachments[0].get("url", "")
    subprocess.run(["curl", "-s", "-L", "-o", temp_path, att_url], check=True)

    permanent_url = upload_to_replicate(config, temp_path)

    # Save permanent URL back to Airtable
    at.update_record(config["table_music"], music["id"], {"Music Link": permanent_url})

    os.remove(temp_path)
    return permanent_url


def create_lipsync(config: dict, audio_url: str, avatar_video_url: str) -> str:
    """Create lipsync video using Replicate (PixVerse). Returns output video URL."""
    url = "https://api.replicate.com/v1/models/pixverse/lipsync/predictions"
    headers = {
        "Authorization": f"Bearer {config['replicate_api_token']}",
        "Content-Type": "application/json"
    }
    body = {
        "input": {
            "audio": audio_url,
            "video": avatar_video_url
        }
    }
    result = api_request(url, body, method="POST", headers=headers)
    prediction_url = result.get("urls", {}).get("get", "")

    # Poll until done
    for _ in range(60):
        time.sleep(10)
        status = api_get(prediction_url, {"Authorization": f"Bearer {config['replicate_api_token']}"})
        state = status.get("status", "")
        if state == "succeeded":
            log(f"  Lipsync complete!")
            return status["output"]
        if state == "failed":
            raise RuntimeError(f"Lipsync failed: {status.get('error', 'unknown')}")
        log(f"  Lipsync status: {state}...")

    raise RuntimeError("Lipsync timed out after 10 minutes")


# ── Step 6: FFmpeg video processing ─────────────────────────────────────────

def combine_avatar_and_source(source_video: str, clone_video: str, output_path: str, crop_top: int = 0) -> str:
    """Combine source video (top) with avatar clone (bottom) in 9:16 format."""
    top_h = 608
    gap = 1
    push = 0
    bottom_h = 1920 - (top_h + gap + push)
    bot_y = top_h + gap + push

    dur_result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", clone_video],
        capture_output=True, text=True
    )
    duration = dur_result.stdout.strip()

    cmd = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-i", clone_video,
        "-filter_complex",
        f"color=c=black:size=1080x1920:d=360[bg];"
        f"[0:v]scale=1080:{top_h}:flags=bicubic[top];"
        f"[1:v]scale=1080:-2[vs];"
        f"[vs]crop=w=1080:h={bottom_h}:x=0:y={crop_top}[bot];"
        f"[bg][top]overlay=x=0:y=0[tmp];"
        f"[tmp][bot]overlay=x=0:y={bot_y}[v];"
        f"[1:a]volume=1.5[a]",
        "-map", "[v]", "-map", "[a]",
        "-t", duration,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast",
        "-c:a", "aac", "-movflags", "+faststart",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    log(f"  Combined videos: {output_path}")
    return output_path


def transform_to_9x16(source_video: str, voice_path: str, output_path: str) -> str:
    """Transform source video to 9:16 with voiceover."""
    cmd = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-i", voice_path,
        "-filter_complex",
        "color=c=black:s=1080x1920:d=999[bg];"
        "[0:v]scale=1080:-1[vid];"
        "[bg][vid]overlay=(W-w)/2:(H-h)/2:eval=init,format=yuv420p[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        "-shortest", "-movflags", "+faststart", output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    log(f"  Transformed to 9:16: {output_path}")
    return output_path


def add_music_and_overlay(source_9x16: str, overlay_3s: str, music_path: str, output_path: str) -> str:
    """Combine 9:16 video with 3s avatar overlay and background music."""
    cmd = [
        "ffmpeg", "-y",
        "-i", source_9x16,
        "-i", overlay_3s,
        "-i", music_path,
        "-filter_complex",
        "[1:v]trim=0:3,setpts=PTS-STARTPTS,scale=iw*1:-1,fade=t=out:st=2.5:d=0.5:alpha=1[overlayfit];"
        "[0:v]setpts=PTS-STARTPTS[base];"
        "[base][overlayfit]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,3)'[vout];"
        "[0:a]volume=1.5[a0];"
        "[2:a]volume=0.1[a2];"
        "[a0][a2]amix=inputs=2:duration=first:dropout_transition=3[aout]",
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    log(f"  Added music + overlay: {output_path}")
    return output_path


# ── Step 7: Captions (ElevenLabs S2T → ASS → FFmpeg burn) ──────────────────

def transcribe_audio(config: dict, audio_path: str) -> list:
    """Transcribe audio using ElevenLabs Scribe v1. Returns word-level timestamps."""
    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         "https://api.elevenlabs.io/v1/speech-to-text",
         "-H", f"xi-api-key: {config['elevenlabs_api_key']}",
         "-H", "Accept: application/json",
         "-F", "model_id=scribe_v1",
         "-F", "language_code=en",
         "-F", "speaker_diarization=true",
         "-F", "tag_audio_events=true",
         "-F", f"file=@{audio_path}"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)

    # Parse ElevenLabs Scribe format: words with {text, start, end, type}
    words = []
    for w in data.get("words", []):
        if str(w.get("type", "")).lower() != "word":
            continue
        words.append({
            "word": str(w.get("text", "")),
            "start": float(w.get("start", 0)),
            "end": float(w.get("end", 0))
        })

    log(f"  Transcribed {len(words)} words (ElevenLabs Scribe)")
    return words


def create_ass_subtitles(words: list, output_path: str):
    """Create ASS subtitle file from word-level timestamps.
    Ported from the n8n Create Ass node — groups of 3, cyan highlight, hold last line."""
    if not words:
        log("  WARNING: No words found in transcription")
        return

    # Config (matches n8n)
    WORDS_TO_SHOW = 3
    HOLD_LAST_LINE = True
    MAX_HOLD_GAP_SEC = 0.6
    MIN_WORD_DUR_SEC = 0.08
    FONT = "Arial"
    FONT_SIZE = 50
    HIGHLIGHT_COLOR = "00FFFF"
    MARGIN_V = 1270

    def cs_fmt(cs):
        cs = max(0, int(cs))
        h = cs // 360000; cs %= 360000
        m = cs // 6000; cs %= 6000
        s = cs // 100; c = cs % 100
        return f"{h}:{m:02d}:{s:02d}.{c:02d}"

    def esc_ass(t):
        return str(t or "").replace("\r", " ").replace("\n", " ").upper()

    # Sort and fix zero-duration words
    words.sort(key=lambda w: (w["start"], w["end"]))
    for w in words:
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + MIN_WORD_DUR_SEC

    # Create groups (break on sentence end or max words)
    groups = []
    cur = []
    for i, w in enumerate(words):
        cur.append(w)
        txt = w["word"].strip()
        end_of_sentence = txt and txt[-1] in ".!?"
        at_limit = len(cur) >= WORDS_TO_SHOW
        last = i == len(words) - 1
        if at_limit or end_of_sentence or last:
            if cur:
                groups.append(cur[:])
            cur = []
    if cur:
        groups.append(cur)

    # Build dialogue lines
    raw_lines = []
    for g in groups:
        for hi in range(len(g)):
            w = g[hi]
            parts = []
            for j, gw in enumerate(g):
                token = esc_ass(gw["word"]).strip()
                if j == hi:
                    parts.append("{\\fs" + str(FONT_SIZE) + "\\c&H" + HIGHLIGHT_COLOR + "&}" + token + "{\\r}")
                else:
                    parts.append(token)
            raw_lines.append({
                "text": " ".join(parts),
                "s": max(0, int(w["start"] * 100)),
                "e": max(0, int(w["end"] * 100 + 0.5))
            })

    # Ensure minimum duration
    min_dur_cs = max(1, round(MIN_WORD_DUR_SEC * 100))
    for L in raw_lines:
        if L["e"] < L["s"] + min_dur_cs:
            L["e"] = L["s"] + min_dur_cs

    # Fix overlaps
    for i in range(len(raw_lines) - 1):
        a, b = raw_lines[i], raw_lines[i + 1]
        if b["s"] < a["e"]:
            b["s"] = a["e"]
            if b["e"] < b["s"] + min_dur_cs:
                b["e"] = b["s"] + min_dur_cs

    # Hold last line during silence
    if HOLD_LAST_LINE:
        max_hold_cs = round(MAX_HOLD_GAP_SEC * 100)
        for i in range(len(raw_lines) - 1):
            gap = raw_lines[i + 1]["s"] - raw_lines[i]["e"]
            if 0 < gap <= max_hold_cs:
                raw_lines[i]["e"] = raw_lines[i + 1]["s"]

    # Build ASS file
    ass = "[Script Info]\n"
    ass += "Title: Content Mate v2.2 Subtitles\n"
    ass += "ScriptType: v4.00+\n"
    ass += "PlayResX: 1080\n"
    ass += "PlayResY: 1920\n\n"
    ass += "[V4+ Styles]\n"
    ass += "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    ass += f"Style: Default,{FONT},{FONT_SIZE},&HFFFFFF,&H000000,&H000000,&H000000,10,0,0,0,100,100,0,0,1,3,2,8,10,10,{MARGIN_V},1\n\n"
    ass += "[Events]\n"
    ass += "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"

    for L in raw_lines:
        ass += f"Dialogue: 0,{cs_fmt(L['s'])},{cs_fmt(L['e'])},Default,,0,0,0,,{L['text']}\n"

    with open(output_path, "w") as f:
        f.write(ass)
    log(f"  Created subtitles: {len(raw_lines)} dialogue lines")


def burn_captions(video_path: str, ass_path: str, output_path: str) -> str:
    """Burn ASS subtitles into video. Copies ASS to /tmp to avoid path issues."""
    import shutil
    # Copy ASS and video to /tmp to avoid spaces in path breaking FFmpeg subtitle filter
    tmp_ass = f"/tmp/cm_subtitles_{os.path.basename(ass_path)}"
    tmp_video = f"/tmp/cm_input_{os.path.basename(video_path)}"
    tmp_output = f"/tmp/cm_output_{os.path.basename(output_path)}"

    shutil.copy2(ass_path, tmp_ass)
    shutil.copy2(video_path, tmp_video)

    cmd = [
        "ffmpeg", "-y",
        "-i", tmp_video,
        "-vf", f"subtitles='{tmp_ass}'",
        "-c:v", "libx264", "-c:a", "copy",
        tmp_output
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"  WARNING: Caption burn failed, copying video without captions")
        log(f"  FFmpeg error: {result.stderr[:300]}")
        shutil.copy2(video_path, output_path)
    else:
        shutil.copy2(tmp_output, output_path)
        log(f"  Burned captions successfully")

    # Clean up tmp files
    for f in [tmp_ass, tmp_video, tmp_output]:
        try:
            os.remove(f)
        except:
            pass

    return output_path


# ── Main Creator Pipeline ──────────────────────────────────────────────────

def run_creator(config: dict, idea_record_id: str = None):
    """Run the full creation pipeline for one idea."""
    at = AirtableClient(config)
    videos_dir = Path(config["videos_dir"])

    log("=== Creator: Starting ===")

    # Step 1: Pick idea
    idea = pick_idea(at, config, idea_record_id)
    if not idea:
        log("No ideas available. Run the scraper first.")
        return None

    idea_fields = idea.get("fields", {})
    is_broll = bool(idea_fields.get("Category"))
    idea_name = idea_fields.get("Name", idea_fields.get("Title", "unknown"))
    idea_link = idea_fields.get("Link", "")
    log(f"Selected: {idea_name}{' (B-Roll)' if is_broll else ''}")

    # Step 1b: Mark source as started
    if is_broll:
        broll_table = config.get("table_broll", "")
        if broll_table:
            at.update_record(broll_table, idea["id"], {"Status": "Used"})
    else:
        at.update_record(config["table_ideas"], idea["id"], {"Status": "video_started"})

    # Step 2: Pick random avatar and music (only those with video links)
    all_avatars = at.search_all(config["table_avatars"])
    avatars = [a for a in all_avatars if a.get("fields", {}).get("Avatar link")]
    all_musics = at.search_all(config["table_music"])
    musics = [m for m in all_musics if m.get("fields", {}).get("Music Link")]
    if not avatars:
        log("ERROR: No avatars found in Avatars table")
        return None
    if not musics:
        log("ERROR: No music found in Music table")
        return None

    avatar = random.choice(avatars)
    music = random.choice(musics)
    avatar_id = avatar["id"]
    music_id = music["id"]
    log(f"  Avatar: {avatar.get('fields', {}).get('Avatar Name', avatar_id)}")
    log(f"  Music: {music.get('fields', {}).get('Name', music_id)}")

    # Ensure avatar and music have permanent URLs
    avatar_url = ensure_avatar_url(at, config, avatar)
    music_url = ensure_music_url(at, config, music)
    log(f"  Avatar URL: {avatar_url[:60]}...")

    # Step 3: Create record in Create table
    create_record = at.create_record(config["table_create"], {
        "Name": idea_name,
        "Status": "Scripting",
        "Date Created": datetime.now().isoformat(),
        "Avatars": [avatar_id],
        "🎵 Music": [music_id],
    })
    record_id = create_record["id"]
    log(f"  Created record: {record_id}")

    # Step 4: Get video source
    xvideo_path = str(videos_dir / f"{record_id}_xvideo.mp4")
    
    if is_broll:
        log("--- Downloading B-Roll ---")
        download_broll_video(idea, xvideo_path)
        duration_sec = float(idea_fields.get("Duration (sec)", 30))
        tweet_text = ""
        author_name = ""
        research = ""
    else:
        log("--- Fetching tweet data ---")
        tweet = fetch_tweet(config, idea_link)
        tweet_text = tweet.get("text", "")
        author_name = tweet.get("author", {}).get("userName", "")
        media = tweet.get("extendedEntities", {}).get("media", [{}])[0]
        duration_ms = media.get("video_info", {}).get("duration_millis", 30000)
        duration_sec = duration_ms / 1000
        download_video(tweet, xvideo_path)
        log("--- Researching tweet ---")
        research = research_tweet(config, tweet_text, author_name)
        log(f"  Research: {len(research)} chars")

    # Step 5: Generate script
    log("--- Generating script ---")
    if is_broll:
        category = idea_fields.get("Category", "lifestyle")
        script = generate_testosterone_script(config, category, duration_sec)
    else:
        script = generate_script(config, tweet_text, research, duration_sec)
    log(f"  Script: {len(script.split())} words")

    # Update Airtable with script
    update_fields = {
        "Status": "Voice",
        "YT Short Script": script,
        "X Video (sec)": duration_sec,
    }
    if not is_broll:
        update_fields["X Video Link"] = idea_link
        update_fields["Source Text"] = tweet_text
        update_fields["Views"] = tweet.get("viewCount", 0) if 'tweet' in dir() else 0
    at.update_record(config["table_create"], record_id, update_fields)

    # Step 6: Generate voice
    log("--- Generating voice ---")
    # Re-fetch to get linked Voice ID field
    refreshed = at.get_record(config["table_create"], record_id)
    voice_id_links = refreshed.get("fields", {}).get("Voice ID Link", [])

    if not voice_id_links:
        log("ERROR: No Voice ID linked to avatar. Check Avatars table.")
        return None

    voice_id = voice_id_links[0] if isinstance(voice_id_links, list) else voice_id_links

    voice_full_path = str(videos_dir / f"{record_id}_voice_full.mp3")
    generate_voice(config, script, voice_id, voice_full_path)

    voice_3s_path = str(videos_dir / f"{record_id}_3s_voice.mp3")
    extract_3s_voice(voice_full_path, voice_3s_path)

    # Step 7: Avatar lipsync
    log("--- Creating avatar lipsync ---")
    at.update_record(config["table_create"], record_id, {"Status": "Avatar"})

    # Upload 3s voice to Replicate for URL (temporary is fine)
    voice_3s_url = upload_to_replicate(config, voice_3s_path)

    # Update Airtable with voice URL
    at.update_record(config["table_create"], record_id, {"Voiceover 3sec": voice_3s_url})

    # Run lipsync
    lipsync_output_url = create_lipsync(config, voice_3s_url, avatar_url)

    # Download lipsync result
    clone_path = str(videos_dir / f"{record_id}_clone.mp4")
    subprocess.run(["curl", "-s", "-L", "-o", clone_path, lipsync_output_url], check=True)
    log(f"  Downloaded lipsync video: {clone_path}")

    # Step 8: Combine videos
    log("--- Combining videos ---")
    at.update_record(config["table_create"], record_id, {"Status": "Combine Videos"})

    # Get crop top value
    refreshed = at.get_record(config["table_create"], record_id)
    crop_tops = refreshed.get("fields", {}).get("TopCrop", [0])
    crop_top = int(crop_tops[0]) if isinstance(crop_tops, list) and crop_tops else 0

    vertical_path = str(videos_dir / f"{record_id}_output_vertical.mp4")
    combine_avatar_and_source(xvideo_path, clone_path, vertical_path, crop_top)

    # Transform source to 9:16 with voice
    x9x16_path = str(videos_dir / f"{record_id}_xvideo_9x16.mp4")
    transform_to_9x16(xvideo_path, voice_full_path, x9x16_path)

    # Download and add music
    if music_url:
        music_path = str(videos_dir / f"{record_id}_music.mp3")
        subprocess.run(["curl", "-s", "-L", "-o", music_path, music_url], check=True)

        video_only_path = str(videos_dir / f"{record_id}_video_only.mp4")
        add_music_and_overlay(x9x16_path, vertical_path, music_path, video_only_path)
    else:
        log("WARNING: No music URL, skipping music")
        video_only_path = x9x16_path

    # Step 9: Captions (LOCAL WHISPER — no API cost)
    log("--- Adding captions (ElevenLabs Scribe) ---")
    at.update_record(config["table_create"], record_id, {"Status": "Caption"})

    words = transcribe_audio(config, voice_full_path)
    ass_path = str(videos_dir / f"{record_id}_subtitles.ass")
    create_ass_subtitles(words, ass_path)

    output_path = str(videos_dir / f"{record_id}_output.mp4")
    burn_captions(video_only_path, ass_path, output_path)

    # Step 10: Upload final video (public URL) and update to Review
    log("--- Uploading final video ---")
    video_url = upload_public(output_path)

    log("--- Setting status to Review ---")
    at.update_record(config["table_create"], record_id, {
        "Status": "Review",
        "Caption Drive": video_url,
        "Caption Video": [{"url": video_url}],
    })

    # Mark source as done
    if is_broll:
        broll_table = config.get("table_broll", "")
        if broll_table:
            at.update_record(broll_table, idea["id"], {"Status": "Used"})
    else:
        at.update_record(config["table_ideas"], idea["id"], {"Status": "video_done"})

    log(f"=== Creator: Done! Video ready at: {output_path} ===")
    log(f"    Record ID: {record_id}")
    log(f"    Change status to 'Schedule' in Airtable when ready to publish.")
    return record_id


if __name__ == "__main__":
    import sys
    from config import get_airtable_token, load_config

    token = get_airtable_token()
    cfg = load_config(token)

    idea_id = sys.argv[1] if len(sys.argv) > 1 else None
    run_creator(cfg, idea_id)
