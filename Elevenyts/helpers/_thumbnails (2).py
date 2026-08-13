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
import os
import re
import asyncio
import aiohttp
import base64

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont
)

from Elevenyts import config
from Elevenyts.helpers import Track


PANEL_W, PANEL_H = 1030, 610
PANEL_X = (1280 - PANEL_W) // 2
PANEL_Y = 55

THUMB_W, THUMB_H = 930, 420
THUMB_X = PANEL_X + (PANEL_W - THUMB_W) // 2
THUMB_Y = PANEL_Y + 30

TITLE_X = THUMB_X + 5
TITLE_Y = THUMB_Y + THUMB_H + 25

META_Y = TITLE_Y + 58

BAR_X = THUMB_X + 5
BAR_Y = META_Y + 60

BAR_RED_LEN = 330
BAR_TOTAL_LEN = 920

ICONS_W, ICONS_H = 420, 45
ICONS_X = PANEL_X + (PANEL_W - ICONS_W) // 2
ICONS_Y = BAR_Y + 65

MAX_TITLE_WIDTH = 820

_f = "QXJ0aXN0Ym90cw=="


def _decode_f():
    decoded = base64.b64decode(_f).decode("utf-8")
    return f"✦ {decoded} ✦"


def trim_to_width(text: str, font, max_w: int) -> str:
    ellipsis = "…"
    if font.getlength(text) <= max_w:
        return text
    for i in range(len(text) - 1, 0, -1):
        if font.getlength(text[:i] + ellipsis) <= max_w:
            return text[:i] + ellipsis
    return ellipsis


def draw_rounded_rect_border_glow(draw, box, radius, color, width, glow_color, glow_spread):
    """Draw a glowing rounded rectangle border."""
    x0, y0, x1, y1 = box
    for i in range(glow_spread, 0, -1):
        alpha = int(80 * (i / glow_spread))
        gc = (*glow_color[:3], alpha)
        draw.rounded_rectangle(
            (x0 - i, y0 - i, x1 + i, y1 + i),
            radius=radius + i,
            outline=gc,
            width=1
        )
    draw.rounded_rectangle(box, radius=radius, outline=color, width=width)


class Thumbnail:

    def __init__(self):
        try:
            self.title_font = ImageFont.truetype(
                "Elevenyts/helpers/Raleway-Bold.ttf", 42)
            self.regular_font = ImageFont.truetype(
                "Elevenyts/helpers/Inter-Light.ttf", 24)
            self.signature_font = ImageFont.truetype(
                "Elevenyts/helpers/Raleway-Bold.ttf", 26)
            self.small_font = ImageFont.truetype(
                "Elevenyts/helpers/Inter-Light.ttf", 20)
        except OSError:
            self.title_font = ImageFont.load_default()
            self.regular_font = ImageFont.load_default()
            self.signature_font = ImageFont.load_default()
            self.small_font = ImageFont.load_default()

    async def save_thumb(self, output_path: str, url: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                with open(output_path, "wb") as f:
                    f.write(await resp.read())
        return output_path

    async def generate(self, song: Track, size=(1280, 720)) -> str:
        try:
            temp = f"cache/temp_{song.id}.jpg"
            output = f"cache/{song.id}_ultra.png"
            if os.path.exists(output):
                return output
            await self.save_thumb(temp, song.thumbnail)
            return await asyncio.get_event_loop().run_in_executor(
                None, self._generate_sync, temp, output, song, size)
        except Exception:
            return config.DEFAULT_THUMB

    def _generate_sync(self, temp, output, song, size=(1280, 720)):
        try:
            W, H = size  # 1280, 720

            # ── 1. Background ─────────────────────────────────────────
            with Image.open(temp) as tmp:
                base = tmp.resize(size).convert("RGBA")

            bg = base.filter(ImageFilter.GaussianBlur(32))
            bg = ImageEnhance.Brightness(bg).enhance(0.22)
            bg = ImageEnhance.Contrast(bg).enhance(1.5)

            # Radial vignette overlay (dark edges)
            vignette = Image.new("RGBA", size, (0, 0, 0, 0))
            vd = ImageDraw.Draw(vignette)
            for i in range(60, 0, -1):
                alpha = int(160 * (1 - i / 60))
                spread = i * 6
                vd.ellipse(
                    (W // 2 - spread, H // 2 - spread * 9 // 16,
                     W // 2 + spread, H // 2 + spread * 9 // 16),
                    fill=(0, 0, 0, alpha)
                )
            bg = Image.alpha_composite(bg, vignette)

            # Subtle dark overlay
            dark = Image.new("RGBA", size, (0, 0, 0, 100))
            bg = Image.alpha_composite(bg, dark)

            draw = ImageDraw.Draw(bg)

            # ── 2. Glass panel with glow border ───────────────────────
            panel = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 0))
            pd = ImageDraw.Draw(panel)

            # Outer glow rings
            CYAN = (0, 255, 255)
            for gi in range(8, 0, -1):
                ga = int(35 * (gi / 8))
                pd.rounded_rectangle(
                    (0 - gi, 0 - gi, PANEL_W - 1 + gi, PANEL_H - 1 + gi),
                    radius=42 + gi,
                    outline=(0, 220, 255, ga),
                    width=1
                )

            # Glass fill
            pd.rounded_rectangle(
                (0, 0, PANEL_W - 1, PANEL_H - 1),
                radius=42,
                fill=(8, 8, 18, 165)
            )
            # Inner border
            pd.rounded_rectangle(
                (0, 0, PANEL_W - 1, PANEL_H - 1),
                radius=42,
                outline=(0, 255, 255, 230),
                width=2
            )
            # Subtle inner highlight (top edge)
            pd.rounded_rectangle(
                (3, 3, PANEL_W - 4, PANEL_H // 3),
                radius=40,
                outline=(255, 255, 255, 18),
                width=1
            )

            pmask = Image.new("L", (PANEL_W, PANEL_H), 0)
            ImageDraw.Draw(pmask).rounded_rectangle(
                (0, 0, PANEL_W, PANEL_H), radius=42, fill=255)
            bg.paste(panel, (PANEL_X, PANEL_Y), pmask)

            # ── 3. Thumbnail image with border glow ───────────────────
            thumb = base.resize((THUMB_W, THUMB_H))

            # Glow frame behind thumbnail
            glow_layer = Image.new("RGBA", size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
            for gi in range(10, 0, -1):
                ga = int(50 * (gi / 10))
                gd.rounded_rectangle(
                    (THUMB_X - gi, THUMB_Y - gi,
                     THUMB_X + THUMB_W + gi, THUMB_Y + THUMB_H + gi),
                    radius=28 + gi,
                    fill=(0, 200, 255, ga)
                )
            bg = Image.alpha_composite(bg, glow_layer)
            draw = ImageDraw.Draw(bg)

            tmask = Image.new("L", thumb.size, 0)
            ImageDraw.Draw(tmask).rounded_rectangle(
                (0, 0, THUMB_W, THUMB_H), radius=26, fill=255)
            bg.paste(thumb, (THUMB_X, THUMB_Y), tmask)

            # Thin cyan border around thumbnail
            draw.rounded_rectangle(
                (THUMB_X, THUMB_Y, THUMB_X + THUMB_W, THUMB_Y + THUMB_H),
                radius=26, outline=(0, 255, 255, 160), width=2
            )

            # ── 4. Cyan accent bar + Title ────────────────────────────
            # Vertical accent bar
            draw.rounded_rectangle(
                (TITLE_X, TITLE_Y + 2, TITLE_X + 5, TITLE_Y + 46),
                radius=3, fill=(0, 255, 255)
            )

            clean_title = re.sub(r"\W+", " ", song.title).title() + " | Moon_Music"
            final_title = trim_to_width(clean_title, self.title_font, MAX_TITLE_WIDTH)

            # Drop shadow
            draw.text((TITLE_X + 13, TITLE_Y + 3), final_title,
                      fill=(0, 0, 0, 160), font=self.title_font)
            # Main title
            draw.text((TITLE_X + 12, TITLE_Y + 1), final_title,
                      fill=(255, 255, 255), font=self.title_font)

            # ── 5. Meta info ──────────────────────────────────────────
            meta_text = f"▷  Now Playing   ·   YouTube   ·   {song.view_count or 'Unknown Views'}"
            draw.text((TITLE_X + 12, META_Y), meta_text,
                      fill=(140, 200, 220), font=self.regular_font)

            # ── 6. Progress bar ───────────────────────────────────────
            # Track BG
            draw.rounded_rectangle(
                (BAR_X, BAR_Y - 5, BAR_X + BAR_TOTAL_LEN, BAR_Y + 5),
                radius=12, fill=(45, 45, 55)
            )
            # Played portion
            draw.rounded_rectangle(
                (BAR_X, BAR_Y - 5, BAR_X + BAR_RED_LEN, BAR_Y + 5),
                radius=12, fill=(0, 220, 255)
            )
            # Knob glow
            kx = BAR_X + BAR_RED_LEN
            for gi in range(8, 0, -1):
                ga = int(60 * (gi / 8))
                draw.ellipse(
                    (kx - 10 - gi, BAR_Y - 10 - gi,
                     kx + 10 + gi, BAR_Y + 10 + gi),
                    fill=(0, 200, 255, ga)
                )
            # Knob
            draw.ellipse(
                (kx - 10, BAR_Y - 10, kx + 10, BAR_Y + 10),
                fill=(0, 255, 255)
            )
            draw.ellipse(
                (kx - 5, BAR_Y - 5, kx + 5, BAR_Y + 5),
                fill=(255, 255, 255)
            )

            # Time stamps
            draw.text((BAR_X, BAR_Y + 18), "00:00",
                      fill=(180, 180, 180), font=self.small_font)
            is_live = getattr(song, "is_live", False)
            end_text = "🔴 LIVE" if is_live else song.duration
            tw = self.small_font.getlength(end_text)
            draw.text((BAR_X + BAR_TOTAL_LEN - tw, BAR_Y + 18),
                      end_text,
                      fill=(0, 255, 255) if is_live else (180, 180, 180),
                      font=self.small_font)

            # ── 7. Play icons ─────────────────────────────────────────
            icons_path = "Elevenyts/helpers/play_icons.png"
            if os.path.isfile(icons_path):
                with Image.open(icons_path) as icons_img:
                    ic = icons_img.resize((ICONS_W, ICONS_H)).convert("RGBA")
                    r, g, b, a = ic.split()
                    cyan_ic = Image.merge("RGBA", (
                        r.point(lambda _: 0),
                        g.point(lambda _: 220),
                        b.point(lambda _: 255),
                        a
                    ))
                    bg.paste(cyan_ic, (ICONS_X, ICONS_Y), cyan_ic)

            bg.save(output)
            try:
                os.remove(temp)
            except OSError:
                pass
            return output

        except Exception:
            return config.DEFAULT_THUMB
