#!/usr/bin/env python3
"""
Scrape trending Reddit posts and adapt them into viral YouTube Shorts scripts.
Uses Reddit JSON API (free, no key) + Groq for adaptation.
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import random
import time

GROQ_MODEL = "llama-3.3-70b-versatile"
BROWSER_UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds


def _call_groq(groq_api_key: str, prompt: str, temperature: float = 0.85) -> dict:
    """Call Groq API with retry logic. Returns parsed JSON or None."""
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }).encode()

    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
                "User-Agent": BROWSER_UA,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode())
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            print(f"  [WARN] Groq attempt {attempt}/{MAX_RETRIES} failed: {e}",
                  file=sys.stderr)
            if attempt < MAX_RETRIES:
                print(f"  Retrying in {RETRY_DELAY}s...", file=sys.stderr)
                time.sleep(RETRY_DELAY)
    print(f"  [ERR] Groq failed after {MAX_RETRIES} attempts", file=sys.stderr)
    return None

# Subreddits to scrape (sorted by virality potential)
SUBREDDITS = [
    "AmItheAsshole",
    "tifu",
    "ProRevenge",
    "MaliciousCompliance",
    "entitledparents",
    "relationship_advice",
    "pettyrevenge",
    "TrueOffMyChest",
]


def scrape_reddit(subreddits: list = None, time_filter: str = "week",
                   limit: int = 5) -> list:
    """Scrape top posts from Reddit (no API key needed)."""
    if not subreddits:
        subreddits = random.sample(SUBREDDITS, min(4, len(SUBREDDITS)))

    posts = []
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/top.json?t={time_filter}&limit={limit}"
        req = urllib.request.Request(url, headers={
            "User-Agent": BROWSER_UA,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    text = post.get("selftext", "")
                    if len(text) > 200:  # Only posts with substantial text
                        posts.append({
                            "subreddit": sub,
                            "title": post.get("title", ""),
                            "text": text[:3000],  # Cap at 3000 chars
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                            "url": f"https://reddit.com{post.get('permalink', '')}",
                        })
            time.sleep(1)  # Be nice to Reddit
        except Exception as e:
            print(f"  [WARN] Reddit r/{sub} failed: {e}", file=sys.stderr)

    # Sort by engagement (score + comments)
    posts.sort(key=lambda p: p["score"] + p["num_comments"] * 2, reverse=True)
    return posts


def adapt_stories(groq_api_key: str, reddit_posts: list, count: int = 3) -> dict:
    """Use Groq to adapt Reddit posts into viral Short scripts."""

    # Pick top posts
    selected = reddit_posts[:count]

    posts_text = ""
    for i, post in enumerate(selected):
        posts_text += f"""
--- REDDIT POST {i+1} (r/{post['subreddit']}, {post['score']} upvotes) ---
Title: {post['title']}
Story: {post['text'][:1500]}
---
"""

    prompt = f"""You are a viral YouTube Shorts scriptwriter. Adapt these REAL trending Reddit posts into dramatic YouTube Shorts scripts.

{posts_text}

For EACH post, create a Short script:

Rules:
- Narration MUST be exactly 120-150 words (45-55 seconds when spoken). COUNT CAREFULLY.
- Rewrite in first person, casual dramatic tone - like you're telling the story to a friend
- Start with a CRAZY hook that makes people stop scrolling (the most shocking part first)
- Build tension throughout
- End with the twist, payoff, or most dramatic moment
- Create 4 DETAILED visual scene descriptions (see format below)
- DO NOT copy the Reddit text directly - rewrite it dramatically

Return JSON:
{{
  "shorts": [
    {{
      "title": "catchy YouTube title under 60 chars, use 1-2 CAPS words for impact",
      "description": "YouTube description with hashtags #aita #reddit #storytime #drama #plottwist",
      "tags": ["storytime", "reddit", "aita", "revenge", "plottwist", "drama", "viral", "shorts"],
      "niche": "aita/revenge/plottwist/entitled/drama",
      "narration": "THE REWRITTEN STORY. 120-150 words. First person. Dramatic. Hook first.",
      "scenes": [
        {{"visual_prompt": "close up portrait of [person: age, gender, hair color/style, specific facial expression], [specific indoor/outdoor setting with details], soft directional lighting, shallow depth of field, cinematic photography"}},
        {{"visual_prompt": "[specific action scene], [camera angle: low/overhead/medium shot], [specific setting with objects], dramatic side lighting, moody atmosphere, cinematic photography"}},
        {{"visual_prompt": "[confrontation or key moment between characters], [specific setting], dramatic lighting, tense body language, cinematic photography"}},
        {{"visual_prompt": "[resolution/emotional aftermath scene], [setting with time-of-day lighting], contemplative mood, cinematic composition"}}
      ],
      "hook_text": "2-4 word overlay (AM I WRONG?, WAIT FOR IT, SWEET REVENGE, PLOT TWIST, THE AUDACITY)",
      "source_subreddit": "subreddit name"
    }}
  ]
}}

IMPORTANT for visual_prompt: Write each as a DETAILED cinematic photography description. Include specific subjects (age, gender, hair, clothing, expression), specific settings (room type, furniture, time of day), and lighting details. Example: "close up portrait of a 28 year old woman with long brown hair, shocked expression, sitting at a wooden kitchen table, warm overhead pendant light, dim evening atmosphere, shallow depth of field, cinematic photography" - NOT generic descriptions.

CRITICAL: Each narration must be 120-150 words. Not less, not more.
Return ONLY valid JSON."""

    print("  Adapting stories via Groq...", file=sys.stderr)
    stories = _call_groq(groq_api_key, prompt, temperature=0.85)
    if stories:
        shorts = stories.get("shorts", [])
        print(f"  Adapted {len(shorts)} shorts", file=sys.stderr)
        for i, s in enumerate(shorts):
            words = len(s.get("narration", "").split())
            scenes = len(s.get("scenes", []))
            print(f"    Short {i+1}: '{s.get('title', '?')[:45]}' ({words}w, {scenes} scenes)",
                  file=sys.stderr)
    return stories


def generate_story(groq_api_key: str, niche: str = None, count: int = 3) -> dict:
    """Main entry: scrape Reddit trending + adapt with Groq."""

    # Step 1: Scrape Reddit
    print("  Scraping Reddit trending...", file=sys.stderr)
    posts = scrape_reddit()
    print(f"  Found {len(posts)} trending posts", file=sys.stderr)

    if not posts:
        print("  [WARN] No Reddit posts found, using Groq to generate original stories",
              file=sys.stderr)
        return _generate_original(groq_api_key, count)

    for p in posts[:5]:
        print(f"    r/{p['subreddit']}: {p['title'][:50]}... ({p['score']} pts)",
              file=sys.stderr)

    # Step 2: Adapt top posts with Groq
    return adapt_stories(groq_api_key, posts, count)


def _generate_original(groq_api_key: str, count: int = 3) -> dict:
    """Fallback: generate original stories if Reddit scraping fails."""
    niches = [
        "AITA - shocking family/relationship conflict with a twist ending",
        "Revenge - clever satisfying payback story",
        "Plot Twist - normal situation that takes an insane unexpected turn",
    ]
    selected = random.sample(niches, min(count, len(niches)))
    niche_list = "\n".join(f"- Story {i+1}: {n}" for i, n in enumerate(selected))

    prompt = f"""Generate {count} viral YouTube Shorts stories. 120-150 words each narration.

Niches:
{niche_list}

Return JSON:
{{
  "shorts": [
    {{
      "title": "catchy YouTube title under 60 chars, use 1-2 CAPS words",
      "description": "YouTube description with hashtags #aita #reddit #storytime #drama #plottwist",
      "tags": ["storytime", "reddit", "aita", "revenge", "plottwist", "drama", "viral", "shorts"],
      "niche": "aita/revenge/plottwist",
      "narration": "THE STORY. 120-150 words. First person. Dramatic hook first. Casual tone.",
      "scenes": [
        {{"visual_prompt": "close up portrait of [person: age, gender, hair, expression], [specific setting], soft directional lighting, shallow depth of field, cinematic photography"}},
        {{"visual_prompt": "[specific action scene], [camera angle], [setting with objects], dramatic side lighting, cinematic photography"}},
        {{"visual_prompt": "[confrontation between characters], [specific setting], dramatic lighting, tense body language, cinematic photography"}},
        {{"visual_prompt": "[resolution scene], [setting with time-of-day lighting], contemplative mood, cinematic composition"}}
      ],
      "hook_text": "2-4 word overlay like AM I WRONG? or PLOT TWIST",
      "source_subreddit": "reddit"
    }}
  ]
}}

Make stories feel REAL like Reddit posts. Dramatic hooks. Shocking twists.
IMPORTANT: Write each visual_prompt as a DETAILED cinematic photography description with specific subjects, settings, and lighting. Example: "close up portrait of a 25 year old man with black hair looking at his phone, blue glow on face, dimly lit bedroom, shallow depth of field, cinematic photography" - NOT generic descriptions.

CRITICAL RULES:
1. Each narration MUST be EXACTLY 120-150 words. NOT 80, NOT 100 - at least 120 words minimum.
2. Count your words before finishing. If under 120, ADD MORE DETAIL.
3. The narration should fill 45-55 seconds when spoken aloud.
4. First person perspective, casual dramatic tone.
5. Start with the most shocking part as a hook.
6. Each scene visual_prompt must be a detailed cinematic description.
Return ONLY valid JSON."""

    return _call_groq(groq_api_key, prompt, temperature=0.9)


if __name__ == "__main__":
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("GROQ_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    stories = generate_story(groq_key)
    if stories:
        print(json.dumps(stories, indent=2))
