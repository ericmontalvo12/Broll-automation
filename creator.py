#!/usr/bin/env python3
"""
Content Mate v2.2 — Creator Module
Simplified pipeline: Idea → Download → Script → 9:16 → Music → Captions → Review

Each step updates Airtable status so you can see progress.
"""

import json
import os
import random
import subprocess
from datetime import datetime
from pathlib import Path
from airtable_utils import AirtableClient, api_request


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── File Upload ──────────────────────────────────────────────────────────────

def upload_public(file_path: str) -> str:
    """Upload a file and return a public URL."""
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
    log(f"  Uploaded: {filename} → {url}")
    return url


# ── Pick Idea ────────────────────────────────────────────────────────────────

def pick_idea(at: AirtableClient, config: dict, idea_record_id: str = None) -> dict:
    """Pick the best unprocessed idea, or a specific one."""
    if idea_record_id:
        return at.get_record(config["table_ideas"], idea_record_id)

    # Find ideas with Source=Instagram, high views, unused
    formula = "AND({Source}='Instagram', {Status}='')"
    records = at.search(
        config["table_ideas"],
        formula=formula,
        sort_field="Views",
        sort_dir="desc",
        max_records=1
    )
    if records:
        f = records[0].get("fields", {})
        log(f"  Selected: {f.get('Name', '?')} - {f.get('Views', 0):,} views")
        return records[0]

    # Fallback: any unused idea
    formula = "{Status}=''"
    records = at.search(
        config["table_ideas"],
        formula=formula,
        sort_field="Views",
        sort_dir="desc",
        max_records=1
    )
    if records:
        return records[0]

    log("No ideas found. Run scrape-ig first.")
    return None


# ── Download Video ───────────────────────────────────────────────────────────

def download_video(video_url: str, output_path: str) -> str:
    """Download video from URL."""
    subprocess.run(["curl", "-s", "-L", "-o", output_path, video_url], check=True)
    log(f"  Downloaded: {output_path}")
    return output_path


# ── OCR Text Extraction ──────────────────────────────────────────────────────

def extract_onscreen_text(video_path: str) -> str:
    """Extract on-screen text from video using OCR."""
    from video_ocr import extract_text_from_video

    log("  Running OCR on video...")
    result = extract_text_from_video(video_path, fps=0.5)

    if "error" in result:
        log(f"  OCR error: {result['error']}")
        return ""

    # Get unique lines of text found
    unique_lines = result.get("unique_lines", [])
    hook = result.get("hook", "")

    log(f"  Found {len(unique_lines)} text segments")
    if hook:
        log(f"  Hook: {hook[:50]}...")

    # Join all unique text
    return "\n".join(unique_lines)


# ── Video Processing (FFmpeg) ────────────────────────────────────────────────

def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip() or 30)


def transform_to_9x16(source_video: str, output_path: str) -> str:
    """Transform video to 9:16 vertical format, keeping original audio."""
    cmd = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:v", "libx264", "-c:a", "aac",
        "-movflags", "+faststart",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    log(f"  Transformed to 9:16: {output_path}")
    return output_path


def add_background_music(video_path: str, music_path: str, output_path: str) -> str:
    """Add background music to video (lowered volume)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        "[0:a]volume=1.0[a0];[1:a]volume=0.15[a1];[a0][a1]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac",
        "-movflags", "+faststart",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    log(f"  Added music: {output_path}")
    return output_path


# ── Captions ─────────────────────────────────────────────────────────────────

def transcribe_audio(config: dict, video_path: str) -> list:
    """Transcribe audio using ElevenLabs Scribe. Returns word-level timestamps."""
    # Extract audio from video
    audio_path = video_path.replace(".mp4", "_audio.mp3")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "mp3", audio_path
    ], capture_output=True)

    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         "https://api.elevenlabs.io/v1/speech-to-text",
         "-H", f"xi-api-key: {config['elevenlabs_api_key']}",
         "-H", "Accept: application/json",
         "-F", "model_id=scribe_v1",
         "-F", "language_code=en",
         "-F", f"file=@{audio_path}"],
        capture_output=True, text=True
    )

    # Cleanup audio file
    if os.path.exists(audio_path):
        os.remove(audio_path)

    data = json.loads(result.stdout)
    words = []
    for w in data.get("words", []):
        if str(w.get("type", "")).lower() != "word":
            continue
        words.append({
            "word": str(w.get("text", "")),
            "start": float(w.get("start", 0)),
            "end": float(w.get("end", 0))
        })

    log(f"  Transcribed {len(words)} words")
    return words


def create_ass_subtitles(words: list, output_path: str):
    """Create ASS subtitle file from word-level timestamps."""
    if not words:
        log("  WARNING: No words for subtitles")
        return

    WORDS_TO_SHOW = 3
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

    # Fix zero-duration words
    for w in words:
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + 0.08

    # Create groups
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

    # Build ASS file
    ass = "[Script Info]\n"
    ass += "Title: Content Mate Subtitles\n"
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
    log(f"  Created subtitles: {len(raw_lines)} lines")


def burn_captions(video_path: str, ass_path: str, output_path: str) -> str:
    """Burn ASS subtitles into video."""
    import shutil

    # Copy to temp to avoid path issues
    tmp_ass = f"/tmp/cm_subtitles.ass"
    tmp_video = f"/tmp/cm_input.mp4"
    tmp_output = f"/tmp/cm_output.mp4"

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
        log(f"  Caption burn failed, using video without captions")
        shutil.copy2(video_path, output_path)
    else:
        shutil.copy2(tmp_output, output_path)
        log(f"  Burned captions")

    # Cleanup
    for f in [tmp_ass, tmp_video, tmp_output]:
        try:
            os.remove(f)
        except:
            pass

    return output_path


# ── Main Creator Pipeline ────────────────────────────────────────────────────

def run_creator(config: dict, idea_record_id: str = None):
    """Run the simplified creation pipeline for one idea."""
    at = AirtableClient(config)
    videos_dir = Path(config["videos_dir"])

    log("=== Creator: Starting ===")

    # Step 1: Pick idea
    idea = pick_idea(at, config, idea_record_id)
    if not idea:
        return None

    idea_fields = idea.get("fields", {})
    idea_name = idea_fields.get("Name", "unknown")
    caption = idea_fields.get("Text", "")
    video_url = idea_fields.get("Video URL", "")

    if not video_url:
        log(f"ERROR: No video URL for idea {idea_name}")
        return None

    log(f"Selected: {idea_name}")

    # Mark as started
    at.update_record(config["table_ideas"], idea["id"], {"Status": "processing"})

    # Step 2: Create record in Create table
    create_record = at.create_record(config["table_create"], {
        "Name": idea_name,
        "Status": "Downloading",
        "Date Created": datetime.now().isoformat(),
    })
    record_id = create_record["id"]
    log(f"  Created record: {record_id}")

    # Step 3: Download video
    log("--- Downloading video ---")
    source_path = str(videos_dir / f"{record_id}_source.mp4")
    download_video(video_url, source_path)
    duration_sec = get_video_duration(source_path)
    log(f"  Duration: {duration_sec:.1f}s")

    # Step 4: Extract on-screen text from competitor video (OCR)
    log("--- Extracting on-screen text ---")
    at.update_record(config["table_create"], record_id, {"Status": "OCR"})
    onscreen_text = extract_onscreen_text(source_path)

    # Store both: on-screen text (for video captions) and IG caption (for post)
    at.update_record(config["table_create"], record_id, {
        "YT Short Script": onscreen_text,  # On-screen text from OCR
        "Source Text": caption,             # Competitor's IG caption for publishing
    })
    log(f"  On-screen text: {len(onscreen_text)} chars")
    log(f"  IG caption: {len(caption)} chars")

    # Step 5: Transform to 9:16
    log("--- Transforming to 9:16 ---")
    at.update_record(config["table_create"], record_id, {"Status": "Processing"})
    vertical_path = str(videos_dir / f"{record_id}_vertical.mp4")
    transform_to_9x16(source_path, vertical_path)

    # Step 6: Add background music (optional)
    music_url = config.get("default_music_url", "")
    if music_url:
        log("--- Adding music ---")
        music_path = str(videos_dir / f"{record_id}_music.mp3")
        subprocess.run(["curl", "-s", "-L", "-o", music_path, music_url], check=True)
        with_music_path = str(videos_dir / f"{record_id}_with_music.mp4")
        add_background_music(vertical_path, music_path, with_music_path)
        video_for_captions = with_music_path
    else:
        video_for_captions = vertical_path

    # Step 7: Captions
    log("--- Adding captions ---")
    at.update_record(config["table_create"], record_id, {"Status": "Caption"})
    words = transcribe_audio(config, video_for_captions)
    ass_path = str(videos_dir / f"{record_id}_subtitles.ass")
    create_ass_subtitles(words, ass_path)

    output_path = str(videos_dir / f"{record_id}_output.mp4")
    burn_captions(video_for_captions, ass_path, output_path)

    # Step 8: Upload and set to Review
    log("--- Uploading ---")
    video_url = upload_public(output_path)

    at.update_record(config["table_create"], record_id, {
        "Status": "Review",
        "Caption Drive": video_url,
        "Caption Video": [{"url": video_url}],
    })

    # Mark source idea as done
    at.update_record(config["table_ideas"], idea["id"], {"Status": "video_done"})

    log(f"=== Creator: Done! ===")
    log(f"    Record ID: {record_id}")
    log(f"    Video URL: {video_url}")
    return record_id


if __name__ == "__main__":
    import sys
    from config import get_airtable_token, load_config

    token = get_airtable_token()
    cfg = load_config(token)

    idea_id = sys.argv[1] if len(sys.argv) > 1 else None
    run_creator(cfg, idea_id)
