#!/usr/bin/env python3
"""
B-Roll Creator with Music
Pipeline: Pexels → Script (Claude) → Text Overlay → Music → n8n → Platforms
"""

import json
import os
import random
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from airtable_utils import AirtableClient, api_request

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── Upload ───────────────────────────────────────────────────────────────────

def upload_public(file_path: str) -> str:
    # Try catbox.moe first
    result = subprocess.run(
        ["curl", "-s", "-F", "reqtype=fileupload",
         "-F", f"fileToUpload=@{file_path}",
         "https://catbox.moe/user/api.php"],
        capture_output=True, text=True
    )
    url = result.stdout.strip()
    if url.startswith("http"):
        log(f"  Uploaded to catbox: {url[:60]}...")
        return url

    # Fallback to litterbox (72h temporary storage)
    log(f"  catbox failed ({result.stdout.strip()[:80]}), trying litterbox...")
    result = subprocess.run(
        ["curl", "-s", "-F", "reqtype=fileupload", "-F", "time=72h",
         "-F", f"fileToUpload=@{file_path}",
         "https://litterbox.catbox.moe/resources/internals/api.php"],
        capture_output=True, text=True
    )
    url = result.stdout.strip()
    if url.startswith("http"):
        log(f"  Uploaded to litterbox: {url[:60]}...")
        return url

    raise RuntimeError(f"Upload failed on catbox and litterbox: {result.stdout[:200]}")


# ── Blotato ────────────────────────────────────────────────────────────────────

BLOTATO_BASE = "https://backend.blotato.com/v2"


def blotato_get(endpoint: str, api_key: str) -> dict:
    url = f"{BLOTATO_BASE}{endpoint}"
    req = subprocess.run(
        ["curl", "-s", "-H", f"blotato-api-key: {api_key}", url],
        capture_output=True, text=True
    )
    return json.loads(req.stdout)


def blotato_post(endpoint: str, api_key: str, data: dict) -> dict:
    url = f"{BLOTATO_BASE}{endpoint}"
    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         "-H", "Content-Type: application/json",
         "-H", f"blotato-api-key: {api_key}",
         "-d", json.dumps(data), url],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)


def post_to_blotato(api_key: str, account_id: str, platform: str, video_url: str, 
                    caption: str) -> str:
    if platform == "tiktok":
        payload = {
            "post": {
                "accountId": account_id,
                "content": {
                    "text": caption,
                    "mediaUrls": [video_url],
                    "platform": "tiktok"
                },
                "target": {
                    "targetType": "tiktok",
                    "privacyLevel": "PUBLIC_TO_EVERYONE",
                    "disabledComments": False,
                    "disabledDuet": False,
                    "disabledStitch": False,
                    "isBrandedContent": False,
                    "isYourBrand": True,
                    "isAiGenerated": False
                }
            }
        }
    elif platform == "instagram":
        payload = {
            "post": {
                "accountId": account_id,
                "content": {
                    "text": caption,
                    "mediaUrls": [video_url],
                    "platform": "instagram"
                },
                "target": {
                    "targetType": "instagram",
                    "mediaType": "reel",
                    "shareToFeed": True
                }
            }
        }
    else:
        raise ValueError(f"Unsupported platform: {platform}")
    
    result = blotato_post("/posts", api_key, payload)
    return result.get("postSubmissionId", "")


def get_blotato_accounts(api_key: str, platform: str = None) -> list:
    endpoint = "/users/me/accounts"
    if platform:
        endpoint += f"?platform={platform}"
    data = blotato_get(endpoint, api_key)
    return data.get("items", [])


def get_blotato_account_id(api_key: str, platform: str) -> str:
    """Get the first connected account ID for a platform."""
    accounts = get_blotato_accounts(api_key, platform)
    if accounts:
        return accounts[0].get("id", "")
    return ""


def post_to_platforms(config: dict, video_url: str, script: str,
                      platforms: list = None) -> dict:
    api_key = config.get("blotato_api_key", "")
    if not api_key:
        log("No Blotato API key - skipping social post")
        return {}
    
    if not platforms:
        platforms = []
        if config.get("instagram_account_id") or get_blotato_account_id(api_key, "instagram"):
            platforms.append("instagram")
        if config.get("tiktok_account_id") or get_blotato_account_id(api_key, "tiktok"):
            platforms.append("tiktok")
    
    results = {}
    for platform in platforms:
        account_id = config.get(f"{platform}_account_id") or get_blotato_account_id(api_key, platform)
        if not account_id:
            log(f"No {platform} account connected in Blotato")
            continue
        
        try:
            caption = generate_caption(script, platform)
            log(f"Posting to {platform}...")
            log(f"  Caption: {caption[:80]}...")
            post_id = post_to_blotato(api_key, account_id, platform, video_url, caption)
            results[platform] = post_id
            if post_id:
                log(f"  {platform} post submitted: {post_id[:20]}...")
            else:
                log(f"  {platform} post may have failed — no submission ID returned")
        except Exception as e:
            log(f"  {platform} post failed: {e}")
    
    return results


# ── Caption Generation ─────────────────────────────────────────────────────────

def generate_caption(script: str, platform: str) -> str:
    """Extract the caption from Claude's two-part output.
    If no ---CAPTION--- delimiter is found, falls back to building one from the on-screen text."""
    _, caption = parse_script_and_caption(script)
    
    if caption:
        # Caption was generated by Claude — use it directly
        # Add spacing for TikTok if missing
        if platform == "tiktok":
            # Ensure proper spacing between sections
            caption = caption.strip()
            if not caption.startswith("\n"):
                caption = "\n" + caption
            caption = caption[:2200]
        elif platform == "instagram":
            # Ensure hashtags are present; Claude should include them but just in case
            if "#" not in caption:
                caption += "\n\n#Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance"
            return caption[:2200]
        return caption[:2200]
    
    # Fallback: no caption section found — build from on-screen text
    on_screen = script.split("---CAPTION---")[0] if "---CAPTION---" in script else script
    clean_script = re.sub(r'\*\*', '', on_screen).strip()
    lines = [l.strip() for l in clean_script.split('\n') if l.strip()]
    
    if not lines:
        return "Optimize your testosterone naturally. Follow @rockmountainperformance"
    
    hook = lines[0].replace("HOOK:", "").strip()
    
    body_lines = []
    for line in lines[1:5]:
        line = re.sub(r'^(HOOK|BODY|CTA|INTRO|OUTRO|SCRIPT)\s*:?\s*', '', line, flags=re.IGNORECASE)
        if line and len(line) < 150:
            body_lines.append(line)
    
    # Build caption with proper spacing for both platforms
    if platform == "tiktok":
        caption = hook + "\n\n" + "\n\n".join(body_lines[:3]) + "\n\nFollow @rockmountainperformance\n\n#Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance"
    else:
        caption = hook + "\n\n"
        caption += "\n".join(body_lines[:3])
        caption += "\n\nFollow @rockmountainperformance for evidence-based testosterone content."
        caption += "\n\n#Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance"
    return caption[:2200]


# ── Script Generation (Claude AI) ─────────────────────────────────────────────

# Load viral examples for reference
from pathlib import Path
PROMPT_DIR = Path(__file__).resolve().parent

VIRAL_EXAMPLES = """
Here are examples of high-performing content for Rock Mountain Performance:

"""

viral_examples_path = PROMPT_DIR / "prompts" / "viral_examples.txt"
if viral_examples_path.exists():
    with open(viral_examples_path, "r") as f:
        VIRAL_EXAMPLES += f.read()

VIRAL_EXAMPLES += """

Use these examples as reference for style, tone, and format. Match the energy and structure of these successful posts.
"""


def get_recent_virals(at, table_id: str, limit: int = 5) -> list:
    """Fetch recent high-performing videos from Airtable for prompt learning."""
    if not table_id:
        return []
    try:
        records = at.search(table_id, max_records=limit, sort_field="Views", sort_dir="desc")
        return [r.get("fields", {}) for r in records if r.get("fields", {}).get("Script")]
    except Exception:
        return []


def build_dynamic_prompt(config: dict, at, target_sec: float = 30, category: str = "lifestyle") -> str:
    """Build the script prompt with recent viral examples for learning."""
    table_perf = config.get("table_performance", "")
    recent = get_recent_virals(at, table_perf, limit=3)

    prompt = TESTOSTERONE_SCRIPT_PROMPT.format(target_sec=target_sec, category=category)

    if recent:
        prompt += "\n\n--- RECENT WINNERS (use these as top reference) ---\n"
        for i, r in enumerate(recent, 1):
            script = r.get("Script", "")
            if script:
                prompt += f"\n{i}. {script[:500]}...\n"
        prompt += "\nMatch the style and hooks of these proven winners.\n"

    return prompt


TESTOSTERONE_SCRIPT_PROMPT = """You are a viral short-form content writer for Rock Mountain Performance (@rockmountainperformance), a transparent, research-aligned testosterone support brand for men who read labels and care what actually works.

BRAND IDENTITY:
- Brand essence: Built for men who verify.
- Brand promise: A testosterone support formula you can audit.
- Brand personality: Measured, credible, disciplined, direct.
- Brand tone: Clear, clinical-lite, masculine, skeptical, controlled. Not aggressive. Not macho for the sake of it. Not "alpha" language.
- Brand belief: Men deserve formulas they can evaluate, not marketing they have to trust blindly.
- Brand enemy: Underdosed, hidden, overclaimed formulas.
- Product: Peak Performance — research-backed, fully disclosed labels, batch tested, 30-day guarantee. Clinical doses of ingredients selected to support real hormonal function.
- The brand sounds like: "Read the label." / "Check the dose." / "Look at the mechanism." / "Judge the formula, not the claim."

SCIENTIFIC ACCURACY — NON-NEGOTIABLE:
Every factual claim must be grounded in real human research. Before writing any claim, ask: "Is there a peer-reviewed study that supports this in humans?" If not, do not write it.

REQUIRED:
- Only include claims supported by human clinical studies or well-established physiology
- When citing a number (e.g. "15% drop in T"), it must reflect real published research
- Use cautious language that matches the actual strength of evidence:
  - Strong evidence: "increases," "raises," "is linked to"
  - Moderate evidence: "may support," "is associated with," "research suggests"
  - Weak evidence: do not include at all
- Mechanisms must be physiologically accurate (e.g. aromatase converting T to estrogen is real; "seed oils spike cortisol" is not established — do not use it)

FORBIDDEN CLAIMS (these are bro-science myths — never use them):
- "Seed oils spike cortisol" or any claim that seed oils directly raise cortisol
- "Tap water destroys testosterone" (endocrine disruptors exist but this is overstated)
- "Intermittent fasting spikes testosterone" (evidence is weak and mixed)
- "Cold exposure raises testosterone" (evidence is very limited in humans)
- "Porn lowers testosterone" (no solid human evidence)
- "Garlic lowers cortisol" stated as fact — allicin/cortisol evidence is mostly animal studies; if used at all, must say "may" or "some research suggests"
- "Pomegranate blocks aromatase" — one small human study and in-vitro data only; must say "may inhibit" not "blocks"
- Any absolute claim like "floods your system with testosterone" or "destroys your hormones"
- Specific percentages or numbers you are not certain are from published research
- On-screen text making a stronger claim than the caption — both must use the same level of caution

WHAT IS WELL-SUPPORTED AND SAFE TO USE:
- Sleep deprivation reducing testosterone (well-studied — one week of 5h sleep linked to ~10-15% T reduction, Leproult & Van Cauter 2011)
- Zinc deficiency impairing testosterone production
- Vitamin D correlation with testosterone levels in deficient men
- Resistance training (especially compound lifts) acutely raising testosterone
- Obesity and excess body fat increasing aromatase activity (converting T to estrogen)
- Chronic stress and elevated cortisol suppressing testosterone
- Alcohol reducing testosterone synthesis
- Cholesterol being a precursor to steroid hormones including testosterone
- Selenium concentration in testicular tissue (well-established in physiology)

""" + VIRAL_EXAMPLES + """

ALLOWED THEMES (pick 1-2):
- Testosterone optimization and hormonal health (evidence-based only)
- Natural T-support: red meat, zinc, vitamin D, sleep, sunlight, cholesterol
- Heavy compound lifts and hormonal response (not generic gym tips)
- Diet for hormones: healthy fats, eggs, steak, nutrient density
- Sleep and recovery for testosterone production
- Avoiding endocrine disruptors (plastics, alcohol)
- Transparency in supplements — why most T-boosters fail (underdosed, proprietary blends, no evidence)
- Educated decision-making: reading labels, checking doses, understanding mechanisms
- Signs of high/low testosterone (relatable, list-based)
- Daily habits that raise or kill testosterone (evidence-backed only)

FORBIDDEN:
- Never mention competitors by name or handle
- Never use "primal," "viking," "alpha male," or "beef organs"
- Never mention generic protein powder or generic supplements
- Never use "Go to the gym" / generic fitness motivation
- Never use aggressive bro-science language or overclaimed statements
- Never use emojis in on-screen text
- Never make up statistics or cite numbers you are not confident are real

YOU MUST OUTPUT TWO SECTIONS separated by the exact delimiter ---CAPTION---

SECTION 1: ON-SCREEN TEXT
This is what viewers read on the video. Rules:
- Bold hook line first (mark with **HOOK:**)
- Then 3-8 short punchy lines or a numbered/bulleted list
- Each line MUST be under 50 characters
- Total: 4-8 lines max (including hook)
- Scannable in 3-5 seconds
- 6th grade reading level
- No hashtags, no emojis
- Claims must be cautious: "supports," "may increase," "is linked to" — not absolute
- Include 1-2 specific facts about hormones or biology
- Can use list format (numbered or bulleted) when appropriate
- End with a short CTA line like "Follow @rockmountainperformance" or "Comment TESTOSTERONE below"

SECTION 2: CAPTION (after ---CAPTION---)
This is the long-form caption posted below the video. Rules:
- 150-350 words
- Opens by restating or expanding the hook — pull the reader in
- Educates with specific, verifiable facts about testosterone, nutrition, or biology
- Ties the topic to hormonal health and why it matters
- Weaves in Peak Performance by @rockmountainperformance naturally (not a hard sell — position it as the logical next step for men who want research-backed support)
- Mentions what makes Peak Performance different: clinical doses, fully disclosed label, batch tested, no proprietary blends
- Ends with a clear CTA: "Comment [KEYWORD]" or "Follow @rockmountainperformance"
- Ends with a hashtag line: #Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance
- Tone: direct, educated, controlled, credible — like talking to a smart friend, not yelling at a crowd
- NO emojis

VIRAL FORMAT EXAMPLES (study the structure, tone, and rhythm — these are proven to perform):

---
ON-SCREEN:
For the next 3 months, do this challenge:

No porn
No alcohol
2-4 eggs/day
3 liters of water
6-7 hours of sleep
10,000+ steps/day
300+ push-ups daily
Cold water in the morning

Write 1,000 words daily

3 months. That is all it takes.

CAPTION:
FOLLOW US @rockmountainperformance and save this post for later

Three months. That is all it takes to engineer a massive glow up. But this isn't just a challenge; it is a war for your testosterone. You want real life gains? You need to strip away the weak habits and fuel your body with quality protein. This list is the ultimate hormonal reset button.

Cutting alcohol and porn isn't just about discipline; it is about hormonal protection. Eating eggs daily provides the cholesterol and protein needed to synthesize high testosterone. Without these building blocks, your efforts are wasted. Stick to this, and the physical glow up is inevitable.

Most men want the glow up without the grind. They skip the sleep, ignore their hormonal health, and wonder why their testosterone is tanking. Don't be them. Respect the protein.

Chase the gains. Use Peak Performance to maximize your testosterone.

Comment GAINS and I'll send you the full schedule.
#testosterone #glowup #gains #hormonal
---

---
ON-SCREEN:
16 SIGNS OF HIGH TESTOSTERONE

(If you score less than 6, you need to fix this)

Strong Morning Erections
High Sex Drive
Low Body Fat
Easy Muscle Growth
Deep Voice
Thick Beard Growth
Consistent Energy All Day
Sharp Mental Clarity
Strong Grip Strength
High Competitive Drive
Unshakeable Confidence
Fast Workout Recovery
Assertive Behavior
Strong Bones
Deep Quality Sleep
Calm Under Pressure

COMMENT TESTOSTERONE

CAPTION:
FOLLOW US @rockmountainperformance and save this post for later

Be honest, how many did you check off? If you scored less than 6, your testosterone is in the danger zone. You might be eating plenty of protein and hitting the gym, but you still aren't seeing gains. Why? Because without a solid hormonal foundation, your gains will never happen.

You feel stuck because your body is fighting you. Low testosterone kills your energy and destroys your gains. You can chug all the protein shakes you want, but if your hormonal health is off, you are spinning your wheels.

Stop making excuses. To unlock real gains, you need to optimize your hormonal balance. This is the only way your body will actually use that protein to build muscle.

Use Peak Performance to support your hormonal levels. Comment TESTOSTERONE and I'll send you the ultimate guide.
#testosterone #hormonal #protein #glowup
---

---
ON-SCREEN:
The Testosterone Doctrine

Sunlight increases testosterone.
Not eating increases testosterone.
Being lean increases testosterone.
More sleep increases testosterone.
Hot temperature increases testosterone.
Lifting heavy things increases testosterone.

Comment TESTOSTERONE

CAPTION:
FOLLOW US @rockmountainperformance and save this post for later

This is the code to unlock your genetic potential. You do not need a pharmacy; you need to align your lifestyle with your biology. Sunlight acts as a signal for your skin to produce Vitamin D, which is a steroid precursor essential for high testosterone.

Not eating refers to intermittent fasting which spikes Growth Hormone and resets insulin sensitivity. Being lean is critical because body fat contains an enzyme called aromatase which converts testosterone into estrogen.

Recovery is where the magic happens. More sleep is non negotiable because testosterone is manufactured during Deep and REM sleep cycles. Sauna exposure triggers heat shock proteins that repair damaged cells.

Finally Lifting heavy things provides the mechanical stress needed to upregulate androgen receptors. Use Peak Performance to amplify the results.

Comment TESTOSTERONE and I'll send you the keys on how to optimize naturally.
#testosterone #hormonal #protein #glowup #biology
---

---
ON-SCREEN:
Maximize Your TESTOSTERONE

Heavy Compound Lifts
Vitamin D3 + K2 (Sunlight)
Cold Exposure (Ice Baths)
Whole Eggs (Cholesterol)
Pomegranate Juice
Creatine Monohydrate
7-9 Hours Quality Sleep
Ginger and Garlic Intake
Minimize Alcohol
Competition / Winning Mindset
Avoid Phthalates
Steak / Red Meat

Comment TESTOSTERONE

CAPTION:
FOLLOW US @rockmountainperformance and save this post for later

Let's be real for a second. You are chasing that ultimate glow up, but you feel stuck. You're in the gym, but the gains aren't matching your effort. The missing link? It's usually your hormonal health.

Real men know that a true glow up isn't just about looks; it's about how you feel. High testosterone is the engine of your life. Without optimized testosterone, you're just spinning your wheels.

Stop looking for shortcuts. The only path to serious gains is discipline. Optimize your testosterone through habits and diet. Eat your protein. Fix your hormonal baseline.

The secret? It's hard work, good sleep, and the right supplementation. Use Peak Performance to fuel the man who is willing to do the work.

Comment TESTOSTERONE and I'll send you my personal guide on how to boost your levels naturally.
#testosterone #hormonal #protein #glowup
---

---
ON-SCREEN:
10 signs you have HIGH TESTOSTERONE

The Morning Salute is consistent
You carry all groceries in one trip
You don't get the 2 PM Slump
You pick the restaurant without hesitation
You recover fast from heavy leg day
Stress doesn't ruin your mood
You play to win (even in Uno)
You don't store fat on Love Handles
You possess a firm handshake
You hold eye contact naturally

FOLLOW US @rockmountainperformance

CAPTION:
It's time for a real glow up. If you've been chasing gains but feeling stuck, the answer might be hormonal. You can chug all the protein you want, but without optimized testosterone, you're just spinning your wheels.

We all want that glow up, right? To walk into the room with confidence and serious gains. But a hormonal imbalance can kill your progress.

Look at the signs in the slides. Do you relate? Real gains come from hard work and hormonal health. It's about discipline, eating high quality protein, and unlocking your natural testosterone potential.

The secret? There is no magic pill. It's heavy lifting, consistent protein, and taking Peak Performance to support your hormonal levels.

Comment TESTOSTERONE and I'll send you our exclusive guide!
#testosterone #glowup #gains
---

---
ON-SCREEN:
16 SIGNS YOU HAVE HIGH TESTOSTERONE

Morning wood
Hate being idle
You don't flinch
Humor is sharp
Crave confrontation
Calm under pressure
Hard work feels good
Multiple rounds is easy
Ice bath feels invigorating
Cuts heal quickly
High tolerance for spicy food
Unaffected by stress
Risk feels exciting
Sweat carries more scent
Movements are slower, more deliberate

If you're not following us, you will never see us again...

CAPTION:
Read that list again. How many can you honestly check off?

Be real. Do you wake up ready to take on the world, calm under pressure, and craving hard work? Or are you dragging, feeling irritable, and avoiding challenges?

Remember when you had that natural fire? That drive for real gains? That is what optimal hormonal health feels like. If you feel disconnected from the high testosterone man described in the image, your levels are likely crashed.

You can't fake high testosterone. You're stuck because your body lacks the raw materials. You probably aren't eating enough real protein.

But you can turn it around.

The solution is simple: hard work and prioritizing your biology. Use Peak Performance to support hormonal balance and maximize natural testosterone.

Click the link in bio to get started.
#testosterone #menshealth #glowup
---

---
ON-SCREEN:
10 Daily Habits Killing Your Testosterone

Sleeping like a vampire
Living off convenience foods
Zero sunlight, all screens
Chronic stress
Never lifting heavy
Drinking your calories
Fear of healthy fats
Being a Seat Warrior
Avoiding the cold
Constant digital stimulation

COMMENT TESTOSTERONE

CAPTION:
FOLLOW US @rockmountainperformance and save this post for later

1. Sleeping like a vampire
4 hours of sleep then wondering why you feel weak. T is made while you sleep, not while doom-scrolling at 2 AM.

2. Living off convenience foods
If your diet comes in a plastic wrapper, your hormones are crying. Real food = real gains.

3. Zero sunlight, all screens
You haven't seen the sun but your phone brightness is on max. Vitamin D is basically testosterone's best friend.

4. Chronic stress
Cortisol is a testosterone KILLER. If you're stressed 24/7, you are sabotaging your own masculinity.

5. Never lifting heavy
If everything you lift is light weight, your body has no reason to produce more T.

6. Drinking your calories
Beer and sugary sodas are estrogenic. Swap the liquid sugar for water.

7. Fear of healthy fats
Low fat = low T. Your body needs cholesterol to synthesize hormones. Eat the eggs.

8. Being a Seat Warrior
Sitting for 10 hours a day kills circulation and lowers testosterone.

9. Avoiding the cold
Brief cold exposure lowers inflammation and resets your nervous system.

10. Constant digital stimulation
Always being on keeps your brain in a high-beta state. Disconnect to recharge.

Use Peak Performance to armor your endocrine system.

Comment TESTOSTERONE and I'll send you my private guide on the top 5 habits to naturally boost your levels.
#testosterone #glowup #protein #gains
---

---
ON-SCREEN:
10 habits that ACTUALLY increase testosterone

I lift heavy compound weights 4x per week
I prioritize 8 hours of deep sleep
I devour massive amounts of red meat
I get morning sunlight in my eyes
I avoid seed oils and processed sugars
I hydrate with sea salt
I take Peak Performance daily
I walk 10,000 steps a day
I manage my stress levels
I eat whole eggs with the yolk

Comment TESTOSTERONE

CAPTION:
FOLLOW US @rockmountainperformance and save this post for later

I spent years figuring out what actually works and narrowed it down to ten daily habits that naturally spike testosterone.

I lift heavy compound weights four times a week to force my body to build dense muscle.
I prioritize eight hours of deep sleep to completely reset my internal hormonal baseline.
I devour massive amounts of red meat to get the raw protein required for absolute power.
I get morning sunlight in my eyes to regulate my circadian rhythm and protect my gains.
I completely avoid seed oils and processed sugars because they destroy my hormonal health.
I hydrate with sea salt to ensure every gram of protein reaches my cells.
I take Peak Performance daily to armor my endocrine system and naturally elevate my testosterone.
I walk ten thousand steps a day to stay lean and reveal my hard earned muscle.
I manage my stress levels to prevent cortisol from eating away at my physical gains.
I eat whole eggs with the yolk to give my body the cholesterol it needs to manufacture more testosterone.

Executing these habits guarantees my hormonal profile stays elite. I refuse to compromise my biology.

Comment TESTOSTERONE and I will send you the keys on how to become the man you were meant to be.
#testosterone #hormonal #protein #gains #muscle
---

---
ON-SCREEN:
Your testosterone is CRASHING if you:

Sleep less than 7 hours
Eat seed oils daily
Skip leg day
Don't get sunlight
Live in chronic stress
Drink alcohol regularly
Avoid red meat
Sit too much

You need to fix this NOW.

FOLLOW US @rockmountainperformance

CAPTION:
Your testosterone is crashing if you do any of these things. I see men destroying their hormones every single day without even knowing it.

Sleep is when your body manufactures testosterone. Less than 7 hours? You're literally leaving gains on the table.

Seed oils are estrogenic nightmares. They spike your cortisol and crash your T. Stop cooking with soybean oil.

Skipping leg day means missing the biggest hormonal stimulus your body can get. Squats and deadlifts flood your system with testosterone.

No sunlight means no Vitamin D. And Vitamin D is a steroid precursor essential for T production.

Chronic stress? Cortisol and testosterone compete. High cortisol = low testosterone. Simple as that.

Alcohol destroys your hormonal health. Every drink is hurting your gains.

Red meat provides the cholesterol and zinc your body needs to synthesize testosterone. Stop avoiding it.

Sitting all day kills your circulation and tanks your T. Stand up more.

Use Peak Performance to support your hormonal baseline while you fix these habits.

Comment T and I'll send you the protocol.
#testosterone #glowup #hormonal
---

---
ON-SCREEN:
Stop doing these 5 things:

1. Eating chicken breast only
2. Running for cardio
3. Taking pre-workout
4. Skipping breakfast
5. Drinking tap water

Your testosterone will thank you.

FOLLOW US @rockmountainperformance

CAPTION:
FOLLOW US @rockmountainperformance and save this post for later

1. EATING CHICKEN BREAST ONLY
Chicken breast has less zinc and cholesterol than red meat. Your T needs cholesterol to be manufactured. Eat the steak.

2. RUNNING FOR CARDIO
Long steady-state cardio can lower testosterone. Sprint intervals and heavy lifting are better for hormonal health.

3. TAKING PRE-WORKOUT
Most pre-workouts are loaded with caffeine and artificial ingredients that spike cortisol. Train fasted or with black coffee.

4. SKIPPING BREAKFAST
Intermittent fasting can boost T, but skipping breakfast AND training fasted can spike cortisol too much. Eat some protein.

5. DRINKING TAP WATER
Tap water contains endocrine-disrupting chemicals. Filter your water or drink spring water.

Use Peak Performance to fill the gaps in your hormonal support protocol.

Comment T and I'll send you my top 5 T-boosting tips.
#testosterone #hormonal #glowup #protein
---


Target: ~{target_sec:.0f} seconds of on-screen content for the video.
Write ONE complete output for a {category} video. Start immediately with the on-screen text."""


FACT_CHECK_PROMPT = """You are a scientific fact-checker for health and testosterone content. Your job is to review a short-form video script and fix any claims that are not supported by peer-reviewed human clinical research.

REVIEW PROCESS:
1. Read every factual claim in both the on-screen text and the caption
2. For each claim, ask: "Is this supported by human clinical studies?"
3. Fix any claim that is overstated, based only on animal studies, or unsubstantiated

COMMON ISSUES TO CATCH AND FIX:
- Absolute language ("raises testosterone", "destroys hormones") when evidence is moderate → soften to "may support", "is associated with", "research suggests"
- Garlic/allicin lowering cortisol stated as fact → animal studies only, must say "some research suggests may lower cortisol"
- Pomegranate "blocking" aromatase → one small study, must say "may help inhibit"
- Cold exposure raising testosterone → very limited human evidence, remove or heavily hedge
- Specific numbers or percentages that aren't from real published studies → remove or replace with hedged language
- On-screen text making a stronger claim than the caption → both must match in caution level

OUTPUT RULES — STRICT:
- You must respond with ONLY one of two things — nothing else, no commentary, no explanation, no preamble:
  1. The single word APPROVED (if every claim is scientifically sound)
  2. The complete corrected script starting immediately with the on-screen text (if any fixes were needed)
- Do NOT write anything like "The script is largely sound" or "Here is the corrected version" or any other sentence before or after your output
- Do NOT explain what you changed
- Your entire response must be either the word APPROVED or the raw script text"""


def fact_check_script(client, script: str) -> str:
    """Run the generated script through a second Claude call for scientific accuracy.
    Returns the original script if approved, or a corrected version if fixes were needed."""
    log("  Fact-checking script for scientific accuracy...")
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=FACT_CHECK_PROMPT,
            messages=[
                {"role": "user", "content": f"Fact-check this script:\n\n{script}"}
            ]
        )
        result = response.content[0].text.strip()
        if result == "APPROVED" or result.upper().startswith("APPROVED"):
            log("  Fact-check: APPROVED — all claims are scientifically sound")
            return script
        # If the result contains ---CAPTION--- it's a valid corrected script
        if "---CAPTION---" in result:
            # Strip any leading commentary before the script starts
            if "**" in result:
                result = result[result.index("**"):]
            log("  Fact-check: corrections made — using revised script")
            return result
        # Fallback: fact-checker returned something unexpected, keep original
        log(f"  Fact-check returned unexpected format — keeping original script")
        return script
    except Exception as e:
        log(f"  Fact-check failed ({e}) — using original script")
        return script


def parse_script_and_caption(raw_response: str) -> tuple:
    """Parse Claude's two-part response into (on_screen_text, caption).
    The response is split on the ---CAPTION--- delimiter."""
    if "---CAPTION---" in raw_response:
        parts = raw_response.split("---CAPTION---", 1)
        on_screen = parts[0].strip()
        caption = parts[1].strip()
    else:
        # Fallback: treat entire response as on-screen text, no caption
        on_screen = raw_response.strip()
        caption = ""
    return on_screen, caption


def generate_script(config: dict, category: str, duration_sec: float, at=None) -> str:
    """Generate on-screen text + caption using Claude. Returns the full raw response
    containing both sections separated by ---CAPTION---."""
    target_sec = min(duration_sec, 45)

    api_key = config.get("anthropic_api_key", "")
    if not api_key:
        log("  WARNING: No Claude API key found - will use mock script")

    # Build dynamic prompt with recent viral examples if available
    system_prompt = TESTOSTERONE_SCRIPT_PROMPT.format(target_sec=target_sec, category=category)
    if at and config.get("table_performance"):
        system_prompt = build_dynamic_prompt(config, at, target_sec=target_sec, category=category)
        log(f"  Using dynamic prompt with recent viral examples")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        log(f"  Calling Claude API (claude-sonnet-4-6)...")
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"Write a powerful testosterone-focused script for a {category} video."}
            ]
        )
        log(f"  SUCCESS: Claude generated script")
        script = response.content[0].text
        script = fact_check_script(client, script)
        return script
    except Exception as e:
        log(f"  Claude API failed ({e}), using mock script")
        mock_scripts = {
            "food": (
                "**HOOK:** Stop eating chicken. Your testosterone depends on it.\n\n"
                "Red meat supports testosterone production.\n"
                "Beef contains zinc, creatine, and saturated fat.\n"
                "These are building blocks your body uses to make T.\n"
                "Stop avoiding the foods that built strong men.\n\n"
                "Follow @rockmountainperformance\n\n"
                "---CAPTION---\n\n"
                "FOLLOW @rockmountainperformance and save this post for later\n\n"
                "Red meat is one of the most testosterone-supporting foods available. "
                "Beef provides zinc, saturated fat, and creatine — all directly involved in hormonal health. "
                "Most men are undereating the exact nutrients their endocrine system needs.\n\n"
                "That is why we built Peak Performance. Every ingredient is clinically dosed. "
                "Every dose is disclosed on the label. No proprietary blends. No guessing.\n\n"
                "Comment TESTOSTERONE below.\n\n"
                "#Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance"
            ),
            "workout": (
                "**HOOK:** Your testosterone is starving. Go heavy.\n\n"
                "Heavy compound lifts trigger a hormonal response.\n"
                "Deadlifts and squats release testosterone.\n"
                "Your legs contain the largest muscle groups.\n"
                "Lift heavy. Recover hard. Repeat.\n\n"
                "Follow @rockmountainperformance\n\n"
                "---CAPTION---\n\n"
                "FOLLOW @rockmountainperformance and save this post for later\n\n"
                "Heavy compound lifts create a hormonal response that isolation exercises cannot match. "
                "Deadlifts, squats, and presses signal your body to produce more testosterone. "
                "But training is only half the equation. Recovery and proper supplementation matter.\n\n"
                "Peak Performance is built with clinical doses and a fully disclosed label. "
                "Every batch is tested. No proprietary blends.\n\n"
                "Comment TESTOSTERONE below.\n\n"
                "#Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance"
            ),
            "lifestyle": (
                "**HOOK:** You are destroying your testosterone every night.\n\n"
                "Sleep deprivation may cut T levels by 15%.\n"
                "Morning sunlight supports testosterone production.\n"
                "Cold exposure helps maintain hormonal balance.\n"
                "Fix your habits. Fix your hormones.\n\n"
                "Follow @rockmountainperformance\n\n"
                "---CAPTION---\n\n"
                "FOLLOW @rockmountainperformance and save this post for later\n\n"
                "Sleep is when your body produces the most testosterone. "
                "One week of sleeping 5 hours is linked to a 15% drop in T levels. "
                "Morning sunlight exposure supports vitamin D production, which is directly tied to testosterone.\n\n"
                "Peak Performance was built for men who verify. Clinical doses. Disclosed labels. Batch tested.\n\n"
                "Comment TESTOSTERONE below.\n\n"
                "#Testosterone #MensHealth #HormonalHealth #PeakPerformance #RockMountainPerformance"
            ),
        }
        return mock_scripts.get(category, mock_scripts["lifestyle"])


# ── Text Overlay (Captions) ───────────────────────────────────────────────────

def add_captions(video_path: str, script: str, output_path: str) -> str:
    log("  Adding captions...")
    
    total_duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    ).stdout.strip())
    
    clean_script = script.replace("#", "").replace("*", "").replace("_", " ").strip()
    
    import re
    clean_script = re.sub(r'\b(HOOK|BODY|CTA|INTRO|OUTRO|SCRIPT)\s*:', '', clean_script, flags=re.IGNORECASE).strip()
    
    parts = clean_script.split('\n')
    lines = []
    
    hook_line = parts[0].strip() if parts else ""
    lines.append(hook_line)
    lines.append("")
    
    if len(parts) > 1:
        for part in parts[1:]:
            part = part.strip()
            if part:
                lines.append(part)
    
    lines = lines[:10]
    
    cta_lines = []
    other_lines = []
    for line in lines:
        if "comment" in line.lower() or "follow @" in line.lower() or "save this" in line.lower():
            cta_lines.append(line)
        else:
            other_lines.append(line)
    
    lines = other_lines + [""] + cta_lines
    full_text = "\\N".join(lines)
    
    log(f"  Adding static text overlay ({len(lines)} lines)")
    
    def fmt_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int((sec % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    
    ass = "[Script Info]\n"
    ass += "Title: Static Captions\n"
    ass += "ScriptType: v4.00+\n"
    ass += "PlayResX: 1080\n"
    ass += "PlayResY: 1920\n\n"
    ass += "[V4+ Styles]\n"
    ass += "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    ass += "Style: Default,Roboto,44,&H00FFFFFF,&H000000,&H000000,&H000000,-1,0,0,0,100,100,3,0,1,4,0,5,40,40,950,1\n\n"
    ass += "[Events]\n"
    ass += "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    ass += f"Dialogue: 0,0:00:00.00,{fmt_time(total_duration - 0.5)},Default,,40,40,950,,{full_text}\n"
    
    ass_path = output_path.replace(".mp4", ".ass")
    with open(ass_path, "w") as f:
        f.write(ass)
    
    videos_dir = os.path.dirname(video_path)
    video_name = os.path.basename(video_path)
    ass_name = os.path.basename(ass_path)
    output_name = os.path.basename(output_path)
    
    cmd = ["ffmpeg", "-y", "-i", video_name, "-vf", f"ass={ass_name}", "-c:a", "copy", output_name]
    result = subprocess.run(cmd, cwd=videos_dir, capture_output=True, text=True)
    
    try:
        os.remove(ass_path)
    except:
        pass
    
    if result.returncode != 0:
        log(f"  Caption failed")
        subprocess.run(["copy", video_path, output_path], shell=True)
    else:
        log("  Captions added!")
    
    return output_path


# ── Music from Airtable ───────────────────────────────────────────────────────

def get_random_music(at: AirtableClient, table_id: str):
    """Pick random music from Music table."""
    records = at.search_all(table_id)
    if not records:
        return None
    return random.choice(records)


def download_music(music: dict, output_path: str) -> str:
    """Download music file from Music table."""
    fields = music.get("fields", {})
    
    # Try Music Link (Google Drive URL)
    music_url = fields.get("Music Link", "")
    
    # Try attachment URL
    attachments = fields.get("Music mp3", [])
    if attachments and isinstance(attachments, list):
        music_url = attachments[0].get("url", "")
    
    if not music_url:
        return None
    
    subprocess.run(["curl", "-s", "-L", "-o", str(output_path), music_url], check=True)
    log(f"  Downloaded music: {output_path}")
    return output_path


def combine_video_music(video_path: str, music_path: str, output_path: str) -> str:
    """Mix video audio with background music."""
    log("  Adding music...")
    
    # Check if video has audio
    check = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", video_path],
        capture_output=True, text=True
    )
    has_audio = "audio" in check.stdout.strip().lower()
    
    if has_audio:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", music_path,
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.15[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]
    else:
        log("  Video has no audio - using music as audio")
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", music_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"  Music mix failed: {result.stderr[:100]}")
        subprocess.run(["copy", video_path, output_path], shell=True)
    else:
        log("  Music added successfully")
    
    return output_path


# ── Pexels Download ─────────────────────────────────────────────────────────

PEXELS_SEARCH_TERMS = {
    "workout": ["gym workout", "weightlifting", "man exercising", "fitness training"],
    "food": ["healthy food", "steak dinner", "grilled meat", "protein meal"],
    "lifestyle": ["sunrise", "coffee", "strong man", "nutrition"],
}


def search_pexels(api_key, query, per_page=3):
    import urllib.parse
    params = urllib.parse.urlencode({'query': query, 'per_page': per_page, 'orientation': 'portrait'})
    url = f"https://api.pexels.com/videos/search?{params}"
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: {api_key}", url],
        capture_output=True, text=True
    )
    return json.loads(result.stdout).get("videos", [])


def download_pexels_video(api_key, video_id, output_path):
    output_path = Path(output_path)
    if output_path.exists():
        log(f"  Video already exists: {output_path.name}")
        return str(output_path)
    
    url = f"https://api.pexels.com/videos/videos/{video_id}"
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: {api_key}", url],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    
    video_files = data.get("video_files", [])
    mp4s = [v for v in video_files if v.get("file_type") == "video/mp4"]
    if not mp4s:
        raise RuntimeError(f"No mp4 files found for Pexels video {video_id} (API returned: {list(data.keys())})")
    
    def is_4x5(v):
        w, h = v.get("width", 0), v.get("height", 0)
        if w == 0 or h == 0:
            return False
        ratio = w / h
        return 0.75 <= ratio <= 0.85
    
    def duration_ok(v):
        dur = v.get("duration", 999)
        return 15 <= dur <= 35
    
    four_by_five = [v for v in mp4s if is_4x5(v) and duration_ok(v)]
    if four_by_five:
        four_by_five.sort(key=lambda v: v.get("width", 0) * v.get("height", 0), reverse=True)
        video_url = four_by_five[0].get("link")
    else:
        in_range = [v for v in mp4s if duration_ok(v)]
        if in_range:
            in_range.sort(key=lambda v: v.get("width", 0) * v.get("height", 0), reverse=True)
            video_url = in_range[0].get("link")
        else:
            mp4s.sort(key=lambda v: v.get("width", 0) * v.get("height", 0), reverse=True)
            video_url = mp4s[0].get("link")
    
    subprocess.run(["curl", "-s", "-L", "-o", str(output_path), video_url], check=True)
    return output_path


# ── Main Pipeline ────────────────────────────────────────────────────────────

def run_creator(config: dict, category: str = None):
    at = AirtableClient(config)
    videos_dir = Path(config["videos_dir"])
    videos_dir.mkdir(exist_ok=True)
    
    log("=== B-Roll Creator: Starting ===")
    
    pexels_key = config.get("pexels_api_key", "")
    if not pexels_key:
        log("ERROR: No Pexels API key")
        return None
    
    # Step 1: Pick category
    if not category:
        category = random.choice(list(PEXELS_SEARCH_TERMS.keys()))
    log(f"Category: {category}")
    
    # Step 2: Search Pexels with multiple related terms for better match
    log("--- Searching Pexels ---")
    search_terms = PEXELS_SEARCH_TERMS.get(category, PEXELS_SEARCH_TERMS["lifestyle"])
    
    # Try each search term until we find good videos
    all_videos = []
    for term in search_terms[:3]:  # Try first 3 terms
        log(f"  Trying search: {term}")
        videos = search_pexels(pexels_key, term, per_page=10)
        if videos:
            all_videos.extend(videos)
    
    if not all_videos:
        log("No videos found")
        return None
    
    # Get used video IDs from Airtable to avoid duplicates
    used_ids = set()
    try:
        existing = at.search(config["table_create"], max_records=100)
        for rec in existing:
            fields = rec.get("fields", {})
            video_url = fields.get("Video URL", "")
            if "pexels" in video_url.lower() and "video" in video_url:
                parts = video_url.strip("/").split("/")
                if parts and parts[-1].isdigit():
                    used_ids.add(parts[-1])
    except Exception as e:
        log(f"  Could not fetch used videos: {e}")
    
    videos = all_videos
    
    # Score and sort videos by quality
    def score_video(v):
        # Prefer duration between 15-30 seconds (ideal for short-form)
        dur = v.get("duration", 999)
        dur_score = 100 if 15 <= dur <= 30 else (50 if 10 <= dur <= 40 else 20)
        
        # Prefer 4x5 (9:16) portrait orientation
        w, h = v.get("width", 0), v.get("height", 0)
        if w and h:
            ratio = w / h
            ratio_score = 100 if 0.75 <= ratio <= 0.85 else 50
            quality_score = w * h  # Higher resolution is better
        else:
            ratio_score = 50
            quality_score = 0
        
        return dur_score + ratio_score + (quality_score // 10000)
    
    # Sort by score (best first)
    videos.sort(key=score_video, reverse=True)
    log(f"  Found {len(videos)} videos, top scored: {videos[0].get('duration')}s, {videos[0].get('width')}x{videos[0].get('height')}")
    
    # Filter out already used videos
    available = [v for v in videos if str(v.get("id")) not in used_ids]
    if not available:
        log("All found videos already used, trying any video")
        available = videos
    
    video = random.choice(available)
    video_id = video.get("id")
    duration = video.get("duration", 30)
    log(f"Found: {video_id} ({duration}s) [used: {len(used_ids)} already]")
    
    # Step 3: Get random music
    log("--- Getting music ---")
    music_table = config.get("table_music", "")
    music = get_random_music(at, music_table) if music_table else None
    music_name = music.get("fields", {}).get("Name", "No music") if music else "No music"
    log(f"Music: {music_name}")
    
    # Step 4: Create Airtable record
    log("--- Creating record ---")
    create_record = at.create_record(config["table_create"], {
        "Name": f"{category.title()} - {datetime.now().strftime('%m/%d %H:%M')}",
        "Status": "Review",
        "Category": category,
    })
    record_id = create_record["id"]
    
    # Step 5: Generate script (on-screen text + caption)
    log("--- Generating script ---")
    full_script = generate_script(config, category, duration, at)
    on_screen_text, caption_text = parse_script_and_caption(full_script)
    log(f"  On-screen: {on_screen_text[:60]}...")
    if caption_text:
        log(f"  Caption: {caption_text[:60]}...")
    
    at.update_record(config["table_create"], record_id, {
        "Script": full_script,
    })
    
    # Step 6: Download video
    log("--- Downloading video ---")
    video_path = str(videos_dir / f"{record_id}_pexels.mp4")
    try:
        download_pexels_video(pexels_key, video_id, video_path)
    except Exception as e:
        log(f"ERROR: Video download failed: {e}")
        try:
            at.update_record(config["table_create"], record_id, {"Status": "Error - Download failed"})
        except Exception:
            pass
        return None

    # Step 7: Add captions (on-screen text only — not the long caption)
    log("--- Adding captions ---")
    captioned_path = str(videos_dir / f"{record_id}_captioned.mp4")
    try:
        add_captions(video_path, on_screen_text, captioned_path)
    except Exception as e:
        log(f"ERROR: Caption step failed: {e}")
        try:
            at.update_record(config["table_create"], record_id, {"Status": "Error - Caption failed"})
        except Exception:
            pass
        return None

    # Step 8: Add music
    if music:
        music_path = str(videos_dir / f"{record_id}_music.mp3")
        download_music(music, music_path)
        output_path = str(videos_dir / f"{record_id}_output.mp4")
        combine_video_music(captioned_path, music_path, output_path)
    else:
        output_path = captioned_path

    # Step 9: Upload
    log("--- Uploading ---")
    try:
        video_url = upload_public(output_path)
    except Exception as e:
        log(f"ERROR: Upload failed: {e}")
        try:
            at.update_record(config["table_create"], record_id, {"Status": "Error - Upload failed"})
        except Exception:
            pass
        return None

    at.update_record(config["table_create"], record_id, {
        "Video URL": video_url,
    })

    # Step 10: Post to platforms (pass full_script so caption can be extracted)
    platforms = config.get("auto_post_platforms", "").split(",") if config.get("auto_post_platforms") else []
    if platforms:
        log("--- Posting to platforms ---")
        post_to_platforms(config, video_url, full_script, [p.strip() for p in platforms])
    
    # Step 11: Log to performance table for learning
    if config.get("table_performance"):
        try:
            at.create_record(config["table_performance"], {
                "Script": full_script,
                "Video URL": video_url,
                "Pexels ID": str(video_id),
                "Category": category,
                "Views": 0,
                "Likes": 0,
                "Status": "New",
            })
            log("  Saved to performance table for learning")
        except Exception as e:
            log(f"  Could not save to performance table: {e}")
    
    log(f"=== Done! ===")
    log(f"    Record: {record_id}")
    log(f"    Video: {video_url}")
    if platforms:
        log(f"    Posted to: {', '.join(platforms)}")
    else:
        log(f"    Status: Review - Approve in Airtable")
    
    return record_id


def rerun_from_record(config: dict, record_id: str):
    """Regenerate video from existing record's script."""
    at = AirtableClient(config)
    videos_dir = Path(config["videos_dir"])
    videos_dir.mkdir(exist_ok=True)
    
    log(f"=== Rerun from record: {record_id} ===")
    
    record = at.get_record(config["table_create"], record_id)
    if not record:
        log(f"ERROR: Record not found: {record_id}")
        return None
    
    fields = record.get("fields", {})
    full_script = fields.get("Script", "")
    category = fields.get("Category", "lifestyle")
    
    if not full_script:
        log(f"ERROR: No script found in record")
        return None
    
    on_screen_text, caption_text = parse_script_and_caption(full_script)
    log(f"  On-screen: {on_screen_text[:60]}...")
    
    pexels_key = config.get("pexels_api_key", "")
    if not pexels_key:
        log("ERROR: No Pexels API key")
        return None
    
    search_terms = PEXELS_SEARCH_TERMS.get(category, PEXELS_SEARCH_TERMS["lifestyle"])
    search_term = random.choice(search_terms)
    log(f"  Search: {search_term}")
    
    videos = search_pexels(pexels_key, search_term, per_page=3)
    if not videos:
        log("No videos found")
        return None
    
    video = random.choice(videos)
    video_id = video.get("id")
    duration = video.get("duration", 30)
    log(f"  Video: {video_id} ({duration}s)")
    
    log("--- Creating new record ---")
    create_record = at.create_record(config["table_create"], {
        "Name": f"{category.title()} - RERUN {datetime.now().strftime('%m/%d %H:%M')}",
        "Status": "Review",
        "Category": category,
        "Script": full_script,
    })
    new_record_id = create_record["id"]
    
    log("--- Downloading video ---")
    video_path = str(videos_dir / f"{new_record_id}_pexels.mp4")
    try:
        download_pexels_video(pexels_key, video_id, video_path)
    except Exception as e:
        log(f"ERROR: Video download failed: {e}")
        try:
            at.update_record(config["table_create"], new_record_id, {"Status": "Error - Download failed"})
        except Exception:
            pass
        return None

    log("--- Adding captions ---")
    captioned_path = str(videos_dir / f"{new_record_id}_captioned.mp4")
    try:
        add_captions(video_path, on_screen_text, captioned_path)
    except Exception as e:
        log(f"ERROR: Caption step failed: {e}")
        try:
            at.update_record(config["table_create"], new_record_id, {"Status": "Error - Caption failed"})
        except Exception:
            pass
        return None

    music_table = config.get("table_music", "")
    music = get_random_music(at, music_table) if music_table else None
    if music:
        music_path = str(videos_dir / f"{new_record_id}_music.mp3")
        download_music(music, music_path)
        output_path = str(videos_dir / f"{new_record_id}_output.mp4")
        combine_video_music(captioned_path, music_path, output_path)
    else:
        output_path = captioned_path

    log("--- Uploading ---")
    try:
        video_url = upload_public(output_path)
    except Exception as e:
        log(f"ERROR: Upload failed: {e}")
        try:
            at.update_record(config["table_create"], new_record_id, {"Status": "Error - Upload failed"})
        except Exception:
            pass
        return None
    
    at.update_record(config["table_create"], new_record_id, {
        "Video URL": video_url,
    })
    
    platforms = config.get("auto_post_platforms", "").split(",") if config.get("auto_post_platforms") else []
    if platforms:
        log("--- Posting to platforms ---")
        post_to_platforms(config, video_url, full_script, [p.strip() for p in platforms])
    
    log(f"=== Done! ===")
    log(f"    Record: {new_record_id}")
    log(f"    Video: {video_url}")
    if platforms:
        log(f"    Posted to: {', '.join(platforms)}")
    
    return new_record_id


if __name__ == "__main__":
    import sys
    from config import get_airtable_token, load_config, get_blotato_api_key, get_env_var
    
    token = get_airtable_token()
    cfg = load_config(token)
    # Override Airtable values with env vars only when the env var is actually set
    blotato_key = get_blotato_api_key()
    if blotato_key:
        cfg["blotato_api_key"] = blotato_key
    instagram_id = get_env_var("BLOTATO_INSTAGRAM_ACCOUNT_ID")
    if instagram_id:
        cfg["instagram_account_id"] = instagram_id
    tiktok_id = get_env_var("BLOTATO_TIKTOK_ACCOUNT_ID")
    if tiktok_id:
        cfg["tiktok_account_id"] = tiktok_id
    auto_post = get_env_var("AUTO_POST_PLATFORMS")
    if auto_post:
        cfg["auto_post_platforms"] = auto_post
    
    args = sys.argv[1:]
    if len(args) == 1 and args[0].startswith("rec"):
        rerun_from_record(cfg, args[0])
    else:
        category = args[0] if args else None
        run_creator(cfg, category)
