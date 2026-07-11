# ==========================================================
# Copyright (c) 2026 Juno X Music
# All Rights Reserved.
# ==========================================================

import time
from typing import Dict

from pyrogram import filters, types

from Elevenyts import app

AFK_USERS: Dict[int, Dict[str, object]] = {}
AFK_HEADER = "❖ ⎯꯭̽🦚⤹‌⋆‌‌‌‌𝅃͢𝐓𝛋֟͡‌‌‌𝐬 ≛ ͓͢‌‌𝛃 ͓𝛊֟͜͡ ͓𝛅 ͓𝝸̵̵𝐥 ͓𝛌 ͓𝐥 ⤹💙ˎ˗"


def _format_duration(seconds: int) -> str:
    seconds = max(seconds, 0)
    if seconds < 60:
        return f"{seconds} seconds"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    hours = minutes // 60
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _build_afk_message(name: str = "", reason: str = "", seconds: int = 0) -> str:
    text = f"{AFK_HEADER} is now AFK!" if not name else f"{AFK_HEADER} {name} is now AFK!"
    if reason:
        text += f"\n● Reason: {reason}"
    text += f"\n● Away for: {_format_duration(seconds)}"
    return text


def _build_back_message(seconds: int = 0) -> str:
    return f"❖ Welcome back {AFK_HEADER}!\n● You were away for: {_format_duration(seconds)}"


@app.on_message(filters.command(["afk", "away"]))
async def afk_set(_, message: types.Message):
    if not message.from_user:
        return

    reason = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""
    AFK_USERS[message.from_user.id] = {
        "reason": reason,
        "time": time.time(),
        "username": message.from_user.username,
        "name": message.from_user.first_name or "User",
    }
    await message.reply_text(_build_afk_message(reason=reason, seconds=0))


@app.on_message(filters.command(["afkoff", "back"]))
async def afk_clear(_, message: types.Message):
    if not message.from_user:
        return

    state = AFK_USERS.get(message.from_user.id)
    elapsed = int(time.time() - state.get("time", time.time())) if state else 0
    AFK_USERS.pop(message.from_user.id, None)
    await message.reply_text(_build_back_message(seconds=elapsed))


@app.on_message(filters.text & ~filters.command & ~filters.service, group=25)
async def afk_reply(_, message: types.Message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    if user_id in AFK_USERS:
        state = AFK_USERS.pop(user_id, None)
        elapsed = int(time.time() - state.get("time", time.time())) if state else 0
        await message.reply_text(_build_back_message(seconds=elapsed))
        return

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        state = AFK_USERS.get(target_id)
        if state and target_id != user_id:
            reason = state.get("reason") or ""
            name = state.get("name") or message.reply_to_message.from_user.first_name or "User"
            elapsed = int(time.time() - state.get("time", time.time()))
            await message.reply_text(_build_afk_message(name=name, reason=reason, seconds=elapsed))
            return

    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mention = message.text[entity.offset : entity.offset + entity.length]
                username = mention.lstrip("@")
                for target_id, state in AFK_USERS.items():
                    if target_id != user_id and str(state.get("username") or "").lower() == username.lower():
                        reason = state.get("reason") or ""
                        name = state.get("name") or username
                        elapsed = int(time.time() - state.get("time", time.time()))
                        await message.reply_text(_build_afk_message(name=name, reason=reason, seconds=elapsed))
                        return
