# ==========================================================
# VelocityBots — Daily Couple Shipping + Couple PFP
# ==========================================================

import hashlib
import html
import os
import random
import tempfile
from datetime import datetime, timedelta
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from pyrogram import filters, types
from pyrogram.enums import ChatType

from Elevenyts import app, db


SHIPPING_COLLECTION = "daily_shipping"
FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "helpers", "Raleway-Bold.ttf")


def _seeded_score(chat_id: int, user_a: int, user_b: int, stamp: str) -> int:
    raw = f"{chat_id}:{min(user_a, user_b)}:{max(user_a, user_b)}:{stamp}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return 50 + (int(digest[:8], 16) % 51)


def _tier(score: int) -> tuple[str, str]:
    if score >= 95:
        return "💍 Soulmates", "The stars have basically signed the marriage papers."
    if score >= 85:
        return "💖 Perfect Match", "This ship is dangerously adorable."
    if score >= 75:
        return "💕 Strong Chemistry", "There is definitely something going on here."
    if score >= 60:
        return "💗 Cute Pair", "A little spark could turn into something bigger."
    return "💔 Chaotic Duo", "The chemistry is questionable, but the entertainment is guaranteed."


def _ship_name(first: str, second: str) -> str:
    a = "".join(c for c in first if c.isalnum())[: max(1, len(first) // 2)]
    b = "".join(c for c in second if c.isalnum())[-max(1, len(second) // 2):]
    name = (a + b).strip()
    return name[:24] if name else "MysteryShip"


def _mention(user: types.User) -> str:
    name = html.escape(user.first_name or "Unknown")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


async def _get_eligible_members(chat_id: int) -> list[types.User]:
    members = []
    seen = set()
    try:
        async for member in app.get_chat_members(chat_id):
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                continue
            if user.id in seen:
                continue
            seen.add(user.id)
            members.append(user)
    except Exception:
        return []
    return members


async def _load_active_ship(chat_id: int):
    doc = await db.db[SHIPPING_COLLECTION].find_one({"_id": chat_id})
    if not doc:
        return None
    expires = doc.get("expires_at")
    if not isinstance(expires, datetime):
        return None
    if expires > datetime.utcnow():
        return doc
    try:
        await db.db[SHIPPING_COLLECTION].delete_one({"_id": chat_id})
    except Exception:
        pass
    return None


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _initial_avatar(name: str, size: int, hue_seed: int) -> Image.Image:
    # A clean fallback when a user has no accessible profile photo.
    img = Image.new("RGB", (size, size), (80 + hue_seed % 100, 55 + hue_seed % 80, 120 + hue_seed % 80))
    d = ImageDraw.Draw(img)
    letter = (name or "?").strip()[0].upper()
    box = d.textbbox((0, 0), letter, font=_font(size // 2))
    d.text(((size - (box[2] - box[0])) / 2, (size - (box[3] - box[1])) / 2 - box[1]), letter, font=_font(size // 2), fill="white")
    return img


async def _download_avatar(user: types.User, size: int, hue_seed: int) -> Image.Image:
    try:
        photos = []
        async for photo in app.get_chat_photos(user.id, limit=1):
            photos.append(photo)
        if photos:
            with tempfile.TemporaryDirectory() as td:
                path = await app.download_media(photos[0].file_id, file_name=os.path.join(td, "avatar.jpg"))
                if path and os.path.exists(path):
                    return Image.open(path).convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    except Exception:
        pass
    return _initial_avatar(user.first_name or "?", size, hue_seed)


def _circle_avatar(img: Image.Image, size: int, border: int = 10, ring=(255, 255, 255, 235)) -> Image.Image:
    img = ImageOps.fit(img.convert("RGB"), (size, size), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    d = ImageDraw.Draw(out)
    d.ellipse((border // 2, border // 2, size - border // 2, size - border // 2), outline=ring, width=border)
    return out


def _center_text(draw, text, y, font, fill="white", W=1280):
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((W - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)


def _draw_neon_heart(draw, cx, cy, size, outline, width=10):
    # Stylized heart made from two arcs + lower point.
    r = size * 0.30
    top = cy - size * 0.20
    left_box = (cx - r * 2.0, top - r * 0.35, cx, top + r * 1.25)
    right_box = (cx, top - r * 0.35, cx + r * 2.0, top + r * 1.25)
    draw.arc(left_box, 190, 350, fill=outline, width=width)
    draw.arc(right_box, 190, 350, fill=outline, width=width)
    pts = [(cx - r * 1.75, top + r * 0.58), (cx, cy + size * 0.42), (cx + r * 1.75, top + r * 0.58)]
    draw.line(pts, fill=outline, width=width, joint="curve")


def _draw_crown(draw, cx, cy, scale, outline):
    pts = [
        (cx - 55*scale, cy + 20*scale),
        (cx - 40*scale, cy - 25*scale),
        (cx - 10*scale, cy + 0*scale),
        (cx + 15*scale, cy - 32*scale),
        (cx + 38*scale, cy + 0*scale),
        (cx + 58*scale, cy - 22*scale),
        (cx + 50*scale, cy + 30*scale),
        (cx - 48*scale, cy + 30*scale),
        (cx - 55*scale, cy + 20*scale),
    ]
    draw.line(pts, fill=outline, width=max(3, int(7*scale)), joint="curve")
    draw.line((cx-45*scale, cy+30*scale, cx+48*scale, cy+30*scale), fill=outline, width=max(3, int(7*scale)))


async def _make_couple_pfp(first: types.User, second: types.User, score: int, chat_id: int) -> str:
    """Create a 16:9 Match Report image modeled on the user's reference design."""
    seed = int(hashlib.sha256(
        f"{chat_id}:{min(first.id, second.id)}:{max(first.id, second.id)}:{datetime.utcnow().date()}".encode()
    ).hexdigest()[:12], 16)
    rng = random.Random(seed)

    W, H = 1280, 720
    # Dark blurred romantic background.
    base = Image.new("RGB", (W, H), (12, 14, 32))
    bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    blobs = [
        (170, 190, 190, (34, 80, 190, 150)),
        (1080, 170, 210, (180, 35, 125, 145)),
        (640, 360, 240, (95, 15, 110, 100)),
        (120, 620, 180, (15, 90, 145, 110)),
        (1160, 620, 180, (170, 25, 90, 110)),
    ]
    for x, y, r, c in blobs:
        bd.ellipse((x-r, y-r, x+r, y+r), fill=c)
    for _ in range(38):
        x, y = rng.randint(0, W), rng.randint(0, H)
        r = rng.randint(5, 28)
        c = (255, rng.randint(80, 190), rng.randint(160, 240), rng.randint(20, 80))
        bd.ellipse((x-r, y-r, x+r, y+r), fill=c)
    bg = bg.filter(ImageFilter.GaussianBlur(48))
    base = Image.alpha_composite(base.convert("RGBA"), bg)

    # Thin white frame + subtle neon edge.
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((12, 12, W-12, H-12), radius=10, outline=(255,255,255,245), width=3)
    d.rounded_rectangle((18, 18, W-18, H-18), radius=8, outline=(238,95,255,145), width=2)

    # Fetch real Telegram profile photos.
    avatar_size = 330
    first_img = await _download_avatar(first, avatar_size, seed)
    second_img = await _download_avatar(second, avatar_size, seed >> 8)
    av1 = _circle_avatar(first_img, avatar_size, 10, (242, 246, 255, 245))
    av2 = _circle_avatar(second_img, avatar_size, 10, (242, 246, 255, 245))

    # Glows behind avatars.
    for x, ring in ((225, (90, 145, 255, 120)), (1055, (255, 80, 220, 120))):
        glow = Image.new("RGBA", (avatar_size+80, avatar_size+80), (0,0,0,0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((40,40,avatar_size+40,avatar_size+40), outline=ring, width=24)
        glow = glow.filter(ImageFilter.GaussianBlur(22))
        base.alpha_composite(glow, (x-(avatar_size+80)//2, 185-(avatar_size+80)//2))

    base.alpha_composite(av1, (60, 190))
    base.alpha_composite(av2, (890, 190))
    d = ImageDraw.Draw(base)

    # Crowns above portraits.
    _draw_crown(d, 225, 145, 0.95, (255, 236, 170, 255))
    _draw_crown(d, 1055, 145, 0.95, (255, 236, 170, 255))

    # Title.
    _center_text(d, "Match Report", 42, _font(66), (250, 250, 255, 255), W)

    # Central compatibility heart.
    heart_glow = Image.new("RGBA", (430, 430), (0,0,0,0))
    hg = ImageDraw.Draw(heart_glow)
    _draw_neon_heart(hg, 215, 185, 250, (255, 35, 210, 180), 18)
    heart_glow = heart_glow.filter(ImageFilter.GaussianBlur(18))
    base.alpha_composite(heart_glow, (425, 180))
    d = ImageDraw.Draw(base)
    _draw_neon_heart(d, 640, 365, 250, (255, 70, 225, 255), 8)
    _center_text(d, f"{score}%", 300, _font(82), (255, 220, 255, 255), W)
    _center_text(d, "COMPATIBILITY", 390, _font(30), (255, 255, 255, 255), W)

    # Small decorative hearts.
    for x, y, col in ((510, 285, (255, 80, 220, 220)), (770, 285, (255, 80, 220, 220)),
                      (520, 475, (255, 120, 225, 220)), (760, 475, (255, 120, 225, 220))):
        d.text((x, y), "♡", font=_font(52), fill=col)

    # User labels beneath each photo.
    left_name = (first.first_name or "Unknown")[:20]
    right_name = (second.first_name or "Unknown")[:20]
    for x, text, fill in ((225, f"User: {left_name}", (12, 35, 70, 235)),
                          (1055, f"User: {right_name}", (70, 12, 55, 235))):
        font = _font(34)
        box = d.textbbox((0,0), text, font=font)
        tw = box[2]-box[0]
        bw = min(370, tw + 42)
        bx = int(x - bw/2)
        d.rounded_rectangle((bx, 535, bx+bw, 595), radius=18, fill=fill, outline=(255,255,255,170), width=2)
        d.text((x-tw/2, 548), text, font=font, fill="white")

    _center_text(d, "Two Souls,", 560, _font(34), (255,255,255,255), W)
    _center_text(d, "One Vibe", 600, _font(34), (255,255,255,255), W)

    # Final JPEG.
    out = BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=93, optimize=True)
    out.seek(0)
    fd, path = tempfile.mkstemp(prefix="couple_match_report_", suffix=".jpg")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(out.getvalue())
    return path


async def _send_ship_photo(message, first, second, score, tier, ship, verdict, expires):
    image_path = await _make_couple_pfp(first, second, score, message.chat.id)
    try:
        caption = (
            f"💘 <b>DAILY SHIP HAS ARRIVED!</b> 💘\n\n"
            f"💞 {_mention(first)}  ×  {_mention(second)}\n\n"
            f"💗 <b>Compatibility:</b> {score}%\n"
            f"🏷️ <b>{tier}</b>\n"
            f"✨ <b>Ship Name:</b> #{html.escape(ship)}\n\n"
            f"🔮 <i>{html.escape(verdict)}</i>\n\n"
            f"⏳ <b>This couple is locked for 24 hours.</b>\n"
            f"🌙 Tomorrow, fate chooses again!"
        )
        await message.reply_photo(image_path, caption=caption)
    finally:
        try:
            os.remove(image_path)
        except Exception:
            pass


@app.on_message(filters.command("shipping") & filters.group & ~app.bl_users)
async def daily_shipping(_, message: types.Message):
    chat_id = message.chat.id
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    active = await _load_active_ship(chat_id)
    if active:
        expires = active["expires_at"]
        remaining = max(0, int((expires - datetime.utcnow()).total_seconds()))
        hours, rem = divmod(remaining, 3600)
        minutes = rem // 60
        first_name = html.escape(active.get("first_name", "Unknown"))
        second_name = html.escape(active.get("second_name", "Unknown"))
        score = int(active.get("score", 0))
        tier, _ = _tier(score)
        await message.reply_text(
            f"💘 <b>Today's Couple Is Already Locked!</b>\n\n"
            f"💞 {first_name} × {second_name}\n"
            f"💗 Compatibility: <b>{score}%</b>\n"
            f"🏷️ {tier}\n\n"
            f"⏳ New couple available in <b>{hours}h {minutes}m</b>.\n"
            f"✨ Come back tomorrow for a fresh ship!",
            disable_web_page_preview=True,
        )
        return

    members = await _get_eligible_members(chat_id)
    if len(members) < 2:
        await message.reply_text(
            "💔 <b>Not enough members!</b>\n\n"
            "I need at least <b>2 real members</b> in this group to create a ship."
        )
        return

    random.shuffle(members)
    first, second = members[0], members[1]
    now = datetime.utcnow()
    stamp = now.strftime("%Y-%m-%d")
    score = _seeded_score(chat_id, first.id, second.id, stamp)
    tier, verdict = _tier(score)
    first_display = first.first_name or "Unknown"
    second_display = second.first_name or "Unknown"
    ship = _ship_name(first_display, second_display)
    expires = now + timedelta(days=1)

    doc = {
        "_id": chat_id,
        "chat_id": chat_id,
        "first_id": first.id,
        "second_id": second.id,
        "first_name": first_display,
        "second_name": second_display,
        "score": score,
        "tier": tier,
        "ship_name": ship,
        "created_at": now,
        "expires_at": expires,
    }

    try:
        await db.db[SHIPPING_COLLECTION].insert_one(doc)
    except Exception:
        active = await _load_active_ship(chat_id)
        if active:
            # Another simultaneous command won the race. Keep the existing couple.
            await message.reply_text(
                "💘 <b>Today's couple has just been chosen!</b>\n\n"
                f"💞 {html.escape(active.get('first_name', 'Unknown'))} × {html.escape(active.get('second_name', 'Unknown'))}\n"
                f"💗 Compatibility: <b>{int(active.get('score', 0))}%</b>\n"
                f"🏷️ {_tier(int(active.get('score', 0)))[0]}\n\n"
                "⏳ This ship lasts for 24 hours.",
                disable_web_page_preview=True,
            )
            return
        raise

    await _send_ship_photo(message, first, second, score, tier, ship, verdict, expires)
