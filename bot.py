"""
IGAUTO — Daily Quote Instagram Bot
-----------------------------------
Fetches a daily quote, renders it as a square image, picks a matching
song + hashtags, and publishes it to Instagram via the Graph API.

The image is hosted by committing it into this (public) GitHub repo and
referencing its raw.githubusercontent.com URL — Instagram's API requires
a public image URL, and this avoids needing a separate image-hosting
service. This is why the script runs in two phases (see below) with a
git commit+push in between, orchestrated by the GitHub Actions workflow.

Environment variables required (set as GitHub Actions secrets):
    IG_ACCESS_TOKEN   - long-lived Instagram access token
    IG_USER_ID        - Instagram business account ID (numeric)

Provided automatically by GitHub Actions (no setup needed):
    GITHUB_REPOSITORY - "owner/repo"
    GITHUB_REF_NAME    - branch name (e.g. "main")

Optional:
    DRY_RUN=true      - generate everything but skip the Instagram publish
                        (safe testing)

Usage:
    python bot.py prepare   # fetch quote, render image, write posts/<date>/
                             # (commit + push this before "publish")
    python bot.py publish   # read today's posts/<date>/record.json and
                             # publish it to Instagram using the now-public
                             # raw GitHub URL for the image
"""

import os
import io
import sys
import json
import time
import random
import textwrap
import datetime as dt

import requests
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo", auto-set in Actions
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "main")  # branch, auto-set in Actions

GRAPH_API_VERSION = "v22.0"
GRAPH_HOST = "https://graph.instagram.com"  # Instagram API with Instagram Login

IMAGE_SIZE = (1080, 1080)
FONT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "fonts")
POSTS_DIR = os.path.join(os.path.dirname(__file__), "posts")

# Fallback quotes used only if the ZenQuotes API is unreachable
FALLBACK_QUOTES = [
    {"q": "The way to get started is to quit talking and begin doing.", "a": "Walt Disney"},
    {"q": "Life is what happens when you're busy making other plans.", "a": "John Lennon"},
    {"q": "The future belongs to those who believe in the beauty of their dreams.", "a": "Eleanor Roosevelt"},
    {"q": "It does not matter how slowly you go as long as you do not stop.", "a": "Confucius"},
    {"q": "Everything you've ever wanted is on the other side of fear.", "a": "George Addair"},
    {"q": "Success is not final, failure is not fatal: it is the courage to continue that counts.", "a": "Winston Churchill"},
    {"q": "Believe you can and you're halfway there.", "a": "Theodore Roosevelt"},
]

# Theme keyword map -> used to pick hashtags + a matching song
THEMES = {
    "love": {
        "keywords": ["love", "heart", "loved", "loving", "beloved"],
        "hashtags": ["lovequotes", "relationshipgoals", "loveyourself"],
        "songs": [
            ("Perfect", "Ed Sheeran"),
            ("All of Me", "John Legend"),
            ("Thinking Out Loud", "Ed Sheeran"),
            ("Just the Way You Are", "Bruno Mars"),
        ],
    },
    "success": {
        "keywords": ["success", "win", "achieve", "goal", "victory", "accomplish"],
        "hashtags": ["successmindset", "hustle", "goalgetter"],
        "songs": [
            ("Eye of the Tiger", "Survivor"),
            ("Stronger", "Kanye West"),
            ("Level Up", "Ciara"),
            ("Legends Are Made", "Sam Tinnesz"),
        ],
    },
    "motivation": {
        "keywords": ["dream", "believe", "hope", "try", "never give up", "courage", "fear", "strong", "strength"],
        "hashtags": ["motivationalquotes", "keepgoing", "nevergiveup"],
        "songs": [
            ("Rise Up", "Andra Day"),
            ("Believer", "Imagine Dragons"),
            ("Titanium", "David Guetta ft. Sia"),
            ("Fight Song", "Rachel Platten"),
        ],
    },
    "time": {
        "keywords": ["time", "moment", "present", "today", "now", "tomorrow", "yesterday"],
        "hashtags": ["liveinthemoment", "seizetheday", "presentmoment"],
        "songs": [
            ("Time of Your Life", "Green Day"),
            ("Beautiful Day", "U2"),
            ("Here Comes the Sun", "The Beatles"),
        ],
    },
    "growth": {
        "keywords": ["grow", "change", "learn", "become", "journey", "grew", "learning"],
        "hashtags": ["selfgrowth", "personalgrowth", "growthmindset"],
        "songs": [
            ("Brave", "Sara Bareilles"),
            ("Roar", "Katy Perry"),
            ("A Sky Full of Stars", "Coldplay"),
        ],
    },
    "wisdom": {
        "keywords": ["wise", "wisdom", "truth", "knowledge", "understand", "mind"],
        "hashtags": ["wordsofwisdom", "quotestoliveby", "deepthoughts"],
        "songs": [
            ("The Sound of Silence", "Simon & Garfunkel"),
            ("Fix You", "Coldplay"),
            ("Vienna", "Billy Joel"),
        ],
    },
    "life": {
        "keywords": ["life", "living", "live"],
        "hashtags": ["lifequotes", "lifelessons", "reallife"],
        "songs": [
            ("Life Is a Highway", "Tom Cochrane"),
            ("Good Life", "OneRepublic"),
            ("Three Little Birds", "Bob Marley"),
        ],
    },
}

GENERIC_HASHTAGS = [
    "quoteoftheday",
    "dailyquote",
    "quotestoliveby",
    "inspirationalquotes",
    "wordsofwisdom",
    "positivevibes",
]

GENERIC_SONGS = [
    ("Here Comes the Sun", "The Beatles"),
    ("Good Vibrations", "The Beach Boys"),
    ("Walking on Sunshine", "Katrina and the Waves"),
    ("Three Little Birds", "Bob Marley"),
]

BACKGROUND_PALETTES = [
    ((25, 25, 40), (70, 40, 90)),      # deep indigo -> plum
    ((15, 40, 45), (10, 90, 90)),      # teal
    ((45, 20, 20), (110, 50, 30)),     # warm ember
    ((20, 30, 55), (40, 80, 130)),     # night blue
    ((35, 15, 45), (120, 40, 80)),     # magenta dusk
]

GOOGLE_FONT_URLS = {
    "bold": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
    "regular": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Regular.ttf",
    "italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Italic.ttf",
}

SYSTEM_FONT_FALLBACKS = {
    "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "italic": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
}


# --------------------------------------------------------------------------
# Quote fetching
# --------------------------------------------------------------------------

def fetch_quote():
    """Get today's quote from ZenQuotes (free, no key). Falls back to a
    local list if the API is unreachable or rate-limited."""
    try:
        resp = requests.get("https://zenquotes.io/api/today", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]["q"].strip(), data[0]["a"].strip()
    except Exception as exc:
        print(f"[warn] ZenQuotes fetch failed ({exc}); using fallback quote.")

    pick = random.choice(FALLBACK_QUOTES)
    return pick["q"], pick["a"]


# --------------------------------------------------------------------------
# Theme / hashtags / song
# --------------------------------------------------------------------------

def detect_theme(quote_text):
    text = quote_text.lower()
    best_theme, best_hits = "life", 0
    for name, data in THEMES.items():
        hits = sum(1 for kw in data["keywords"] if kw in text)
        if hits > best_hits:
            best_theme, best_hits = name, hits
    return best_theme if best_hits > 0 else "life"


def pick_song(theme):
    pool = THEMES.get(theme, {}).get("songs") or GENERIC_SONGS
    title, artist = random.choice(pool)
    return title, artist


def build_hashtags(theme, author):
    tags = list(GENERIC_HASHTAGS)
    tags += THEMES.get(theme, {}).get("hashtags", [])
    author_tag = "".join(w.capitalize() for w in author.replace(".", "").split())
    if author_tag:
        tags.append(f"{author_tag}Quotes")
    # de-dupe while preserving order, cap at 15
    seen, ordered = set(), []
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(t)
    return ordered[:15]


def build_caption(quote, author, song_title, song_artist, hashtags):
    tag_line = " ".join(f"#{t}" for t in hashtags)
    return (
        f'"{quote}"\n'
        f"— {author}\n\n"
        f'🎵 Pairs well with "{song_title}" by {song_artist}.\n\n'
        f"{tag_line}"
    )


# --------------------------------------------------------------------------
# Image generation
# --------------------------------------------------------------------------

def _download_font(url, dest_path):
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)


def get_font(style, size):
    """style is 'bold' | 'regular' | 'italic'. Tries a cached/downloaded
    Google Font first, falls back to a system font, then PIL default."""
    os.makedirs(FONT_CACHE_DIR, exist_ok=True)
    cached_path = os.path.join(FONT_CACHE_DIR, f"Poppins-{style}.ttf")

    if not os.path.exists(cached_path):
        try:
            _download_font(GOOGLE_FONT_URLS[style], cached_path)
        except Exception as exc:
            print(f"[warn] Could not download font ({exc}); trying system font.")

    if os.path.exists(cached_path):
        try:
            return ImageFont.truetype(cached_path, size)
        except Exception:
            pass

    fallback_path = SYSTEM_FONT_FALLBACKS.get(style)
    if fallback_path and os.path.exists(fallback_path):
        return ImageFont.truetype(fallback_path, size)

    print("[warn] Falling back to PIL default bitmap font (low quality).")
    return ImageFont.load_default()


def make_gradient_background(size):
    top, bottom = random.choice(BACKGROUND_PALETTES)
    w, h = size
    base = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(base)
    for y in range(h):
        ratio = y / h
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return base


def wrap_text_to_width(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_quote_image(quote, author, out_path):
    img = make_gradient_background(IMAGE_SIZE)
    draw = ImageDraw.Draw(img)
    w, h = IMAGE_SIZE
    margin = 100
    max_text_width = w - 2 * margin

    # Auto-shrink the quote font until it fits within a reasonable height
    quote_font_size = 64
    quote_font = get_font("bold", quote_font_size)
    lines = wrap_text_to_width(draw, quote, quote_font, max_text_width)
    while len(lines) > 8 and quote_font_size > 36:
        quote_font_size -= 4
        quote_font = get_font("bold", quote_font_size)
        lines = wrap_text_to_width(draw, quote, quote_font, max_text_width)

    line_height = int(quote_font_size * 135 / 1000) + quote_font_size
    total_text_height = line_height * len(lines)
    author_font = get_font("italic", 34)
    mark_font = get_font("bold", 160)

    mark_gap = 30
    author_gap = 40
    mark_height = mark_font.getbbox("\u201C")[3]
    author_height = author_font.getbbox(f"— {author}")[3]

    block_height = mark_height + mark_gap + total_text_height + author_gap + author_height
    y = (h - block_height) / 2

    draw.text((margin - 10, y), "\u201C", font=mark_font, fill=(255, 255, 255, 90))
    y += mark_height + mark_gap

    for line in lines:
        line_width = draw.textlength(line, font=quote_font)
        x = (w - line_width) / 2
        draw.text((x, y), line, font=quote_font, fill="white")
        y += line_height

    author_text = f"— {author}"
    author_width = draw.textlength(author_text, font=author_font)
    draw.text(((w - author_width) / 2, y + author_gap), author_text, font=author_font, fill=(230, 230, 230))

    img.save(out_path, "JPEG", quality=92)
    return out_path


# --------------------------------------------------------------------------
# Public image URL (hosted via this GitHub repo instead of a 3rd party)
# --------------------------------------------------------------------------

def build_public_image_url(date_str):
    if not GITHUB_REPOSITORY:
        raise EnvironmentError(
            "GITHUB_REPOSITORY is not set. This should be run inside GitHub "
            "Actions, or set it manually as 'owner/repo' for local testing."
        )
    return (
        f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/"
        f"{GITHUB_REF_NAME}/posts/{date_str}/quote.jpg"
    )


# --------------------------------------------------------------------------
# Instagram publishing
# --------------------------------------------------------------------------

def create_media_container(image_url, caption):
    url = f"{GRAPH_HOST}/{GRAPH_API_VERSION}/{IG_USER_ID}/media"
    resp = requests.post(
        url,
        data={"image_url": image_url, "caption": caption, "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def wait_for_container_ready(container_id, timeout=90, interval=5):
    url = f"{GRAPH_HOST}/{container_id}"
    waited = 0
    while waited < timeout:
        resp = requests.get(
            url, params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN}, timeout=15
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Container failed with status: {status}")
        time.sleep(interval)
        waited += interval
    raise TimeoutError("Timed out waiting for media container to finish processing.")


def publish_container(creation_id):
    url = f"{GRAPH_HOST}/{GRAPH_API_VERSION}/{IG_USER_ID}/media_publish"
    resp = requests.post(
        url, data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()["id"]


# --------------------------------------------------------------------------
# Local record-keeping
# --------------------------------------------------------------------------

def save_record(date_str, quote, author, theme, song_title, song_artist, hashtags, caption, media_id=None):
    day_dir = os.path.join(POSTS_DIR, date_str)
    os.makedirs(day_dir, exist_ok=True)

    record_path = os.path.join(day_dir, "record.json")
    record = {}
    if os.path.exists(record_path):
        with open(record_path) as f:
            record = json.load(f)

    record.update({
        "date": date_str,
        "quote": quote,
        "author": author,
        "theme": theme,
        "song": {"title": song_title, "artist": song_artist},
        "hashtags": hashtags,
        "caption": caption,
        "dry_run": DRY_RUN,
    })
    if media_id is not None:
        record["instagram_media_id"] = media_id

    with open(record_path, "w") as f:
        json.dump(record, f, indent=2)
    return record


def load_record(date_str):
    record_path = os.path.join(POSTS_DIR, date_str, "record.json")
    with open(record_path) as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def cmd_prepare():
    """Phase 1: fetch quote, render image, write posts/<date>/. Commit and
    push this (the workflow does that) before running 'publish'."""
    today = dt.date.today().isoformat()
    print(f"[info] Preparing daily post for {today} (DRY_RUN={DRY_RUN})")

    quote, author = fetch_quote()
    theme = detect_theme(quote)
    song_title, song_artist = pick_song(theme)
    hashtags = build_hashtags(theme, author)
    caption = build_caption(quote, author, song_title, song_artist, hashtags)

    print(f"[info] Quote: \"{quote}\" — {author}")
    print(f"[info] Theme: {theme} | Song: {song_title} by {song_artist}")

    day_dir = os.path.join(POSTS_DIR, today)
    os.makedirs(day_dir, exist_ok=True)
    image_path = os.path.join(day_dir, "quote.jpg")
    render_quote_image(quote, author, image_path)
    print(f"[info] Image rendered at {image_path}")

    save_record(today, quote, author, theme, song_title, song_artist, hashtags, caption)
    print("[info] Wrote posts/{}/record.json — commit and push this next.".format(today))


def cmd_publish():
    """Phase 2: read today's prepared record and publish it to Instagram
    using the now-public (already pushed) raw GitHub URL for the image."""
    today = dt.date.today().isoformat()
    record = load_record(today)
    caption = record["caption"]

    if DRY_RUN:
        print("[info] DRY_RUN is on — skipping Instagram publish.")
        print("----- CAPTION PREVIEW -----")
        print(caption)
        print("----------------------------")
        return

    if not (IG_ACCESS_TOKEN and IG_USER_ID):
        raise EnvironmentError("Missing IG_ACCESS_TOKEN or IG_USER_ID.")

    image_url = build_public_image_url(today)
    print(f"[info] Using image URL: {image_url}")

    creation_id = create_media_container(image_url, caption)
    print(f"[info] Media container created: {creation_id}")

    wait_for_container_ready(creation_id)
    media_id = publish_container(creation_id)
    print(f"[info] Published! Instagram media ID: {media_id}")

    save_record(
        today, record["quote"], record["author"], record["theme"],
        record["song"]["title"], record["song"]["artist"], record["hashtags"],
        caption, media_id=media_id,
    )
    print("[info] Updated record.json with the Instagram media ID.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if command == "prepare":
        cmd_prepare()
    elif command == "publish":
        cmd_publish()
    else:
        print(f"Unknown command: {command!r}. Use 'prepare' or 'publish'.")
        sys.exit(1)
