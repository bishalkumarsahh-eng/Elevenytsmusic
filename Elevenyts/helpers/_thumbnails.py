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


# ── canvas ──────────────────────────────────────────────────────────────────
W, H = 1280, 720

# ── card geometry ────────────────────────────────────────────────────────────
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

# ── font paths (match originals, fallback to system fonts) ───────────────────
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
    bg = art.convert("RGB").resize((W, H), Image.LANCZOS)
    for r in (22, 22, 14):
        bg = bg.filter(ImageFilter.GaussianBlur(radius=r))
    dark = Image.new("RGB", (W, H), (4, 4, 14))
    bg   = Image.blend(bg, dark, alpha=0.52)
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
    w, h  = x1-x0, y1-y0
    mask  = _rounded_mask((w, h), r)

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
# PROGRESS BAR + ICONS
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
    """Format seconds int OR pass-through a string like '3:47' or '🔴 LIVE'."""
    if isinstance(s, int):
        return f"{s//60}:{s%60:02d}"
    return str(s) if s else "0:00"


# ════════════════════════════════════════════════════════════════════════════
# ART PANEL — scrim + title text overlay on album art
# ════════════════════════════════════════════════════════════════════════════

def _art_scrim(canvas, title, artist, ax, ay, sz):
    d     = ImageDraw.Draw(canvas, "RGBA")
    scrim = sz // 3 + 16
    for i in range(scrim):
        a = int(215 * (i/scrim)**1.35)
        d.rectangle([ax, ay+sz-scrim+i, ax+sz, ay+sz-scrim+i+1], fill=(0,0,0,a))
    ty  = ay + sz - scrim + 14
    f_b = _font(22, bold=True)
    f_s = _font(14)
    for word in title.upper().split():
        d.text((ax+18, ty), word, font=f_b, fill=WHITE)
        ty += 28
    d.text((ax+18, ty+4), artist, font=f_s, fill=(200,200,200))


# ════════════════════════════════════════════════════════════════════════════
# PLACEHOLDER — used when no thumbnail URL is available
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

    art_sq = art.resize((ART_SIZE, ART_SIZE), Image.LANCZOS)
    canvas = _make_bg(art_sq)

    # main glass card
    _glass_rect(canvas, CARD_X, CARD_Y, CARD_X+CARD_W, CARD_Y+CARD_H,
                r=CARD_R, blur=26, tint_alpha=14, border_alpha=100,
                shine_alpha=90, inner_alpha=35, border_w=2)

    # album art
    mask_art = _rounded_mask((ART_SIZE, ART_SIZE), ART_R)
    canvas.paste(art_sq.convert("RGBA"), (ART_X, ART_Y), mask_art)
    d = ImageDraw.Draw(canvas, "RGBA")
    d.rounded_rectangle([ART_X-2, ART_Y-2, ART_X+ART_SIZE+2, ART_Y+ART_SIZE+2],
                        radius=ART_R+2, outline=(255,255,255,80), width=2)
    d.rounded_rectangle([ART_X-1, ART_Y-1, ART_X+ART_SIZE+1, ART_Y+ART_SIZE+1],
                        radius=ART_R+1, outline=(255,255,255,30), width=1)
    _art_scrim(canvas, title, artist, ART_X, ART_Y, ART_SIZE)

    # right panel
    d  = ImageDraw.Draw(canvas, "RGBA")
    iy = CARD_Y + 48

    # source label row
    _eq(d, INFO_X, iy+3, GREEN)
    label = "🔴  LIVE" if is_live else source_label
    d.text((INFO_X+38, iy), label, font=_font(13), fill=(*LGRAY, 210))
    iy += 38

    # song title (up to 2 lines)
    f_ttl  = _font(50, bold=True)
    max_ch = max(1, int(INFO_W / 27))
    lines  = textwrap.wrap(title, width=max_ch)[:2]
    for ln in lines:
        d.text((INFO_X, iy), ln, font=f_ttl, fill=WHITE)
        bb = d.textbbox((INFO_X, iy), ln, font=f_ttl)
        iy += bb[3] - bb[1] + 4
    iy += 6

    # artist + verified badge
    f_art = _font(22)
    d.text((INFO_X, iy), artist, font=f_art, fill=LGRAY)
    ab  = d.textbbox((INFO_X, iy), artist, font=f_art)
    bx  = ab[2] + 14
    by  = iy + (ab[3]-ab[1])//2
    d.ellipse([bx-12, by-12, bx+12, by+12], fill=(*GREEN, 40))
    d.ellipse([bx-10, by-10, bx+10, by+10], fill=GREEN)
    d.text((bx-5, by-8), "✓", font=_font(13, bold=True), fill=(10,10,10))

    # heart + more pills
    rx = CARD_X + CARD_W - 36
    ry = CARD_Y + 48
    _glass_pill(canvas, rx-64, ry, 52, 38, r=19, tint_alpha=20, border_alpha=85, shine_alpha=60)
    d = ImageDraw.Draw(canvas, "RGBA")
    _heart(d, rx-64, ry, GREEN)
    _glass_pill(canvas, rx-4, ry, 52, 38, r=19, tint_alpha=20, border_alpha=85, shine_alpha=60)
    d = ImageDraw.Draw(canvas, "RGBA")
    d.text((rx-22, ry-10), "···", font=_font(22, bold=True), fill=LGRAY)

    iy += 50

    # progress bar (fixed at ~40% for static thumbnail)
    bar_y = iy + 18
    d = ImageDraw.Draw(canvas, "RGBA")
    _bar(d, INFO_X, bar_y, INFO_W, 5, 0.40,
         track=(255,255,255,40), fill=GREEN, dot=WHITE, dot_r=8)

    iy = bar_y + 34
    f_t = _font(16)
    d.text((INFO_X, iy), "0:00", font=f_t, fill=LGRAY)
    dur_str = "🔴 LIVE" if is_live else _fmt(duration)
    tw = d.textbbox((0,0), dur_str, font=f_t)
    d.text((INFO_X+INFO_W-(tw[2]-tw[0]), iy), dur_str,
           font=f_t, fill=(255,80,80) if is_live else LGRAY)

    iy += 52

    # transport controls
    ctrl_y = iy + 6
    mid    = INFO_X + INFO_W // 2
    sp     = 74
    d = ImageDraw.Draw(canvas, "RGBA")
    _shuffle(d, mid - sp*2, ctrl_y, LGRAY)
    d.ellipse([mid-sp*2-3, ctrl_y+23, mid-sp*2+3, ctrl_y+29], fill=GREEN)
    _prev_icon(d, mid - sp, ctrl_y, WHITE)

    _glass_pill(canvas, mid, ctrl_y, 78, 78, r=39,
                tint_alpha=210, border_alpha=200, shine_alpha=130)
    d = ImageDraw.Draw(canvas, "RGBA")
    (_pause if is_playing else _play)(d, mid, ctrl_y, (12,12,22))

    _next_icon(d, mid + sp, ctrl_y, WHITE)
    _repeat(d, mid + sp*2, ctrl_y, LGRAY)
    d.ellipse([mid+sp*2-3, ctrl_y+23, mid+sp*2+3, ctrl_y+29], fill=GREEN)

    # volume strip
    bot_y = CARD_Y + CARD_H - 60
    _glass_rect(canvas, INFO_X-12, bot_y, CARD_X+CARD_W-12, bot_y+46,
                r=23, blur=18, tint_alpha=12, border_alpha=80,
                shine_alpha=55, inner_alpha=22, border_w=1)
    d = ImageDraw.Draw(canvas, "RGBA")
    vx, vy = INFO_X+4, bot_y+23
    _volume(d, vx, vy, LGRAY)
    _bar(d, vx+30, vy-3, INFO_W-108, 4, 0.52,
         track=(255,255,255,38), fill=TEAL, dot=WHITE, dot_r=7)
    ri = CARD_X + CARD_W - 22
    for sym in ["⊞", "⊡", "⤢"]:
        d.text((ri-24, bot_y+14), sym, font=_font(18), fill=LGRAY)
        ri -= 40

    # UPGRADE pill
    _glass_pill(canvas, W-126, 30, 90, 30, r=15,
                tint_alpha=16, border_alpha=80, shine_alpha=55)
    d = ImageDraw.Draw(canvas, "RGBA")
    d.text((W-164, 19), "UPGRADE", font=_font(13, bold=True), fill=WHITE)
    d.text((W-60,  18), "🔔",      font=_font(18),             fill=LGRAY)
    d.text((W-28,  18), "···",     font=_font(18, bold=True),  fill=LGRAY)

    return canvas


# ════════════════════════════════════════════════════════════════════════════
# THUMBNAIL CLASS — exact same public API as the original
# ════════════════════════════════════════════════════════════════════════════

class Thumbnail:

    async def save_thumb(self, output_path: str, url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                with open(output_path, "wb") as f:
                    f.write(await resp.read())
        return output_path

    async def generate(self, song: Track, size=(1280, 720)) -> str:
        """
        Drop-in replacement — same signature as the original.
        Returns the path to the generated PNG, or config.DEFAULT_THUMB on error.
        """
        try:
            os.makedirs("cache", exist_ok=True)
            output = f"cache/{song.id}_ultra.png"

            if os.path.exists(output):
                return output

            # download thumbnail
            art: Image.Image
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

            # extract metadata
            title    = re.sub(r"\s+", " ",
                              str(getattr(song, "title", "") or "Now Playing")).strip() \
                       or "Now Playing"
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

            canvas.convert("RGB").save(output, "PNG", optimize=True)
            return output

        except Exception:
            return config.DEFAULT_THUMB
