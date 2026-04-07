# Content Mate v2.2 — Setup Guide

Get your AI clone shorts pipeline running in under 30 minutes. No coding experience needed.

---

## Step 1: Install Claude Code

If you don't have it yet:
```bash
npm install -g @anthropic-ai/claude-code
```

Then open Claude Code in your terminal:
```bash
claude
```

Tell Claude: "Help me set up Content Mate v2.2"

Claude will walk you through everything below. You can paste this entire guide into Claude and it will do each step for you.

---

## Step 2: Install FFmpeg

**Mac:**
```bash
brew tap homebrew-ffmpeg/ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg
```

This installs FFmpeg with libass (needed for captions). If you already have FFmpeg, you may need to uninstall it first:
```bash
brew uninstall --ignore-dependencies ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg
```

**Verify it works:**
```bash
ffmpeg -filters 2>&1 | grep subtitles
```
You should see: `subtitles  V->V  Render text subtitles onto input video using the libass library.`

---

## Step 3: Install Python Dependencies

```bash
pip3 install certifi
```

That's it. Everything else uses Python's built-in libraries.

---

## Step 4: Download Content Mate v2.2

Download these files from the Skool community and put them in a folder on your computer:

```
content_mate_v2.2/
├── content_mate.py
├── config.py
├── airtable_utils.py
├── scraper.py
├── creator.py
├── publisher.py
└── videos/          (create this empty folder)
```

---

## Step 5: Duplicate the Airtable Base

1. Go to the Content Mate v2.2 Airtable template (link in Skool)
2. Click "Duplicate base" in the top right
3. Your new base will have these tables:
   - **X** — Twitter handles to scrape
   - **Ideas** — Scraped tweet ideas with scores
   - **Create** — Video production pipeline
   - **Avatars** — Your AI clone videos
   - **Music** — Background music tracks
   - **Setup** — All your API keys and config

---

## Step 6: Get Your API Keys

You need 5 API keys. Here's where to get each one:

### OpenAI API Key
1. Go to platform.openai.com
2. Click API Keys → Create new secret key
3. Copy it

### ElevenLabs API Key
1. Go to elevenlabs.io → Profile → API Keys
2. Copy your API key

### Replicate API Token
1. Go to replicate.com → Account → API tokens
2. Copy your token

### Blotato API Key
1. Go to blotato.com → Settings → API
2. Copy your API key
3. Connect your social media accounts in Blotato (YouTube, TikTok, Instagram, Facebook, X, LinkedIn, Bluesky, Threads, Pinterest)
4. Note each account ID from the Blotato dashboard

### TwitterAPI.io Key
1. Go to twitterapi.io
2. Sign up and get your API key
3. Costs about $5-10/month

---

## Step 7: Fill in the Setup Table

Open your Airtable base → Setup table. Fill in ONE row with:

| Field | Value |
|-------|-------|
| Config Name | Your name |
| Active | ON |
| Airtable Base ID | Your base ID (from the URL: airtable.com/YOUR_BASE_ID/...) |
| Airtable Personal Token | Your Airtable personal access token (airtable.com/create/tokens) |
| Table Create ID | Copy from your Create table URL |
| Table Ideas ID | Copy from your Ideas table URL |
| Table X ID | Copy from your X table URL |
| Table Avatars ID | Copy from your Avatars table URL |
| Table Music ID | Copy from your Music table URL |
| OpenAI API Key | From Step 6 |
| ElevenLabs API Key | From Step 6 |
| Replicate API Token | From Step 6 |
| Blotato API Key | From Step 6 |
| TwitterAPI Key | From Step 6 |
| YouTube Account ID | From Blotato |
| Instagram Account ID | From Blotato |
| TikTok Account ID | From Blotato |
| Facebook Account ID | From Blotato |
| X Account ID | From Blotato |
| LinkedIn Account ID | From Blotato |
| Bluesky Account ID | From Blotato |
| Threads Account ID | From Blotato |
| Pinterest Account ID | From Blotato |
| Telegram Access Token | Optional — for notifications |
| Telegram Chat ID | Optional — for notifications |

**How to find table IDs:** Open each table in Airtable. The URL looks like: `airtable.com/appXXXXX/tblYYYYY`. The `tblYYYYY` part is the table ID.

---

## Step 8: Create a Local .env File

In your content_mate_v2.2 folder, create a file called `.env` with one line:

```
AIRTABLE_PERSONAL_ACCESS_TOKEN=patXXXXXXXXXXXXXXXX
```

This is the only thing stored locally. Everything else comes from the Airtable Setup table.

---

## Step 9: Set Up Your Avatar

You need a 5-second video of yourself (or your AI clone) for the lipsync avatar.

1. Record or generate a 5-second vertical video of you looking at the camera
2. Upload it to the Avatars table in Airtable (Avatar Image field)
3. Add your ElevenLabs Voice ID to the Voice ID field
4. The system will handle the rest

---

## Step 10: Add X Handles to Scrape

Go to the X table and add Twitter handles you want to scrape for ideas. Examples:
- @claudeai
- @OpenAI
- @GoogleDeepMind
- @runwayml
- Any accounts that post viral AI content with videos

---

## Step 11: Add Background Music

Upload 3-5 MP3 tracks to the Music table. These get randomly assigned to each video.

---

## Step 12: Test It

```bash
cd content_mate_v2.2

# Check everything is connected
python3 content_mate.py status

# Scrape ideas
python3 content_mate.py scrape

# Create your first video
python3 content_mate.py create

# Check Airtable — your video should be in Review status
# Watch it, then change status to "Schedule" if you like it

# Publish
python3 content_mate.py publish
```

---

## Step 13: Run Daily (Optional)

To run automatically every day, set up a cron job:

```bash
crontab -e
```

Add these lines (adjust times to your timezone):
```
# Scrape new ideas at 7 AM
0 7 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py scrape

# Create 5 videos at 8 AM (every 5 minutes, one at a time)
0 8 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py create
5 8 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py create
10 8 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py create
15 8 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py create
20 8 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py create

# Publish scheduled videos 5x/day
0 9 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py publish
0 14 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py publish
0 18 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py publish
0 22 * * * cd /path/to/content_mate_v2.2 && python3 content_mate.py publish
```

---

## Troubleshooting

**"No ideas available"** — Run `scrape` first, then check that your X handles table has handles listed.

**"No avatars found"** — Add at least one avatar to the Avatars table with a video link and Voice ID.

**"Caption burn failed"** — Your FFmpeg doesn't have libass. Reinstall with `brew install homebrew-ffmpeg/ffmpeg/ffmpeg`.

**"403 Forbidden" on scraping** — Check your TwitterAPI.io key in the Setup table.

**Videos aren't publishing** — Check your Blotato API key and account IDs in the Setup table. Make sure accounts are connected in Blotato.

---

## Costs

| Service | Cost | What it does |
|---------|------|-------------|
| OpenAI | ~$0.05/video | Script generation (O3) + research + captions |
| ElevenLabs | ~$0.03/video | Voice clone + transcription |
| Replicate | ~$0.05/video | Avatar lipsync (PixVerse) |
| Blotato | $29/month | Publish to 9 platforms |
| TwitterAPI.io | $5-10/month | X/Twitter scraping |
| **Total** | ~$0.13/video + $35-40/month | |

At 5 videos/day = ~$0.65/day in API costs + $35-40/month for subscriptions.
