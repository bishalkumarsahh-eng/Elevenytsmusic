# ==========================================================
# VelocityBots — Daily Couple Shipping + Couple PFP
# ==========================================================

import hashlib
import html
import random
import os
from datetime import datetime, timedelta

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



async def _send_ship_text(message, first, second, score, tier, ship, verdict, expires):
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
    await message.reply_text(caption)


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
                    )
            return
        raise

    await _send_ship_text(message, first, second, score, tier, ship, verdict, expires)
