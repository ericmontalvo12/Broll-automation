# Content Mate v2.2

AI clone shorts pipeline that scrapes viral content, writes scripts, generates voiceovers, creates avatar videos with lipsync, adds captions, and publishes to 9 platforms. Runs entirely on your computer. No n8n, no Docker, no VPS.

## What It Does

Every day it:
1. Scrapes 33+ X/Twitter accounts for viral video tweets
2. Scores each idea (Source Score 0-8) to find winners
3. Picks the best unused idea (20K+ views, horizontal video, 10-200 seconds)
4. Researches the topic (GPT-4o-mini-search)
5. Writes a script matched to the source video length (O3, 2.4 words/sec)
6. Generates voiceover with your cloned voice (ElevenLabs)
7. Creates lipsync avatar video (PixVerse via Replicate)
8. Combines source video + avatar + background music (FFmpeg)
9. Burns word-by-word captions with cyan highlight (ElevenLabs Scribe + FFmpeg)
10. Uploads to Airtable for review (approve or deny)
11. Publishes approved videos to 9 platforms via Blotato
12. Sends Telegram notification with stats

## Commands

```bash
python3 content_mate.py scrape              # Scrape X handles for new ideas
python3 content_mate.py create              # Create one video from best idea
python3 content_mate.py create <idea_id>    # Create from specific idea
python3 content_mate.py publish             # Publish all "Schedule" videos
python3 content_mate.py auto --count 5      # Full pipeline: scrape + create 5 + publish
python3 content_mate.py status              # Show pipeline status
```

## How You Use It

1. Run `scrape` to pull fresh ideas
2. Run `create` to make videos (they land in Airtable as "Review")
3. Open Airtable, watch the video, change status to "Schedule" (approve) or "No" (deny)
4. Run `publish` to push approved videos to all 9 platforms

Or just run `auto` and it does everything.

## Platforms

YouTube Shorts, TikTok, Instagram Reels, Facebook Reels, X/Twitter, LinkedIn, Bluesky, Threads, Pinterest

## Files

| File | What it does |
|------|-------------|
| `content_mate.py` | Main CLI entry point |
| `config.py` | Reads config from Airtable Setup table |
| `airtable_utils.py` | Airtable API client |
| `scraper.py` | X/Twitter scraping |
| `creator.py` | Full video creation pipeline |
| `publisher.py` | 9-platform publishing via Blotato |
| `videos/` | Local video storage |

## Requirements

- Python 3.12+
- FFmpeg with libass (for captions)
- certifi (`pip install certifi`)
- faster-whisper (`pip install faster-whisper`) — optional, for local captions

## API Keys Needed

All stored in your Airtable Setup table:
- OpenAI API key (script generation)
- ElevenLabs API key (voice + captions)
- Replicate API token (avatar lipsync)
- Blotato API key (9-platform publishing)
- TwitterAPI.io key (X scraping)
- Telegram token + chat ID (notifications, optional)
