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
    """Render the compact dark/orange music-player thumbnail.

    Layout is intentionally based on a compact Telegram music-card:
    full-bleed dark artwork backdrop, rounded dark card, large artwork
    on the left, compact metadata/player controls on the right.
    """
    # Full-bleed artwork backdrop, heavily darkened so the UI stays readable.
    aw, ah = art.size
    scale = max(W / max(1, aw), H / max(1, ah))
    bg = art.convert("RGB").resize((int(aw * scale), int(ah * scale)), Image.LANCZOS)
    ox = max(0, (bg.width - W) // 2)
    oy = max(0, (bg.height - H) // 2)
    bg = bg.crop((ox, oy, ox + W, oy + H)).filter(ImageFilter.GaussianBlur(5))
    canvas = bg.convert("RGBA")

    # Dark cinematic wash; this keeps the card compact and legible over any artwork.
    wash = Image.new("RGBA", (W, H), (2, 4, 10, 190))
    canvas = Image.alpha_composite(canvas, wash)

    # Main card — almost full canvas, thin orange outline like the reference.
    x0, y0 = 28, 24
    x1, y1 = W - 28, H - 24
    d = ImageDraw.Draw(canvas, "RGBA")
    d.rounded_rectangle([x0, y0, x1, y1], radius=30, fill=(5, 7, 15, 235), outline=(255, 120, 35, 230), width=2)
    d.rounded_rectangle([x0+5, y0+5, x1-5, y1-5], radius=25, outline=(255, 255, 255, 32), width=1)

    # Subtle orange glow around the frame.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    for n in range(14, 0, -2):
        a = int(18 * (1 - n / 16))
        gd.rounded_rectangle([x0-n, y0-n, x1+n, y1+n], radius=30+n, outline=(255, 105, 25, a), width=2)
    canvas = Image.alpha_composite(canvas, glow)
    d = ImageDraw.Draw(canvas, "RGBA")

    # Geometry: artwork occupies the left ~45%; information remains compact on right.
    art_x, art_y = 70, 106
    art_w, art_h = 520, 492
    info_x = 635
    info_w = 535

    # Artwork: rounded image with a clean dark/orange frame.
    art_scaled = art.convert("RGB")
    scale = max(art_w / max(1, art_scaled.width), art_h / max(1, art_scaled.height))
    art_scaled = art_scaled.resize((int(art_scaled.width * scale), int(art_scaled.height * scale)), Image.LANCZOS)
    ax = max(0, (art_scaled.width - art_w) // 2)
    ay = max(0, (art_scaled.height - art_h) // 2)
    art_scaled = art_scaled.crop((ax, ay, ax + art_w, ay + art_h)).convert("RGBA")
    mask = _rounded_mask((art_w, art_h), 22)
    canvas.paste(art_scaled, (art_x, art_y), mask)

    d = ImageDraw.Draw(canvas, "RGBA")
    d.rounded_rectangle([art_x, art_y, art_x+art_w, art_y+art_h], radius=22, outline=(255, 125, 45, 170), width=2)
    d.rounded_rectangle([art_x+4, art_y+4, art_x+art_w-4, art_y+art_h-4], radius=18, outline=(255,255,255,55), width=1)

    # Creative diagonal matte over the far-right edge of the artwork.
    # It gives the thumbnail a distinctive cut-card look without covering the subject.
    matte = Image.new("RGBA", (art_w, art_h), (0, 0, 0, 0))
    md = ImageDraw.Draw(matte, "RGBA")
    md.polygon([
        (art_w-105, 0), (art_w, 0), (art_w, art_h),
        (art_w-205, art_h), (art_w-72, int(art_h*0.55))
    ], fill=(3, 5, 12, 205))
    canvas.alpha_composite(matte, (art_x, art_y))
    d = ImageDraw.Draw(canvas, "RGBA")

    # Tiny top-left status badge.
    d.rounded_rectangle([45, 42, 126, 90], radius=12, fill=(255, 104, 18, 235))
    d.text((66, 48), "V", font=_font(28, bold=True), fill=WHITE)

    # Tiny brand mark in the bottom-left.
    d.text((70, 638), "VELOCITY MUSIC", font=_font(13, bold=True), fill=(210, 215, 225, 210))
    d.text((W-185, 638), "LIVE TO PLAY", font=_font(13, bold=True), fill=(210, 215, 225, 210))

    # Header on the right.
    header_y = 96
    _eq(d, info_x, header_y+6, (255, 112, 24, 255), h=(7,12,17,10,14))
    d.text((info_x+34, header_y), source_label if not is_live else "LIVE",
           font=_font(16, bold=True), fill=(225, 225, 232, 225))

    # Favorite / more controls.
    _heart(d, W-92, header_y+6, (255, 101, 20, 255))
    d.text((W-54, header_y-3), "···", font=_font(20, bold=True), fill=(210,215,225,210))

    # Song title — deliberately compact, max 3 lines.
    title = re.sub(r"\s+", " ", str(title or "Now Playing")).strip()
    title_font = _font(35, bold=True)
    lines = textwrap.wrap(title, width=27, break_long_words=False, break_on_hyphens=False)[:3]
    ty = 145
    for line in lines:
        d.text((info_x, ty), line, font=title_font, fill=WHITE)
        bb = d.textbbox((info_x, ty), line, font=title_font)
        ty += (bb[3] - bb[1]) + 3

    # Artist is small and unobtrusive; don't let it push controls down.
    if artist:
        artist_clean = re.sub(r"\s+", " ", str(artist)).strip()
        artist_font = _font(15)
        d.text((info_x, min(ty+2, 265)), artist_clean[:52], font=artist_font, fill=(185,190,202,185))

    # Waveform + timeline.
    wave_y = 305
    wave_x = info_x
    wave_w = info_w
    bars = (8, 15, 22, 11, 28, 17, 34, 20, 12, 25, 31, 18, 27, 14, 36,
            20, 12, 29, 17, 23, 13, 30, 18, 25, 16, 34, 21, 12, 28, 19,
            31, 14, 23, 18, 27, 12, 35, 20, 15, 29, 18, 25, 13, 32, 17,
            24, 12, 30, 20, 14, 27, 18, 34, 15, 23, 11, 28, 19, 31, 16)
    gap = 5
    bw = max(3, (wave_w - (len(bars)-1)*gap) // len(bars))
    for i, hh in enumerate(bars):
        bx = wave_x + i*(bw+gap)
        d.rounded_rectangle([bx, wave_y-hh, bx+bw, wave_y], radius=2, fill=(255, 104, 20, 235))

    bar_y = 335
    _bar(d, info_x, bar_y, info_w, 6, 0.40,
         track=(255,255,255,30), fill=(255,104,20,255), dot=WHITE, dot_r=8)
    f_time = _font(13)
    d.text((info_x, 350), "0:00", font=f_time, fill=(155,160,175,180))
    end_text = "LIVE" if is_live else _fmt(duration)
    tw = d.textbbox((0,0), end_text, font=f_time)
    d.text((info_x+info_w-(tw[2]-tw[0]), 350), end_text, font=f_time,
           fill=(155,160,175,180) if not is_live else (255,105,45,255))

    # Compact transport row.
    ctrl_y = 430
    # Keep the transport controls balanced around the true center:
    # BACK  <  PLAY/PAUSE  >  FORWARD
    # Shuffle and repeat remain at the outer edges.
    center_x = info_x + info_w // 2
    positions = [
        info_x + 36,
        center_x - 132,
        center_x,
        center_x + 132,
        info_x + info_w - 36,
    ]
    _shuffle(d, positions[0], ctrl_y, (110,115,130,150))
    _prev_icon(d, positions[1], ctrl_y, (220,222,230,220))

    # Orange circular play/pause button.
    cx = positions[2]
    d.ellipse([cx-40, ctrl_y-40, cx+40, ctrl_y+40], fill=(255,105,20,235), outline=(255,178,90,230), width=2)
    d.ellipse([cx-31, ctrl_y-31, cx+31, ctrl_y+31], fill=(125,45,12,185))
    (_pause if is_playing else _play)(d, cx, ctrl_y, WHITE)

    _next_icon(d, positions[3], ctrl_y, (220,222,230,220))
    _repeat(d, positions[4], ctrl_y, (110,115,130,150))

    # Volume strip at the bottom-right.
    vol_y = 528
    _volume(d, info_x+5, vol_y, (180,185,198,185))
    _bar(d, info_x+40, vol_y-3, info_w-85, 5, 0.55,
         track=(255,255,255,25), fill=(255,104,20,255), dot=WHITE, dot_r=7)
    _eq(d, info_x+info_w-16, vol_y+7, (255,104,20,235), h=(7,14,20,11,17))

    # Small bottom-right live indicator.
    d.text((info_x, 566), "●", font=_font(11, bold=True), fill=(255,105,20,255))
    d.text((info_x+17, 565), "NOW PLAYING", font=_font(12, bold=True), fill=(180,185,198,175))

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
            output = f"cache/{song.id}_darkcard.jpg"
            legacy = f"cache/{song.id}_darkcard.png"

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
