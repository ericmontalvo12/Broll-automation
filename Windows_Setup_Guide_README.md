# Content Mate v2.2 — Windows Setup Guide

This guide covers what you need to do manually to get Content Mate running on Windows. It assumes you are using Claude Code to handle the automated steps.

---

## Step 1: Install FFmpeg

Open a terminal and run:

```bash
winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
```

This installs FFmpeg 8.1 (full build with libass for caption burning). The install adds FFmpeg to your PATH, but you need to **restart your terminal** for the PATH change to take effect.

To verify it worked after restarting:

```bash
ffmpeg -filters 2>&1 | findstr subtitles
```

You should see a line mentioning `libass`.

---

## Step 2: Install Python Dependency

```bash
pip install certifi
```

That is the only external Python package required. Everything else uses Python's built-in libraries.

---

## Step 3: Duplicate the Airtable Base

1. Open the Content Mate v2.2 Airtable template link (provided in Skool)
2. Click **Duplicate base** in the top-right corner
3. Your duplicated base will contain these tables: **X**, **Ideas**, **Create**, **Avatars**, **Music**, **Setup**

---

## Step 4: Get Your API Keys

You need accounts and API keys from these 5 services:

| Service | Where to get the key |
|---------|----------------------|
| **OpenAI** | platform.openai.com → API Keys → Create new secret key |
| **ElevenLabs** | elevenlabs.io → Profile → API Keys |
| **Replicate** | replicate.com → Account → API Tokens |
| **TwitterAPI.io** | twitterapi.io → sign up → copy API key (~$5-10/month) |
| **Blotato** | blotato.com → Settings → API (connect your social accounts here too) |

**ElevenLabs:** make sure you copy the full API key. It should be a long string starting with `sk_`. A truncated key will cause 401 errors.

---

## Step 5: Fill In the Airtable Setup Table

Open your duplicated Airtable base and go to the **Setup** table. Fill in one row with all of the following:

| Field | Value |
|-------|-------|
| Config Name | Your name |
| Active | ON (checkbox) |
| Airtable Base ID | From your base URL: `airtable.com/YOUR_BASE_ID/...` |
| Airtable Personal Token | From airtable.com/create/tokens |
| Table Create ID | From the Create table URL: the `tblXXXXX` part |
| Table Ideas ID | From the Ideas table URL |
| Table X ID | From the X table URL |
| Table Avatars ID | From the Avatars table URL |
| Table Music ID | From the Music table URL |
| OpenAI API Key | From Step 4 |
| ElevenLabs API Key | From Step 4 — paste the full key |
| Replicate API Token | From Step 4 |
| TwitterAPI Key | From Step 4 |
| Blotato API Key | From Step 4 |
| YouTube Account ID | From your Blotato dashboard |
| Instagram Account ID | From your Blotato dashboard |
| TikTok Account ID | From your Blotato dashboard |
| Facebook Account ID | From your Blotato dashboard |
| X Account ID | From your Blotato dashboard |
| LinkedIn Account ID | From your Blotato dashboard |
| Bluesky Account ID | From your Blotato dashboard |
| Threads Account ID | From your Blotato dashboard |
| Pinterest Account ID | From your Blotato dashboard |
| Telegram Access Token | Optional — for publish notifications |
| Telegram Chat ID | Optional — for publish notifications |

**How to find table IDs:** Click on each table in Airtable. The URL looks like `airtable.com/appXXXXX/tblYYYYY/...` — the `tblYYYYY` part is the table ID.

---

## Step 6: Create the .env File

In the `content_mate_v2.2` folder, create a file called `.env` with this single line:

```
AIRTABLE_PERSONAL_ACCESS_TOKEN=patXXXXXXXXXXXXXXXX
```

Replace the value with your actual Airtable personal access token (the same one you put in the Setup table). This is the only credential stored locally — everything else is read from Airtable.

---

## Step 7: Add Your Avatar

1. Go to the **Avatars** table in your Airtable base
2. Create a row and fill in:
   - **Avatar Name** — any label
   - **4s Vertical Vid** — upload a short vertical video of yourself (or your AI clone) looking at the camera. A few seconds is enough.
   - **Voice ID** — your ElevenLabs Voice ID (find it at elevenlabs.io → Voices → your voice → ID)

---

## Step 8: Add Twitter Handles to Scrape

Go to the **X** table and add Twitter handles you want to scrape for ideas. One handle per row in the **Handle** field (without the @). Examples: `claudeai`, `runwayml`, `GoogleDeepMind`.

---

## Step 9: Add Background Music

Go to the **Music** table and upload 3–5 MP3 tracks in the **Music mp3** field. These are randomly assigned to each video during creation.

---

## Step 10: Run the Pipeline

All commands must be run from inside the `content_mate_v2.2` folder. On Windows, always prefix with `PYTHONUTF8=1` to avoid character encoding errors:

```bash
# Check everything is connected
PYTHONUTF8=1 python3 content_mate.py status

# Scrape ideas from your X handles
PYTHONUTF8=1 python3 content_mate.py scrape

# Create a video from the best available idea
PYTHONUTF8=1 python3 content_mate.py create

# Create from a specific idea (get the ID from the Ideas table URL)
PYTHONUTF8=1 python3 content_mate.py create recXXXXXXXXXX

# Publish all videos with Status = "Schedule"
PYTHONUTF8=1 python3 content_mate.py publish
```

---

## Step 11: Review and Approve Videos

After running `create`, go to the **Create** table in Airtable. Your video will appear with status **Review** and a video attachment. Watch it, then:

- Change status to **Schedule** to approve it for publishing
- Change status to **No** to discard it

Then run `publish` to push all scheduled videos to your connected platforms.

---

## Step 12: Automate (Optional)

To run the pipeline automatically every day, open Task Scheduler on Windows and create a task that runs:

```
python3 C:\path\to\content_mate_v2.2\content_mate.py auto
```

Or use Git Bash with a cron job — set `PYTHONUTF8=1` in the environment before calling the script.

---

## Costs

| Service | Cost | What it does |
|---------|------|-------------|
| OpenAI | ~$0.05/video | Script generation + research |
| ElevenLabs | ~$0.03/video | Voice clone + transcription |
| Replicate | ~$0.05/video | Avatar lipsync |
| Blotato | $29/month | Publish to 9 platforms |
| TwitterAPI.io | $5–10/month | X/Twitter scraping |
| **Total** | ~$0.13/video + $35–40/month | |

---

## Troubleshooting (Windows-Specific)

**`UnicodeEncodeError` in terminal output**
Always run commands with `PYTHONUTF8=1` prefix.

**`ffmpeg` not found after install**
Restart your terminal. Winget adds FFmpeg to PATH but the current session won't pick it up until restarted. The scripts handle this automatically once Claude Code has set up the path fallback.

**ElevenLabs 401 Unauthorized**
Your API key in the Airtable Setup table is likely truncated. Go back to elevenlabs.io, copy the full key again, and paste it fresh into the Setup table.

**TwitterAPI 403 Forbidden**
The API key is being blocked by Cloudflare. This was fixed in the code — make sure you are using the updated `scraper.py` from this repo.

**"No active config found in Setup table"**
The **Active** checkbox in your Setup table row is not ticked. Open the Setup table and turn it on.

**"No avatars found" / "No music found"**
The code looks for attachments in the `4s Vertical Vid` field (Avatars table) and `Music mp3` field (Music table). Make sure files are uploaded directly to those fields, not linked externally.
