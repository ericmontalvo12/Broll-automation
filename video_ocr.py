#!/usr/bin/env python3
"""
Content Mate v2.2 — Video OCR Module
Extracts on-screen text from videos using OpenCV + pytesseract.

Use this to analyze competitor videos and extract their hooks,
captions, and on-screen text for inspiration.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

try:
    import cv2
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def check_dependencies():
    """Check if OCR dependencies are installed."""
    if not HAS_OCR:
        log("ERROR: OCR dependencies not installed. Run:")
        log("  pip install opencv-python pytesseract Pillow")
        log("  Also install Tesseract OCR:")
        log("    Windows: choco install tesseract")
        log("    Mac: brew install tesseract")
        log("    Linux: sudo apt install tesseract-ocr")
        return False
    return True


def extract_frames(video_path: str, output_dir: str, fps: float = 1.0) -> list:
    """Extract frames from video at specified FPS."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Use ffmpeg to extract frames
    output_pattern = os.path.join(output_dir, "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "2",
        output_pattern
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # Get list of extracted frames
    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    log(f"  Extracted {len(frames)} frames")
    return [str(f) for f in frames]


def preprocess_frame(frame_path: str) -> "Image":
    """Preprocess frame for better OCR accuracy."""
    img = cv2.imread(frame_path)

    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Apply threshold to get black and white image (better for text)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    # Also try inverted (white text on dark background is common)
    _, thresh_inv = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)

    return Image.fromarray(thresh), Image.fromarray(thresh_inv)


def extract_text_from_frame(frame_path: str) -> str:
    """Extract text from a single frame using OCR."""
    if not HAS_OCR:
        return ""

    try:
        # Try both normal and inverted preprocessing
        img_normal, img_inverted = preprocess_frame(frame_path)

        # OCR config for better accuracy on video text
        custom_config = r'--oem 3 --psm 6'

        text_normal = pytesseract.image_to_string(img_normal, config=custom_config)
        text_inverted = pytesseract.image_to_string(img_inverted, config=custom_config)

        # Return whichever has more content
        return text_normal if len(text_normal) >= len(text_inverted) else text_inverted

    except Exception as e:
        log(f"  OCR failed on frame: {e}")
        return ""


def clean_text(text: str) -> str:
    """Clean extracted OCR text."""
    # Remove excessive whitespace
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # Filter out very short lines (likely noise)
    lines = [line for line in lines if len(line) > 2]

    return '\n'.join(lines)


def extract_text_from_video(video_path: str, fps: float = 0.5) -> dict:
    """Extract all on-screen text from a video.

    Args:
        video_path: Path to the video file
        fps: Frames per second to sample (default 0.5 = every 2 seconds)

    Returns:
        dict with 'all_text', 'unique_lines', 'hook' (first significant text)
    """
    if not check_dependencies():
        return {"error": "OCR dependencies not installed"}

    log(f"Analyzing video: {video_path}")

    # Create temp directory for frames
    video_name = Path(video_path).stem
    temp_dir = Path(video_path).parent / f"_ocr_frames_{video_name}"

    try:
        # Extract frames
        frames = extract_frames(video_path, str(temp_dir), fps)

        all_text = []
        unique_lines = set()

        for i, frame_path in enumerate(frames):
            text = extract_text_from_frame(frame_path)
            cleaned = clean_text(text)

            if cleaned:
                all_text.append({
                    "frame": i + 1,
                    "timestamp": f"{(i / fps):.1f}s",
                    "text": cleaned
                })

                for line in cleaned.split('\n'):
                    if line.strip():
                        unique_lines.add(line.strip())

        log(f"  Found {len(unique_lines)} unique text segments")

        # Get the hook (first significant text, likely in first 3 seconds)
        hook = ""
        for entry in all_text:
            if entry["text"]:
                hook = entry["text"].split('\n')[0]
                break

        return {
            "all_text": all_text,
            "unique_lines": list(unique_lines),
            "hook": hook,
            "total_frames": len(frames),
            "text_frames": len(all_text)
        }

    finally:
        # Cleanup temp frames
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def analyze_competitor_video(video_url: str, config: dict = None) -> dict:
    """Download and analyze a competitor video."""
    from pathlib import Path

    videos_dir = Path(config.get("videos_dir", "videos")) if config else Path("videos")
    videos_dir.mkdir(exist_ok=True)

    # Download video
    temp_path = str(videos_dir / f"_analyze_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")

    log(f"Downloading video...")
    subprocess.run(["curl", "-s", "-L", "-o", temp_path, video_url], check=True)

    try:
        result = extract_text_from_video(temp_path)
        return result
    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)


def batch_analyze_videos(video_paths: list) -> list:
    """Analyze multiple videos and return combined results."""
    results = []
    for path in video_paths:
        log(f"\n--- Analyzing: {path} ---")
        result = extract_text_from_video(path)
        result["video"] = path
        results.append(result)
    return results


def print_analysis(result: dict):
    """Pretty print video analysis results."""
    print("\n" + "="*60)
    print("VIDEO ANALYSIS RESULTS")
    print("="*60)

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"\nHOOK (First on-screen text):")
    print(f"  {result.get('hook', 'None found')}")

    print(f"\nUNIQUE TEXT FOUND ({len(result.get('unique_lines', []))} segments):")
    for i, line in enumerate(result.get('unique_lines', [])[:10], 1):
        print(f"  {i}. {line}")

    if len(result.get('unique_lines', [])) > 10:
        print(f"  ... and {len(result['unique_lines']) - 10} more")

    print(f"\nSTATS:")
    print(f"  Total frames analyzed: {result.get('total_frames', 0)}")
    print(f"  Frames with text: {result.get('text_frames', 0)}")
    print("="*60)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python video_ocr.py <video_path_or_url>")
        print("\nExamples:")
        print("  python video_ocr.py ./videos/competitor.mp4")
        print("  python video_ocr.py https://example.com/video.mp4")
        sys.exit(1)

    video_input = sys.argv[1]

    if video_input.startswith("http"):
        from config import get_airtable_token, load_config
        token = get_airtable_token()
        cfg = load_config(token)
        result = analyze_competitor_video(video_input, cfg)
    else:
        result = extract_text_from_video(video_input)

    print_analysis(result)
