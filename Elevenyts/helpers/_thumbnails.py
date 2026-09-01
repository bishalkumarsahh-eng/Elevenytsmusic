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
            source_label: str = "NOW PLAYING") -> Image.Image:
    """Fast editorial music thumbnail.

    The artwork is treated as the main artist/track visual instead of a small
    album card.  Everything is rendered locally with a small blurred preview
    for the background, keeping generation considerably faster than the old
    full-resolution effects.
    """
    from PIL import ImageOps
    import math

    # ── Fast background: tiny blurred artwork + dark overlay ────────────────
    src = art.convert("RGB")
    bg_small = ImageOps.fit(src, (96, 54), method=Image.Resampling.BILINEAR)
    bg_small = bg_small.filter(ImageFilter.GaussianBlur(7))
    bg = bg_small.resize((W, H), Image.Resampling.BILINEAR).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (5, 6, 12, 205))
    bg = Image.alpha_composite(bg, overlay)

    # Subtle warm/orange wash used by the new editorial style.
    wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wash, "RGBA")
    wd.ellipse([30, 35, 760, 760], fill=(255, 120, 20, 34))
    wd.ellipse([650, -160, 1450, 620], fill=(255, 80, 20, 18))
    bg = Image.alpha_composite(bg, wash)

    canvas = bg
    d = ImageDraw.Draw(canvas, "RGBA")

    # ── Outer editorial frame ───────────────────────────────────────────────
    d.rounded_rectangle([14, 14, W-14, H-14], radius=30,
                        fill=(5, 6, 12, 80), outline=(218, 143, 55, 210), width=2)
    d.rounded_rectangle([21, 21, W-21, H-21], radius=26,
                        outline=(255, 255, 255, 28), width=1)

    # ── Left: large artist/track photo ─────────────────────────────────────
    # Deliberately large and edge-to-edge: this is the main visual identity.
    ax0, ay0, ax1, ay1 = 38, 40, 700, 650
    aw, ah = ax1-ax0, ay1-ay0
    photo = ImageOps.fit(src, (aw, ah), method=Image.Resampling.LANCZOS,
                         centering=(0.5, 0.48)).convert("RGBA")

    # Dark lower/side vignette so artist/title treatment remains readable.
    vignette = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette, "RGBA")
    for i in range(12):
        a = int(95 * (i + 1) / 12)
        vd.rectangle([0, ah-i*7, aw, ah], fill=(0, 0, 0, a))
    photo = Image.alpha_composite(photo, vignette)

    # Rounded photo mask with an irregular/editorial edge impression.
    pmask = _rounded_mask((aw, ah), 34)
    canvas.paste(photo, (ax0, ay0), pmask)

    # Thin double border around photo.
    d = ImageDraw.Draw(canvas, "RGBA")
    d.rounded_rectangle([ax0, ay0, ax1, ay1], radius=34,
                        outline=(255, 255, 255, 115), width=2)
    d.rounded_rectangle([ax0+8, ay0+8, ax1-8, ay1-8], radius=28,
                        outline=(255, 141, 35, 105), width=1)

    # Large circular accent behind/over the artist image.
    cx, cy = 330, 275
    for r, a in [(205, 18), (190, 28), (176, 42)]:
        d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(255, 150, 35, a), width=2)
    d.arc([cx-190, cy-190, cx+190, cy+190], 215, 325,
           fill=(255, 151, 38, 220), width=5)

    # Editorial brush strokes behind the lower title.
    d.polygon([(58, 535), (475, 515), (620, 540), (500, 582), (65, 574)],
              fill=(10, 10, 14, 180))
    d.line([(60, 588), (510, 570)], fill=(255, 128, 24, 210), width=4)
    d.line([(92, 597), (430, 583)], fill=(255, 255, 255, 70), width=1)

    # Brand mark.
    d.rounded_rectangle([42, 30, 175, 84], radius=16,
                        fill=(8, 8, 14, 210), outline=(255, 255, 255, 90), width=1)
    d.text((66, 34), "V", font=_font(34, bold=True), fill=(255, 151, 38, 255))
    d.text((108, 45), "VELOCITY", font=_font(13, bold=True), fill=WHITE)

    # Photo labels.
    d.rounded_rectangle([58, 605, 210, 640], radius=14,
                        fill=(8, 8, 14, 210), outline=(255, 128, 25, 100), width=1)
    d.text((76, 613), "ARTIST / NOW PLAYING", font=_font(12, bold=True),
           fill=(255, 220, 185, 235))

    # ── Right: clean editorial player console ───────────────────────────────
    x, right = 760, 1228
    width = right - x
    top = 75

    # Header.
    _eq(d, x, top+8, (255, 126, 28, 245), h=(8,16,11,20,13))
    d.text((x+38, top), source_label, font=_font(17, bold=True),
           fill=(255, 178, 80, 245))
    d.text((right-58, top-7), "♡", font=_font(39, bold=True), fill=(255, 144, 36, 245))

    # Title: large, white, maximum 3 lines.
    clean_title = re.sub(r"\s+", " ", title).strip() or "Now Playing"
    f_title = _font(38, bold=True)
    words = clean_title.split()
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if d.textbbox((0, 0), candidate, font=f_title)[2] <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
        if len(lines) >= 2:
            break
    if line and len(lines) < 3:
        lines.append(line)
    ty = top + 58
    for ln in lines[:3]:
        d.text((x, ty), ln, font=f_title, fill=WHITE)
        ty += 43

    artist_clean = re.sub(r"\s+", " ", str(artist or "")).strip()
    if artist_clean:
        d.text((x, ty+4), artist_clean[:48], font=_font(17),
               fill=(203, 190, 200, 220))
        ty += 38

    # Accent separator.
    d.line([(x, ty+3), (x+95, ty+3)], fill=(255, 128, 26, 245), width=4)
    d.line([(x+105, ty+3), (right, ty+3)], fill=(255, 255, 255, 35), width=2)

    # Waveform.
    wave_y = ty + 58
    bars = 56
    step = width / bars
    seed = sum(ord(c) for c in clean_title) % 997
    for i in range(bars):
        v = (math.sin(i*1.71 + seed) + math.sin(i*.43 + seed*.17) + 2) / 4
        h = 8 + int(v * 42)
        bx = int(x + i * step)
        fill = (255, 135, 30, 225) if i < bars*.62 else (172, 78, 35, 175)
        d.rounded_rectangle([bx, wave_y-h, bx+max(2, int(step*.48)), wave_y],
                            radius=2, fill=fill)

    # Progress.
    bar_y = wave_y + 28
    _bar(d, x, bar_y, width, 6, 0.42,
         track=(255, 255, 255, 32), fill=(255, 128, 25, 245),
         dot=WHITE, dot_r=7)
    f_time = _font(14, bold=True)
    d.text((x, bar_y+15), "0:00", font=f_time, fill=(190, 185, 195, 210))
    dur_str = "LIVE" if is_live else _fmt(duration)
    tw = d.textbbox((0, 0), dur_str, font=f_time)[2]
    d.text((right-tw, bar_y+15), dur_str, font=f_time, fill=(190, 185, 195, 210))

    # Controls.
    cy = 405
    gap = width / 4
    positions = [x+28, int(x+gap), int(x+width/2), int(x+width-gap), right-28]
    _shuffle(d, positions[0], cy, (226, 216, 222, 215))
    _prev_icon(d, positions[1], cy, WHITE)

    # Distinctive central control.
    d.ellipse([positions[2]-44, cy-44, positions[2]+44, cy+44],
               fill=(255, 129, 26, 245), outline=(255, 208, 150, 235), width=3)
    d.ellipse([positions[2]-52, cy-52, positions[2]+52, cy+52],
               outline=(255, 142, 40, 75), width=2)
    (_pause if is_playing else _play)(d, positions[2], cy, WHITE)
    _next_icon(d, positions[3], cy, WHITE)
    _repeat(d, positions[4], cy, (226, 216, 222, 215))

    # Volume.
    vy = 500
    _volume(d, x+8, vy, (210, 204, 215, 205))
    _bar(d, x+42, vy-4, width-78, 6, 0.56,
         track=(255, 255, 255, 30), fill=(255, 128, 25, 220),
         dot=(255, 255, 255), dot_r=6)

    # Tiny status row.
    d.text((x, 548), "HIGH QUALITY  •  MUSIC 24/7", font=_font(12, bold=True),
           fill=(255, 177, 88, 215))
    d.text((right-150, 548), "FAST • SECURE", font=_font(12, bold=True),
           fill=(215, 205, 215, 185))

    # ── Bottom feature rail ─────────────────────────────────────────────────
    rail = (38, 665, 1242, 704)
    d.rounded_rectangle(rail, radius=18, fill=(6, 7, 13, 220),
                        outline=(255, 255, 255, 45), width=1)
    items = [
        (70, "ϟ", "HIGH QUALITY"),
        (360, "↓", "FAST DOWNLOAD"),
        (690, "◇", "100% SECURE"),
        (1005, "➤", "ADD ME TO GROUP"),
    ]
    for px, icon, label in items:
        d.text((px, 671), icon, font=_font(22, bold=True), fill=(255, 139, 34, 245))
        d.text((px+30, 675), label, font=_font(12, bold=True), fill=WHITE)

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
            output = f"cache/{song.id}_editorial.jpg"
            legacy = f"cache/{song.id}_editorial.png"

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
