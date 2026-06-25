"""
Atlantis Space — Instagram Agent
=================================
Space, astronomy, ISRO, NASA news automatically fetch karke Instagram pe post karta hai.
Same infrastructure as atlantis_news_ai, space branding ke saath.

Run:
    python atlantis_space/agent.py
"""

import os
import sys
import json
import time
import tempfile
import colorsys
import requests

# Parent folder se common utilities import karo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from dotenv import load_dotenv
from ddgs import DDGS
from PIL import Image, ImageDraw
from groq import Groq

# Space agent ka apna .env load karo
_space_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_space_env)

# --- Config -------------------------------------------------------------------
GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
PEXELS_API_KEY       = os.getenv("PEXELS_API_KEY")
INSTAGRAM_TOKEN      = os.getenv("SPACE_INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID = os.getenv("SPACE_INSTAGRAM_ACCOUNT_ID")
IMGBB_API_KEY        = os.getenv("IMGBB_API_KEY")
APP_ID               = os.getenv("SPACE_APP_ID")
APP_SECRET           = os.getenv("SPACE_APP_SECRET")

CHANNEL_HANDLE = "@atlantis_space"
POST_DELAY     = 60
CAROUSEL_SLIDES = 3

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlantis_space_logo.png")
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posted_history.json")

NEWS_TOPICS = [
    "NASA space discovery news today",
    "ISRO India space mission launch today",
    "astronomy exoplanet black hole telescope news today",
    "SpaceX rocket launch space news today",
    "space science Mars Moon solar system news today",
]


# --- Shared utilities (copy from parent to keep standalone) -------------------
def get_font(size: int):
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/noto/NotoSansDevanagari-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/Nirmala.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def image_palette(img: Image.Image):
    sample = img.resize((80, 80), Image.LANCZOS).convert("RGB")
    pixels = list(sample.getdata())
    n = len(pixels)
    avg_r = sum(p[0] for p in pixels) // n
    avg_g = sum(p[1] for p in pixels) // n
    avg_b = sum(p[2] for p in pixels) // n
    h, s, v = colorsys.rgb_to_hsv(avg_r / 255, avg_g / 255, avg_b / 255)
    accent = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, min(s + 0.35, 1.0), 0.90))
    bar    = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, min(s + 0.2, 0.85), 0.18))
    return accent, bar


def clean_title(title: str) -> str:
    import re
    return re.sub(r'\s*[-–|]\s*[A-Z][A-Za-z0-9 &.]{2,40}$', '', title).strip()


# --- News Fetch ---------------------------------------------------------------
def fetch_news(topic: str, max_results: int = 5) -> list[dict]:
    print(f"\n[1/4] Space news fetch: '{topic}'")
    cutoff = datetime.now().timestamp() - 86400
    strategies = [{"timelimit": "d"}, {"timelimit": "w"}, {}]

    for attempt, params in enumerate(strategies):
        try:
            time.sleep(attempt * 4)
            with DDGS() as ddgs:
                results = list(ddgs.news(topic, max_results=max_results * 3, **params))
            if not results:
                raise Exception("No results found.")
            fresh = []
            for n in results:
                n["title"] = clean_title(n.get("title", ""))
                pub = n.get("date", "")
                try:
                    from datetime import datetime as dt
                    pub_ts = dt.fromisoformat(pub.replace("Z", "+00:00")).timestamp()
                    if pub_ts >= cutoff - 86400 * attempt:
                        fresh.append(n)
                except Exception:
                    fresh.append(n)
            fresh = fresh[:max_results]
            if fresh:
                print(f"      {len(fresh)} news mili")
                return fresh
            raise Exception("No fresh results after filtering.")
        except Exception as e:
            print(f"      Attempt {attempt+1} failed: {e}")
    return []


# --- History ------------------------------------------------------------------
def load_posted_history() -> set:
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("titles", []))
    except Exception:
        pass
    return set()


def save_posted_title(title: str) -> None:
    try:
        titles = list(load_posted_history())
        normalized = title.lower().strip()[:120]
        if normalized not in titles:
            titles.append(normalized)
        titles = titles[-100:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"titles": titles, "updated": datetime.now().isoformat()},
                      f, ensure_ascii=False, indent=2)
        import subprocess
        repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run(["git", "config", "user.email", "bot@atlantisspace.ai"], cwd=repo_dir)
        subprocess.run(["git", "config", "user.name", "Atlantis Space Bot"], cwd=repo_dir)
        subprocess.run(["git", "add", "atlantis_space/posted_history.json"], cwd=repo_dir)
        result = subprocess.run(
            ["git", "commit", "-m", "chore: update space posted history [skip ci]"],
            cwd=repo_dir, capture_output=True
        )
        if result.returncode == 0:
            subprocess.run(["git", "push"], cwd=repo_dir)
    except Exception as e:
        print(f"      History save error: {e}")


def get_recently_posted_titles() -> set:
    titles = load_posted_history()
    if not INSTAGRAM_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        return titles
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_ACCOUNT_ID}/media",
            params={"fields": "caption", "limit": 12, "access_token": INSTAGRAM_TOKEN},
            timeout=10
        )
        for post in resp.json().get("data", []):
            cap = post.get("caption", "")
            if cap:
                titles.add(cap[:120].lower())
    except Exception:
        pass
    return titles


def is_duplicate(news_title: str, recent_titles: set) -> bool:
    words = set(news_title.lower().split())
    for stored in recent_titles:
        stored_words = set(stored.split())
        overlap = len(words & stored_words) / max(len(words), 1)
        if overlap >= 0.4:
            return True
    return False


# --- AI Planning --------------------------------------------------------------
def smart_plan(all_news: list[dict], count: int = CAROUSEL_SLIDES) -> list[dict]:
    print(f"\n[AI] {len(all_news)} space news analyze kar raha hoon...")
    news_list_str = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n.get('title','')[:100]}"
        for i, n in enumerate(all_news[:10])
    ])
    try:
        client = Groq(api_key=GROQ_API_KEY)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=500,
            messages=[{"role": "user", "content": f"""
Ye space/astronomy news headlines hain. Importance score do (1-10):
- 9-10: Major discovery, mission launch, historic event (moon landing type)
- 7-8: Significant finding, new data, upcoming mission
- 5-6: Minor update, conference announcement
- 1-4: Rumor, unverified, stale

{news_list_str}

TOP {count} choose karo (score 6+). JSON:
{{
  "plan": [
    {{"index": 0, "importance": 9, "reason": "why"}}
  ],
  "strategy": "one line strategy"
}}"""}],
            response_format={"type": "json_object"}
        )
        result = json.loads(resp.choices[0].message.content)
        print(f"      Strategy: {result.get('strategy', '')}")
        planned = []
        for item in result.get("plan", []):
            idx = item.get("index", 0)
            if 0 <= idx < len(all_news):
                news = all_news[idx].copy()
                news["_importance"] = item.get("importance", 7)
                planned.append(news)
        return planned[:count] if planned else all_news[:count]
    except Exception as e:
        print(f"      Planning error: {e}")
        return all_news[:count]


# --- Caption Generation -------------------------------------------------------
def generate_caption(news_item: dict) -> dict:
    print(f"\n[2/4] Caption generate kar raha hoon...")
    client = Groq(api_key=GROQ_API_KEY)

    prompt = f"""
Tu ek Instagram space science page ka content writer hai — channel: {CHANNEL_HANDLE}

News Title: {news_item.get('title', '')}
News Body: {news_item.get('body', '')[:500]}
Source: {news_item.get('source', '')}

FACT ACCURACY RULE: Sirf wahi facts likho jo upar clearly likhe hain — kuch add mat karo.

Caption rules:
- YE EK PHOTO POST HAI — "video", "reel", "clip" mat likho
- Hinglish mein likho (Hindi + English mix)
- Space ke baare mein wonder/awe create karo — "Socho zaraa...", "Ye toh kamaal hai!"
- 6-8 lines, scientific but accessible language
- End mein thought-provoking question
- CAPTION MEIN KOI HASHTAG NAHI — sirf "hashtags" field mein

JSON:
{{
  "caption": "caption only, no hashtags",
  "hashtags": "#Space #ISRO #NASA #Astronomy #SpaceScience #Cosmos #Universe #IndiaInSpace #SpaceExploration #ScienceNews #AstroNews #StarGazing #BlackHole #MarsExploration #SpaceTech (15-20 tags)",
  "image_keyword": "2-3 word English description for image search",
  "emoji_title": "emoji + short title",
  "headline": "5-8 word Hinglish headline — SIRF confirmed facts, spelling 100% correct",
  "image_summary": "2-3 Hinglish sentences (max 35 words) — confirmed facts only, spelling correct"
}}
"""

    try:
        message = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(message.choices[0].message.content.strip())

        import re
        caption = result.get("caption", "")
        caption = re.sub(r'\s*#\w+', '', caption).strip()
        caption = re.sub(r'\b(video|reel|clip)\b', 'photo', caption, flags=re.IGNORECASE)
        result["caption"] = caption

        # Spell-check headline + summary
        headline = result.get("headline", "")
        summary  = result.get("image_summary", "")
        if headline or summary:
            try:
                fix = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    max_tokens=200,
                    messages=[{"role": "user", "content": f"""Fix spelling mistakes only. Do NOT change meaning or words.

Headline: {headline}
Summary: {summary}

JSON: {{"headline": "corrected", "summary": "corrected"}}"""}],
                    response_format={"type": "json_object"}
                )
                fixed = json.loads(fix.choices[0].message.content)
                if fixed.get("headline"):
                    result["headline"] = fixed["headline"]
                if fixed.get("summary"):
                    result["image_summary"] = fixed["summary"]
            except Exception:
                pass

        preview = result['caption'][:60].encode('ascii', errors='ignore').decode()
        print(f"      Caption ready: {preview}...")
        return result
    except Exception as e:
        print(f"      Caption error: {e}")
        return {
            "caption": news_item.get('title', 'Space Breaking News!'),
            "hashtags": "#Space #ISRO #NASA #Astronomy #SpaceScience",
            "image_keyword": "space astronomy",
            "emoji_title": "🚀 Space News",
            "headline": news_item.get('title', 'Space News')[:50],
            "image_summary": "",
        }


# --- Image Upload to ImgBB ----------------------------------------------------
def upload_image(file_path: str) -> str | None:
    if not IMGBB_API_KEY:
        return None
    try:
        with open(file_path, "rb") as f:
            import base64
            b64 = base64.b64encode(f.read()).decode("utf-8")
        resp = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": IMGBB_API_KEY, "image": b64},
            timeout=30
        )
        url = resp.json().get("data", {}).get("url")
        if url:
            print(f"      ImgBB upload: {url}")
        return url
    except Exception as e:
        print(f"      ImgBB error: {e}")
        return None


# --- Image Overlay ------------------------------------------------------------
def add_watermark(image_url: str, title: str = "", source: str = "", summary: str = "") -> str | None:
    try:
        import io
        resp = requests.get(image_url, timeout=15)
        if resp.status_code != 200:
            return image_url

        news_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

        # 1080x1080 square crop
        w, h = news_img.size
        side = min(w, h)
        news_img = news_img.crop(((w-side)//2, (h-side)//2, (w+side)//2, (h+side)//2))
        news_img = news_img.resize((1080, 1080), Image.LANCZOS)

        draw = ImageDraw.Draw(news_img)
        accent_color, bar_base = image_palette(news_img)

        # Gradient bar — bottom 38%
        bar_top = int(1080 * 0.62)
        overlay = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        for i in range(1080 - bar_top):
            alpha = int(220 * (i / (1080 - bar_top)))
            ov_draw.line([(0, bar_top + i), (1080, bar_top + i)], fill=(*bar_base, alpha))
        news_img = Image.alpha_composite(news_img, overlay)
        draw = ImageDraw.Draw(news_img)

        # Top accent bar
        draw.rectangle([0, 0, 1080, 10], fill=(*accent_color, 255))

        font_title   = get_font(52)
        font_summary = get_font(32)
        font_source  = get_font(32)

        # Source + date line
        date_str  = datetime.now().strftime("%d %b %Y")
        src_color = tuple(min(255, int(c * 1.4 + 60)) for c in accent_color)
        src_label = f"{source}  •  " if source else ""
        draw.text((30, bar_top + 18), f"{src_label}{date_str}  •  {CHANNEL_HANDLE}",
                  font=font_source, fill=(*src_color, 255))

        # Headline
        y = bar_top + 68
        if title:
            words = title.split()
            lines, line = [], ""
            for w_word in words:
                test = f"{line} {w_word}".strip()
                if len(test) > 28:
                    lines.append(line)
                    line = w_word
                else:
                    line = test
            if line:
                lines.append(line)
            for l in lines[:2]:
                draw.text((30, y), l, font=font_title, fill=(255, 255, 255, 255))
                y += 62

        # Summary
        if summary:
            y += 8
            words = summary.split()
            lines, line = [], ""
            for w_word in words:
                test = f"{line} {w_word}".strip()
                if len(test) > 38:
                    lines.append(line)
                    line = w_word
                else:
                    line = test
            if line:
                lines.append(line)
            for l in lines[:3]:
                draw.text((30, y), l, font=font_summary, fill=(230, 230, 230, 245))
                y += 40

        # Logo
        if os.path.exists(LOGO_PATH):
            logo = Image.open(LOGO_PATH).convert("RGBA")
            pixels = list(logo.getdata())
            logo.putdata([
                (pr, pg, pb, 0) if pr > 220 and pg > 220 and pb > 220 else (pr, pg, pb, pa)
                for pr, pg, pb, pa in pixels
            ])
            logo_w = int(1080 * 0.10)
            logo_h = int(logo.height * (logo_w / logo.width))
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            pad = 4
            lx, ly = 1080 - logo_w - 20, 1080 - logo_h - 20
            draw.rectangle([lx-pad, ly-pad, lx+logo_w+pad, ly+logo_h+pad], fill=(255, 255, 255, 230))
            news_img.paste(logo, (lx, ly), logo)

        final = news_img.convert("RGB")
        path = os.path.join(tempfile.gettempdir(), f"space_{int(time.time())}.jpg")
        final.save(path, "JPEG", quality=92)
        url = upload_image(path)
        return url if url else image_url

    except Exception as e:
        print(f"      Overlay error: {e}")
        return image_url


# --- Instagram Post -----------------------------------------------------------
def post_to_instagram(image_url: str, caption: str) -> str | None:
    print(f"\n[4/4] Instagram pe post kar raha hoon...")
    if not INSTAGRAM_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        print("      Dry run — credentials nahi hain")
        return "dry_run"
    try:
        upload = requests.post(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_ACCOUNT_ID}/media",
            data={"image_url": image_url, "caption": caption, "access_token": INSTAGRAM_TOKEN},
            timeout=15
        )
        container_id = upload.json().get("id")
        if not container_id:
            print(f"      Upload error: {upload.json()}")
            return None
        time.sleep(3)
        pub = requests.post(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_ACCOUNT_ID}/media_publish",
            data={"creation_id": container_id, "access_token": INSTAGRAM_TOKEN},
            timeout=15
        )
        media_id = pub.json().get("id")
        if media_id:
            print(f"      Post successful! ID: {media_id}")
            return media_id
        print(f"      Publish error: {pub.json()}")
        return None
    except Exception as e:
        print(f"      Instagram error: {e}")
        return None


# --- Reel Pipeline -----------------------------------------------------------
def fetch_space_video(keyword: str) -> str | None:
    """Pexels se space stock video download karo — portrait MP4"""
    if not PEXELS_API_KEY:
        return None
    try:
        headers = {"Authorization": PEXELS_API_KEY}
        resp = requests.get(
            f"https://api.pexels.com/videos/search?query={keyword} space&per_page=8&orientation=portrait",
            headers=headers, timeout=10
        )
        videos = resp.json().get("videos", [])
        for video in videos:
            for vf in video.get("video_files", []):
                if vf.get("file_type") == "video/mp4" and vf.get("height", 0) >= 720:
                    url = vf["link"]
                    print(f"      Pexels space video mili: {url[:60]}")
                    r = requests.get(url, timeout=90, stream=True)
                    path = os.path.join(tempfile.gettempdir(), f"space_vid_{int(time.time())}.mp4")
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    size_mb = os.path.getsize(path) // 1024 // 1024
                    print(f"      Downloaded: {size_mb}MB")
                    return path
    except Exception as e:
        print(f"      Space video error: {e}")
    return None


def generate_tts(text: str, out_path: str) -> bool:
    try:
        from gtts import gTTS
        gTTS(text=text, lang="hi", slow=False).save(out_path)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as e:
        print(f"      TTS error: {e}")
        return False


def process_reel(video_path: str, headline: str, summary: str) -> str | None:
    """Space video ko Reel format mein convert karo — text overlay + TTS audio"""
    import subprocess
    try:
        ts          = int(time.time())
        tmp         = tempfile.gettempdir()
        base_path   = os.path.join(tmp, f"rbase_{ts}.mp4")
        overlay_png = os.path.join(tmp, f"rovl_{ts}.png")
        audio_path  = os.path.join(tmp, f"rtts_{ts}.mp3")
        out_path    = os.path.join(tmp, f"reel_{ts}.mp4")

        # Step 1: 9:16 crop + resize to 720x1280, trim to 30s
        crop = subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-t", "30",
            "-vf", "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=720:1280",
            "-c:v", "libx264", "-an", "-preset", "fast", "-crf", "28",
            base_path
        ], capture_output=True, timeout=120)

        if crop.returncode != 0 or not os.path.exists(base_path):
            print(f"      Crop fail: {crop.stderr[-100:].decode(errors='ignore')}")
            return None

        # Step 2: Pillow overlay PNG — dark bar at bottom with text
        overlay = Image.new("RGBA", (720, 320), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        ov_draw.rectangle([0, 0, 720, 320], fill=(0, 0, 0, 195))
        # Accent line
        ov_draw.rectangle([0, 0, 720, 6], fill=(80, 180, 255, 255))
        ov_draw.text((20, 18), headline[:50],  font=get_font(46), fill=(255, 255, 255, 255))
        ov_draw.text((20, 78), summary[:90],   font=get_font(28), fill=(210, 230, 255, 245))
        date_str = datetime.now().strftime("%d %b %Y")
        ov_draw.text((20, 282), f"{CHANNEL_HANDLE}  •  {date_str}",
                     font=get_font(24), fill=(140, 180, 230, 220))
        overlay.save(overlay_png, "PNG")

        # Step 3: TTS
        tts_text = f"{headline}. {summary}"
        has_audio = generate_tts(tts_text, audio_path)

        # Step 4: FFmpeg combine
        if has_audio:
            result = subprocess.run([
                "ffmpeg", "-y",
                "-i", base_path, "-i", overlay_png, "-i", audio_path,
                "-filter_complex",
                "[0:v][1:v]overlay=0:H-320[vout];[2:a]volume=1.5,atrim=0:30[aout]",
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-c:a", "aac",
                "-shortest", "-preset", "fast", "-crf", "28", out_path
            ], capture_output=True, timeout=120)
        else:
            result = subprocess.run([
                "ffmpeg", "-y",
                "-i", base_path, "-i", overlay_png,
                "-filter_complex", "[0:v][1:v]overlay=0:H-320[out]",
                "-map", "[out]", "-c:v", "libx264",
                "-preset", "fast", "-crf", "28", out_path
            ], capture_output=True, timeout=120)

        for p in [base_path, overlay_png, audio_path]:
            try: os.remove(p)
            except: pass

        if result.returncode == 0 and os.path.exists(out_path):
            size_mb = os.path.getsize(out_path) // 1024 // 1024
            print(f"      Reel ready: {size_mb}MB {'(with audio)' if has_audio else ''}")
            return out_path
        print(f"      FFmpeg error: {result.stderr[-150:].decode(errors='ignore')}")
    except Exception as e:
        print(f"      Reel process error: {e}")
    return None


def upload_video_github(video_path: str) -> str | None:
    """Reel video GitHub Release pe upload karo — public URL milegi"""
    gh_token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not gh_token or not repo:
        return None
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    filename = f"space_reel_{int(time.time())}.mp4"
    try:
        releases = requests.get(
            f"https://api.github.com/repos/{repo}/releases",
            headers=headers, timeout=10
        ).json()
        upload_url = None
        for rel in (releases if isinstance(releases, list) else []):
            if rel.get("tag_name") == "media-assets":
                upload_url = rel["upload_url"].split("{")[0]
                break
        if not upload_url:
            create = requests.post(
                f"https://api.github.com/repos/{repo}/releases",
                headers=headers,
                json={"tag_name": "media-assets", "name": "Media Assets",
                      "draft": False, "body": "Auto-generated space reels"},
                timeout=10
            ).json()
            upload_url = create.get("upload_url", "").split("{")[0]
        if not upload_url:
            return None
        size_mb = os.path.getsize(video_path) // 1024 // 1024
        print(f"      GitHub upload ({size_mb}MB)...")
        with open(video_path, "rb") as f:
            up = requests.post(
                f"{upload_url}?name={filename}",
                headers={**headers, "Content-Type": "video/mp4"},
                data=f, timeout=300
            ).json()
        url = up.get("browser_download_url", "")
        if url:
            print(f"      Video URL: {url[:80]}")
            return url
    except Exception as e:
        print(f"      GitHub upload error: {e}")
    return None


def post_reel(video_url: str, caption: str) -> str | None:
    """Instagram Reels API se post karo"""
    print(f"\n[Reel] Instagram pe post kar raha hoon...")
    if not INSTAGRAM_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        return "dry_run"
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_ACCOUNT_ID}/media",
            data={"video_url": video_url, "caption": caption,
                  "media_type": "REELS", "access_token": INSTAGRAM_TOKEN},
            timeout=20
        )
        container_id = resp.json().get("id")
        if not container_id:
            print(f"      Reel container error: {resp.json()}")
            return None
        # Wait for processing (max 90s)
        for _ in range(12):
            time.sleep(8)
            status = requests.get(
                f"https://graph.facebook.com/v25.0/{container_id}",
                params={"fields": "status_code", "access_token": INSTAGRAM_TOKEN},
                timeout=10
            ).json()
            code = status.get("status_code", "")
            print(f"      Reel status: {code}")
            if code == "FINISHED":
                break
            if code == "ERROR":
                return None
        pub = requests.post(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_ACCOUNT_ID}/media_publish",
            data={"creation_id": container_id, "access_token": INSTAGRAM_TOKEN},
            timeout=15
        )
        media_id = pub.json().get("id")
        if media_id:
            print(f"      Reel posted! ID: {media_id}")
            return media_id
        print(f"      Reel publish error: {pub.json()}")
    except Exception as e:
        print(f"      Reel error: {e}")
    return None


def auto_first_comment(media_id: str, hashtags: str) -> None:
    if not INSTAGRAM_TOKEN or media_id == "dry_run" or not hashtags:
        return
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://graph.facebook.com/v25.0/{media_id}/comments",
                data={"message": hashtags, "access_token": INSTAGRAM_TOKEN},
                timeout=15
            )
            data = resp.json()
            if data.get("id"):
                print(f"      Hashtag comment posted!")
                return
            print(f"      Comment attempt {attempt+1} error: {data}")
            if attempt < 2:
                time.sleep(6)
        except Exception as e:
            print(f"      Comment attempt {attempt+1} exception: {e}")
            if attempt < 2:
                time.sleep(6)


# --- Main Agent ---------------------------------------------------------------
def run_agent():
    print("=" * 55)
    print(f"  🚀 Atlantis Space Agent Starting...")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    all_news = []
    for topic in NEWS_TOPICS:
        results = fetch_news(topic, max_results=3)
        all_news.extend(results)

    all_news = [n for n in all_news if n.get("image")]
    print(f"      Image wali news: {len(all_news)}")

    if not all_news:
        print("Koi image wali space news nahi mili.")
        return

    recent_titles = get_recently_posted_titles()
    all_news = [n for n in all_news if not is_duplicate(n.get("title", ""), recent_titles)]
    print(f"      Duplicate hataane ke baad: {len(all_news)}")

    if not all_news:
        print("Sab news already post ho chuki hai.")
        return

    news_list = smart_plan(all_news, count=CAROUSEL_SLIDES)
    posted = 0

    for i, news in enumerate(news_list):
        print(f"\n{'-'*50}")
        print(f"News: {news.get('title', '')[:70]}...")

        content = generate_caption(news)
        headline = content.get("headline") or news.get("title", "")
        summary  = content.get("image_summary", "")
        hashtags = content.get("hashtags", "#Space #ISRO #NASA #Astronomy")
        caption  = content.get("caption", "")

        media_id = None

        # First news → Reel, baaki → Photo post
        if i == 0:
            print("      [Reel mode] Space video dhund raha hoon...")
            keyword = content.get("image_keyword", "space astronomy")
            video_path = fetch_space_video(keyword)
            if video_path:
                reel_path = process_reel(video_path, headline, summary)
                try: os.remove(video_path)
                except: pass
                if reel_path:
                    video_url = upload_video_github(reel_path)
                    try: os.remove(reel_path)
                    except: pass
                    if video_url:
                        media_id = post_reel(video_url, caption)
            if not media_id:
                print("      Reel fail — photo post pe fallback")

        # Photo post (Reel fail ya remaining news)
        if not media_id:
            img_url = add_watermark(
                news.get("image"),
                title=headline,
                source=news.get("source", ""),
                summary=summary
            )
            if img_url:
                media_id = post_to_instagram(img_url, caption)

        if media_id:
            save_posted_title(news.get("title", ""))
            time.sleep(8)
            auto_first_comment(media_id, hashtags)
            print(f"      Post ho gaya!")
            posted += 1
            time.sleep(POST_DELAY)

    print(f"\n{'='*55}")
    print(f"  Agent complete! {posted} post kiya gaya.")
    print("=" * 55)


if __name__ == "__main__":
    run_agent()
