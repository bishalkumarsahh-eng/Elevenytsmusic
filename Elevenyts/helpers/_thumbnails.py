# ==========================================================
# Copyright (c) 2026 VelocityBots
# All Rights Reserved.
#
# Project      : VelocityBots API Telegram Music Bot
# Powered By   : VelocityBots
# Type         : API Based Telegram Music Bot
#
# Bot          : @JunoXmusic_Robot
# Channel      : https://t.me/junoxmusic_updates
# GitHub       : https://github.com/bishalkumarsahh-eng
#
# Unauthorized copying, modification, or redistribution
# of this source code without permission is prohibited.
# ==========================================================

import asyncio
import io
import os
import re
import textwrap

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pathlib import Path

from Elevenyts import config
from Elevenyts.helpers import Track


# ── canvas ───────────────────────────────────────────────────────────────────
W, H = 1280, 720

# ── card geometry ─────────────────────────────────────────────────────────────
CARD_X, CARD_Y = 52, 68
CARD_W, CARD_H = W - 104, H - 136
CARD_R         = 38

ART_SIZE = CARD_H - 48
ART_X    = CARD_X + 24
ART_Y    = CARD_Y + 24
ART_R    = 26

INFO_X  = ART_X + ART_SIZE + 56
INFO_W  = CARD_X + CARD_W - INFO_X - 36

# ── colour palette ────────────────────────────────────────────────────────────
GREEN  = (29,  215,  84)
TEAL   = (20,  220, 160)
WHITE  = (255, 255, 255)
LGRAY  = (200, 200, 215)

# ── font paths ────────────────────────────────────────────────────────────────
_FONT_BOLD    = "Elevenyts/helpers/Raleway-Bold.ttf"
_FONT_REGULAR = "Elevenyts/helpers/Inter-Light.ttf"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        _FONT_BOLD if bold else _FONT_REGULAR,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"          if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"  if bold else
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default(size=size)


# ════════════════════════════════════════════════════════════════════════════
# BACKGROUND
# ════════════════════════════════════════════════════════════════════════════

def _make_bg(art: Image.Image) -> Image.Image:
    aw, ah = art.size
    scale  = max(W / aw, H / ah)
    nw, nh = int(aw * scale), int(ah * scale)
    bg     = art.convert("RGB").resize((nw, nh), Image.LANCZOS)
    ox, oy = (nw - W) // 2, (nh - H) // 2
    bg     = bg.crop((ox, oy, ox + W, oy + H))
    bg     = bg.filter(ImageFilter.GaussianBlur(radius=2))
    dark   = Image.new("RGB", (W, H), (4, 4, 18))
    bg     = Image.blend(bg, dark, alpha=0.32)
    return bg.convert("RGBA")


# ════════════════════════════════════════════════════════════════════════════
# GLASS PRIMITIVES
# ════════════════════════════════════════════════════════════════════════════

def _rounded_mask(size, r: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size[0]-1, size[1]-1], radius=r, fill=255)
    return m


def _glass_rect(canvas, x0, y0, x1, y1, r,
                blur=22, tint_alpha=18, border_alpha=90,
                shine_alpha=80, inner_alpha=30, border_w=2):
    w, h    = x1-x0, y1-y0
    region  = canvas.crop((x0, y0, x1, y1)).convert("RGBA")
    blurred = region.filter(ImageFilter.GaussianBlur(radius=blur))
    tint    = Image.new("RGBA", (w, h), (255, 255, 255, tint_alpha))
    blurred = Image.alpha_composite(blurred, tint)

    shine   = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd      = ImageDraw.Draw(shine)
    shine_h = min(h // 3, 90)
    for i in range(shine_h):
        a = int(shine_alpha * (1 - (i / shine_h) ** 1.6))
        sd.line([(0, i), (w, i)], fill=(255, 255, 255, a))
    for i in range(min(8, h)):
        a = int(120 * (1 - i / 8))
        sd.line([(int(w*.10), i), (int(w*.70), i)], fill=(255, 255, 255, a))
    blurred = Image.alpha_composite(blurred, shine)

    mask  = _rounded_mask((w, h), r)
    frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    frame.paste(blurred, mask=mask)
    canvas.alpha_composite(frame, (x0, y0))

    d = ImageDraw.Draw(canvas, "RGBA")
    for bw in range(border_w):
        a = max(0, border_alpha - bw * 30)
        d.rounded_rectangle([x0+bw, y0+bw, x1-bw, y1-bw],
                            radius=max(2, r-bw), outline=(255,255,255,a), width=1)
    d.rounded_rectangle(
        [x0+border_w+1, y0+border_w+1, x1-border_w-1, y1-border_w-1],
        radius=max(2, r-border_w-1), outline=(255,255,255,inner_alpha), width=1)
    return canvas


def _glass_pill(canvas, cx, cy, pw, ph, r=None,
                tint_alpha=16, border_alpha=75, shine_alpha=55):
    r  = r if r is not None else ph // 2
    x0 = cx - pw // 2
    y0 = cy - ph // 2
    _glass_rect(canvas, x0, y0, x0+pw, y0+ph, r,
                blur=14, tint_alpha=tint_alpha, border_alpha=border_alpha,
                shine_alpha=shine_alpha, inner_alpha=20, border_w=1)


# ════════════════════════════════════════════════════════════════════════════
# ICONS & CONTROLS
# ════════════════════════════════════════════════════════════════════════════

def _bar(draw, x, y, w, h, pct,
         track=(255,255,255,38), fill=GREEN, dot=WHITE, dot_r=8):
    draw.rounded_rectangle([x, y, x+w, y+h], radius=h//2, fill=track)
    fw = max(0, int(w * min(1.0, max(0.0, pct))))
    if fw > h:
        draw.rounded_rectangle([x, y, x+fw, y+h], radius=h//2, fill=fill)
    cx2, cy2 = x+fw, y+h//2
    draw.ellipse([cx2-dot_r-4, cy2-dot_r-4, cx2+dot_r+4, cy2+dot_r+4], fill=(*dot[:3], 50))
    draw.ellipse([cx2-dot_r-1, cy2-dot_r-1, cx2+dot_r+1, cy2+dot_r+1], fill=(*dot[:3], 90))
    draw.ellipse([cx2-dot_r,   cy2-dot_r,   cx2+dot_r,   cy2+dot_r],   fill=dot)

def _pause(d, cx, cy, col):
    bw, bh = 7, 22
    d.rounded_rectangle([cx-bw-3, cy-bh//2, cx-3,    cy+bh//2], radius=3, fill=col)
    d.rounded_rectangle([cx+3,    cy-bh//2, cx+bw+3, cy+bh//2], radius=3, fill=col)

def _play(d, cx, cy, col):
    d.polygon([(cx-9,cy-16),(cx-9,cy+16),(cx+16,cy)], fill=col)

def _prev_icon(d, cx, cy, col):
    d.rounded_rectangle([cx-14,cy-12,cx-10,cy+12], radius=2, fill=col)
    d.polygon([(cx-9,cy),(cx+10,cy-12),(cx+10,cy+12)], fill=col)

def _next_icon(d, cx, cy, col):
    d.rounded_rectangle([cx+10,cy-12,cx+14,cy+12], radius=2, fill=col)
    d.polygon([(cx+9,cy),(cx-10,cy-12),(cx-10,cy+12)], fill=col)

def _shuffle(d, cx, cy, col):
    d.line([(cx-14,cy-7),(cx-3,cy-7),(cx+14,cy+7)], fill=col, width=3)
    d.line([(cx-14,cy+7),(cx-3,cy+7),(cx+14,cy-7)], fill=col, width=3)
    d.polygon([(cx+14,cy+7),(cx+8,cy+4),(cx+11,cy+12)], fill=col)
    d.polygon([(cx+14,cy-7),(cx+8,cy-12),(cx+11,cy-4)], fill=col)

def _repeat(d, cx, cy, col):
    d.arc([cx-11,cy-9,cx+11,cy+9], start=210, end=330, fill=col, width=3)
    d.arc([cx-11,cy-9,cx+11,cy+9], start=30,  end=150, fill=col, width=3)
    d.polygon([(cx+11,cy),(cx+6,cy-8),(cx+16,cy-8)], fill=col)
    d.polygon([(cx-11,cy),(cx-6,cy+8),(cx-16,cy+8)], fill=col)

def _heart(d, cx, cy, col):
    d.ellipse([cx-10,cy-8,cx,    cy+4], fill=col)
    d.ellipse([cx,   cy-8,cx+10, cy+4], fill=col)
    d.polygon([(cx-13,cy),(cx,cy+14),(cx+13,cy)], fill=col)

def _volume(d, cx, cy, col):
    d.polygon([(cx-10,cy-5),(cx-4,cy-5),(cx+2,cy-10),
               (cx+2,cy+10),(cx-4,cy+5),(cx-10,cy+5)], fill=col)
    d.arc([cx+2,cy-8,  cx+12,cy+8],  start=-55, end=55, fill=col, width=2)
    d.arc([cx+4,cy-13, cx+18,cy+13], start=-55, end=55, fill=col, width=2)

def _eq(draw, x, y, col, h=(9,16,11,7,14)):
    bw, gap, mh = 3, 2, max(h)
    for i, hh in enumerate(h):
        bx = x + i*(bw+gap)
        draw.rounded_rectangle([bx, y+(mh-hh), bx+bw, y+mh], radius=1, fill=col)

def _fmt(s) -> str:
    if isinstance(s, int):
        return f"{s//60}:{s%60:02d}"
    return str(s) if s else "0:00"


# ════════════════════════════════════════════════════════════════════════════
# PLACEHOLDER
# ════════════════════════════════════════════════════════════════════════════

def _placeholder() -> Image.Image:
    img = Image.new("RGB", (600, 600))
    d   = ImageDraw.Draw(img)
    for i in range(600):
        t = i / 600
        d.rectangle([0,i,599,i+1],
                    fill=(int(60+100*t), int(5+30*t), int(100+140*t)))
    glow = Image.new("RGBA", (600,600), (0,0,0,0))
    gd   = ImageDraw.Draw(glow, "RGBA")
    for r in range(200, 0, -8):
        a = int(55*(1-r/200))
        gd.ellipse([300-r,300-r,300+r,300+r], fill=(160,100,255,a))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    ImageDraw.Draw(img).text((220,250), "♫", font=_font(90, bold=True),
                             fill=(220,210,255))
    return img


# ════════════════════════════════════════════════════════════════════════════
# CORE RENDERER
# ════════════════════════════════════════════════════════════════════════════

def _render(art: Image.Image, title: str, artist: str,
            duration: str, is_live: bool = False,
            is_playing: bool = True,
            source_label: str = "PLAYING FROM ALBUM") -> Image.Image:
    """Render a compact sunset music-player thumbnail.

    The layout is intentionally different from the old glass-card design:
    full-bleed sunset background, brush-cut artwork on the left and a clean
    player console on the right.  It is kept at 1280x720 for Telegram previews.
    """
    import math

    # --- warm sunset background (generated locally; no network work) ---
    bg = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    px = bg.load()
    stops = [
        (0.00, (42, 24, 70)),
        (0.22, (113, 54, 87)),
        (0.48, (218, 96, 63)),
        (0.70, (246, 154, 67)),
        (1.00, (55, 48, 86)),
    ]
    for y in range(H):
        t = y / max(1, H - 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                a, ca = stops[i]
                b, cb = stops[i + 1]
                u = (t - a) / max(0.0001, b - a)
                c = tuple(int(ca[k] * (1-u) + cb[k] * u) for k in range(3))
                break
        for x in range(W):
            glow = max(0.0, 1.0 - abs(x - 780) / 850) * max(0.0, 1.0 - abs(t - .64) / .34)
            px[x, y] = (
                min(255, int(c[0] + 35 * glow)),
                min(255, int(c[1] + 22 * glow)),
                min(255, int(c[2] + 8 * glow)),
                255,
            )

    d = ImageDraw.Draw(bg, "RGBA")
    # Soft clouds.
    for cx, cy, rx, ry, alpha in [
        (160, 390, 250, 75, 35), (520, 430, 330, 90, 28),
        (900, 355, 300, 70, 30), (1120, 455, 260, 85, 28),
    ]:
        d.ellipse([cx-rx, cy-ry, cx+rx, cy+ry], fill=(255, 205, 185, alpha))
    # Sun.
    for r in range(105, 10, -5):
        alpha = int(5 + 28 * (1 - r / 105))
        d.ellipse([790-r, 500-r, 790+r, 500+r], fill=(255, 211, 120, alpha))
    d.ellipse([760, 470, 820, 530], fill=(255, 222, 135, 210))
    # Layered mountain silhouettes.
    d.polygon([(0,620),(160,535),(285,590),(430,505),(575,605),(760,520),(930,610),(1100,505),(1280,575),(1280,720),(0,720)],
              fill=(38, 31, 55, 210))
    d.polygon([(0,665),(210,575),(370,640),(560,565),(730,650),(930,565),(1090,640),(1280,555),(1280,720),(0,720)],
              fill=(24, 25, 45, 235))

    # Add a very soft colour wash from the real artwork, without making a
    # second network request or doing expensive blur operations.
    try:
        wash = art.convert("RGB").resize((96, 96), Image.LANCZOS).filter(ImageFilter.GaussianBlur(18))
        wash = wash.resize((W, H), Image.LANCZOS).convert("RGBA")
        bg = Image.blend(bg, wash, alpha=0.10)
    except Exception:
        pass

    canvas = bg.convert("RGBA")

    # Outer player frame.
    d = ImageDraw.Draw(canvas, "RGBA")
    d.rounded_rectangle([10, 10, W-10, H-10], radius=30,
                        fill=(10, 10, 22, 22), outline=(255, 128, 38, 220), width=3)
    d.rounded_rectangle([16, 16, W-16, H-16], radius=26,
                        outline=(255, 215, 170, 55), width=1)

    # --- brush-cut artwork on the left ---
    art_box = (55, 82, 625, 625)
    aw, ah = art_box[2]-art_box[0], art_box[3]-art_box[1]
    art_img = art.convert("RGBA").resize((aw, ah), Image.LANCZOS)
    mask = Image.new("L", (aw, ah), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([28, 28, aw-28, ah-28], radius=28, fill=245)
    # Brush streaks around the portrait.
    rng = __import__('random').Random(hash(title) & 0xffffffff)
    for i in range(34):
        y = rng.randint(20, ah-20)
        x0 = rng.randint(0, 70)
        x1 = rng.randint(aw-100, aw+10)
        thick = rng.randint(4, 16)
        md.rectangle([x0, y, x1, y+thick], fill=rng.randint(135, 220))
    # Cut a few irregular transparent gaps.
    for i in range(18):
        y = rng.randint(0, ah)
        x = rng.choice([rng.randint(0, 80), rng.randint(aw-80, aw)])
        md.line([(x, y), (max(0, x-rng.randint(10,50)), min(ah, y+rng.randint(4,18)))], fill=0, width=rng.randint(2,7))
    canvas.paste(art_img, (art_box[0], art_box[1]), mask)

    d = ImageDraw.Draw(canvas, "RGBA")
    # Thin warm glow around artwork.
    d.rounded_rectangle([art_box[0]+25, art_box[1]+25, art_box[2]-25, art_box[3]-25],
                        radius=28, outline=(255, 145, 65, 85), width=2)

    # Small brand badge.
    d.rounded_rectangle([30, 28, 145, 92], radius=18, fill=(255, 93, 0, 215))
    d.text((62, 35), "V", font=_font(38, bold=True), fill=WHITE)

    # Right player area.
    x = 665
    right = 1220
    width = right - x
    top = 105

    # Top label and status.
    _eq(d, x, top+7, (255, 111, 24, 235), h=(8,15,10,19,13))
    d.text((x+38, top), source_label, font=_font(18, bold=True), fill=(255, 232, 214, 235))
    d.text((right-95, top-3), "♥", font=_font(35, bold=True), fill=(255, 104, 22, 235))
    d.text((right-38, top+2), "···", font=_font(22, bold=True), fill=(35, 24, 30, 235))

    # Song title, safely wrapped by actual pixel width.
    clean_title = re.sub(r"\s+", " ", title).strip() or "Now Playing"
    f_title = _font(39, bold=True)
    words = clean_title.split()
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if d.textbbox((0,0), candidate, font=f_title)[2] <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
        if len(lines) == 3:
            break
    if line and len(lines) < 3:
        lines.append(line)
    ty = top + 48
    for ln in lines[:3]:
        d.text((x, ty), ln, font=f_title, fill=(20, 14, 25, 250))
        ty += 45

    # Artist/source subline.
    if artist:
        artist_clean = re.sub(r"\s+", " ", artist).strip()
        d.text((x, ty+2), artist_clean[:42], font=_font(17), fill=(45, 30, 42, 205))
        ty += 31

    # Equalizer waveform.
    wave_y = 345
    wave_w = width
    bars = 62
    step = wave_w / bars
    seed = sum(ord(c) for c in clean_title) % 997
    for i in range(bars):
        v = (math.sin(i*1.73 + seed) + math.sin(i*.47 + seed*.31) + 2) / 4
        h = 9 + int(v * 45)
        bx = int(x + i * step)
        d.rounded_rectangle([bx, wave_y-h, bx+max(2, int(step*.48)), wave_y],
                            radius=2, fill=(237, 91, 18, 205))

    # Progress bar + times.
    bar_y = 374
    _bar(d, x, bar_y, width, 7, 0.40,
         track=(70, 38, 48, 110), fill=(247, 91, 19, 235), dot=(255,255,255), dot_r=8)
    f_time = _font(15, bold=True)
    d.text((x, bar_y+19), "0:00", font=f_time, fill=(55, 37, 44, 220))
    dur_str = "LIVE" if is_live else _fmt(duration)
    tw = d.textbbox((0,0), dur_str, font=f_time)[2]
    d.text((right-tw, bar_y+19), dur_str, font=f_time, fill=(55, 37, 44, 220))

    # Main transport row.
    cy = 500
    positions = [x+45, x+160, x+width//2, right-160, right-45]
    _shuffle(d, positions[0], cy, (47, 31, 38, 230))
    _prev_icon(d, positions[1], cy, (35, 26, 32, 245))
    # Orange play/pause disc.
    d.ellipse([positions[2]-48, cy-48, positions[2]+48, cy+48], fill=(180, 57, 8, 220), outline=(255, 159, 70, 245), width=3)
    d.ellipse([positions[2]-37, cy-37, positions[2]+37, cy+37], outline=(255, 204, 142, 100), width=2)
    (_pause if is_playing else _play)(d, positions[2], cy, WHITE)
    _next_icon(d, positions[3], cy, (35, 26, 32, 245))
    _repeat(d, positions[4], cy, (47, 31, 38, 230))

    # Volume strip.
    vy = 620
    _volume(d, x+12, vy, (45, 32, 40, 220))
    _bar(d, x+48, vy-4, width-90, 7, 0.52,
         track=(60, 35, 45, 100), fill=(243, 100, 24, 225), dot=(255,245,225), dot_r=7)
    _eq(d, right-42, vy-9, (236, 91, 19, 220), h=(9,18,13,23,15))

    # Small footer branding.
    d.text((55, 655), "VELOCITY MUSIC", font=_font(16, bold=True), fill=(255, 224, 205, 220))
    d.text((right-160, 655), "LIVE TO PLAY", font=_font(14, bold=True), fill=(255, 224, 205, 205))

    return canvas

# ════════════════════════════════════════════════════════════════════════════
# THUMBNAIL CLASS
# ════════════════════════════════════════════════════════════════════════════

class Thumbnail:
    _session = None

    @classmethod
    async def _get_session(cls):
        if cls._session is None or cls._session.closed:
            timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
            cls._session = aiohttp.ClientSession(timeout=timeout)
        return cls._session

    async def save_thumb(self, output_path: str, url: str) -> str:
        session = await self._get_session()
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.read()
        with open(output_path, "wb") as f:
            f.write(data)
        return output_path

    async def generate(self, song: Track, size=(1280, 720)) -> str:
        try:
            os.makedirs("cache", exist_ok=True)
            output = f"cache/{song.id}_sunset.jpg"
            legacy = f"cache/{song.id}_sunset.png"

            if os.path.exists(output):
                return output

            if getattr(song, "thumbnail", None):
                temp = f"cache/temp_{song.id}.jpg"
                try:
                    await self.save_thumb(temp, song.thumbnail)
                    art = Image.open(temp).convert("RGBA")
                except Exception:
                    art = _placeholder().convert("RGBA")
                finally:
                    try:
                        os.remove(temp)
                    except OSError:
                        pass
            else:
                art = _placeholder().convert("RGBA")

            # Use full YouTube title (ytitle) for thumbnail if available, else fall back to title
            _raw_ytitle = str(getattr(song, "ytitle", "") or "").strip()
            _raw_title  = str(getattr(song, "title", "") or "").strip()
            title = re.sub(r"\s+", " ", _raw_ytitle if _raw_ytitle else _raw_title) or "Now Playing"
            artist   = str(getattr(song, "artist",
                           getattr(song, "channel", "")) or "").strip()
            duration = getattr(song, "duration", "0:00") or "0:00"
            is_live  = bool(getattr(song, "is_live", False))

            canvas = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _render(
                    art, title, artist, duration,
                    is_live=is_live,
                    is_playing=True,
                    source_label="PLAYING FROM ALBUM",
                )
            )

            canvas.convert("RGB").save(output, "JPEG", quality=88, optimize=False, progressive=True)
            return output

        except Exception:
            return config.DEFAULT_THUMB
