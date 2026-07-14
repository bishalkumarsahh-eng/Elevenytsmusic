# ==========================================================
# Copyright (c) 2026 Juno X Music
# All Rights Reserved.
# ==========================================================

import time
import re
from typing import Dict, List, Tuple
# ==========================================================
# Advanced AFK System (adapted)
# Implements group-local AFK and global AFK using the project's DB wrapper.
# Based on: https://github.com/bishalkumar000001/Music-Bot (ArtistMusic)
# ==========================================================

import asyncio
import os
import time
import logging
import tempfile
import subprocess

try:
    result = subprocess.run(
        ["lottie_convert.py", "--help"],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
except Exception as e:
    print("Lottie Error:", e)

import pyrogram
from pyrogram import filters
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from Elevenyts import app, db

logger = logging.getLogger(__name__)

# Prevent duplicate AFK notifications
_afk_notify_cache = {}


async def _set_afk(chat_id: int, user_id: int, reason: str = "",
                   media_type:str | None = None, media_file_id: str | None = None, since: float | None = None,):
    if not hasattr(db, "cache"):
        return None
    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "reason": reason or "No reason given",
        "since": since or time.time(),
        "media_type": None,
    }
    if media_file_id:
        payload["media_file_id"] = media_file_id
    if media_type:
        payload["media_type"] = media_type
    await db.cache.update_one(
        {"_id": f"afk_{chat_id}_{user_id}"},
        {"$set": payload},
        upsert=True,
    )


async def _get_afk(chat_id: int, user_id: int):
    if not hasattr(db, "cache"):
        return None
    doc = await db.cache.find_one({"_id": f"afk_{chat_id}_{user_id}"})
    return doc if doc else None


async def _remove_afk(chat_id: int, user_id: int):
    if not hasattr(db, "cache"):
        return None
    await db.cache.delete_one({"_id": f"afk_{chat_id}_{user_id}"})


async def _get_all_afk(chat_id: int):
    if not hasattr(db, "cache"):
        return []
    docs = []
    async for doc in db.cache.find({"chat_id": chat_id, "_id": {"$regex": f"^afk_{chat_id}_"}}):
        docs.append(doc)
    return docs


async def _set_gafk(user_id: int, reason: str = "",
                    media_type: str | None = None, media_file_id: str | None = None, since: float | None = None,):
    if not hasattr(db, "cache"):
        return None
    payload = {
        "user_id": user_id,
        "reason": reason or "No reason given",
        "since": since or time.time(),
        "media_type": None,
    }
    if media_file_id:
        payload["media_file_id"] = media_file_id
    if media_type:
        payload["media_type"] = media_type
    await db.cache.update_one(
        {"_id": f"gafk_{user_id}"},
        {"$set": payload},
        upsert=True,
    )


async def _get_gafk(user_id: int):
    if not hasattr(db, "cache"):
        return None
    doc = await db.cache.find_one({"_id": f"gafk_{user_id}"})
    return doc if doc else None


async def _remove_gafk(user_id: int):
    if not hasattr(db, "cache"):
        return None
    await db.cache.delete_one({"_id": f"gafk_{user_id}"})


if not hasattr(db, "set_afk"):
    db.set_afk = _set_afk
if not hasattr(db, "get_afk"):
    db.get_afk = _get_afk
if not hasattr(db, "remove_afk"):
    db.remove_afk = _remove_afk
if not hasattr(db, "get_all_afk"):
    db.get_all_afk = _get_all_afk
if not hasattr(db, "set_gafk"):
    db.set_gafk = _set_gafk
if not hasattr(db, "get_gafk"):
    db.get_gafk = _get_gafk
if not hasattr(db, "remove_gafk"):
    db.remove_gafk = _remove_gafk


# ──────────────────────────────────────────────
#  Atomic notification claim (uses db.cache)
# ──────────────────────────────────────────────


async def _claim_afk_notification(chat_id: int, user_id: int) -> bool:
    key = f"_afk_notif_{chat_id}_{user_id}"
    try:
        result = await db.cache.find_one_and_update(
            {"_id": key},
            {"$setOnInsert": {"ts": time.time()}},
            upsert=True,
            return_document=False,
        )
        if result is not None:
            return False

        async def _cleanup():
            await asyncio.sleep(5)
            try:
                await db.cache.delete_one({"_id": key})
            except Exception:
                pass

        asyncio.create_task(_cleanup())
        return True
    except Exception as e:
        logger.debug(f"AFK notification claim failed: {e}")
        return True


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    elif seconds < 86400:
        h, rem = divmod(seconds, 3600)
        m, _ = divmod(rem, 60)
        return f"{h}h {m}m"
    else:
        d, rem = divmod(seconds, 86400)
        h, _ = divmod(rem, 3600)
        return f"{d}d {h}h"


def _format_since_time(timestamp: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    except Exception:
        return "unknown time"


def _parse_command_and_reason(text: str):
    if not text:
        return None, None
    text = text.strip()
    if not text.startswith("/"):
        return None, None
    parts = text.split(None, 1)
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    if cmd not in ("afk", "gafk", "unafk", "ungafk", "afklist"):
        return None, None
    reason = parts[1].strip() if len(parts) > 1 else "No reason given"
    return cmd, reason


def _get_trigger(m: Message):
    return _parse_command_and_reason(m.text or m.caption or "")


# ──────────────────────────────────────────────
# Prevent duplicate AFK notification
# ──────────────────────────────────────────────


async def _should_notify(chat_id: int, user_id: int):
    key = f"{chat_id}:{user_id}"

    now = time.time()

    last = _afk_notify_cache.get(key)

    if last and now - last < 5:
        return False

    _afk_notify_cache[key] = now
    return True
# ──────────────────────────────────────────────
#  Sticker → JPEG conversion (for embedding in AFK messages)
# ──────────────────────────────────────────────


async def _sticker_to_jpeg(msg: Message) -> str | None:
    raw_path: str | None = None
    try:
        raw_path = await app.download_media(
            msg,
            file_name=os.path.join(
                tempfile.gettempdir(), f"afkstk_{msg.id}_{int(time.time())}"
            ),
        )
        if not raw_path or not os.path.exists(raw_path):
            return None

        jpg_path = raw_path + ".jpg"

        try:
            from PIL import Image
            with Image.open(raw_path) as img:
                try:
                    img.seek(0)
                except Exception:
                    pass
                if img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    converted = img.convert("RGBA")
                    alpha = converted.split()[-1]
                    bg.paste(converted.convert("RGB"), mask=alpha)
                    final = bg
                else:
                    final = img.convert("RGB")
                final.save(jpg_path, "JPEG", quality=85)
            if os.path.exists(jpg_path) and os.path.getsize(jpg_path) > 100:
                return jpg_path
        except Exception as e:
            logger.debug(f"PIL sticker conversion failed: {e}")

        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", raw_path,
                 "-vframes", "1", "-q:v", "2", jpg_path],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0 and os.path.exists(jpg_path) and os.path.getsize(jpg_path) > 100:
                return jpg_path
        except Exception as e:
            logger.debug(f"ffmpeg sticker frame extract failed: {e}")

        return None
    except Exception as e:
        logger.debug(f"_sticker_to_jpeg outer error: {e}")
        return None
    finally:
        if raw_path and os.path.exists(raw_path):
            try:
                os.remove(raw_path)
            except Exception:
                pass


# ──────────────────────────────────────────────
#  Core AFK notification sender
# ──────────────────────────────────────────────


async def _send_afk_notification(
    chat_id: int,
    text: str,
    source_msg: Message | None = None,
) -> str | None:
    """
    Send exactly ONE AFK notification message.

    - If `source_msg` is a photo/sticker/animation/video, send exactly one
      photo message (image + caption) and return its file_id.
    - Otherwise (no reply, or reply to plain text), send exactly one plain
      text message and return None.

    `sent_as_photo` guarantees we never fall through to the plain-text
    branch after a photo has already been delivered — this is what
    prevents the double "one with image, one without" notification.
    """
    jpg_path: str | None = None
    photo_file_id: str | None = None
    sent_as_photo = False

    try:
        if source_msg and source_msg.photo:
            fid = source_msg.photo[-1].file_id
            try:
                sent = await app.send_photo(chat_id, photo=fid, caption=text)
                sent_as_photo = True
                if sent and sent.photo:
                    photo_file_id = sent.photo[-1].file_id
            except Exception as e:
                logger.debug(f"send_photo (photo fid) failed: {e}")

        elif source_msg and source_msg.sticker:

            sticker = source_msg.sticker

            # Static Sticker
            if not sticker.is_video and not sticker.is_animated:

                jpg_path = await _sticker_to_jpeg(source_msg)

                if jpg_path:
                    try:
                        sent = await app.send_photo(
                            chat_id,
                            photo=jpg_path,
                            caption=text,
                        )

                        sent_as_photo = True

                        if sent.photo:
                            return "photo", sent.photo[-1].file_id

                    except Exception as e:
                        logger.debug(e)

            # Video Sticker (.webm)
            elif sticker.is_video:

                try:
                    sent = await app.send_sticker(
                        chat_id,
                        sticker=sticker.file_id,
                    )

                    await app.send_message(chat_id, text)

                    return "video_sticker", sticker.file_id

                except Exception as e:
                    logger.debug(e)

            # Animated Sticker (.tgs)

            elif sticker.is_animated:

                try:
                    tgs_path = await app.download_media(sticker.file_id)

                    gif_path = tgs_path.replace(".tgs", ".gif")

                    subprocess.run(
                        [
                            "lottie_convert.py",
                            tgs_path,
                            gif_path,
                        ],
                        check=True,
                    )

                    sent = await app.send_animation(
                        chat_id,
                        animation=gif_path,
                        caption=text,
                    )

                    if os.path.exists(tgs_path):
                    os.remove(tgs_path)

                    if os.path.exists(gif_path):
                    os.remove(gif_path)

                    return "animation", sent.animation.file_id

                except Exception as e:
                    logger.debug(f"Animated sticker conversion failed: {e}")

        elif source_msg and source_msg.animation:

            try:
                sent = await app.send_animation(
                    chat_id,
                    animation=source_msg.animation.file_id,
                    caption=text
                )

                if sent and sent.animation:
                    return "animation", sent.animation.file_id

            except Exception as e:
                logger.debug(f"Animation send failed: {e}")

        elif source_msg and source_msg.video:

            try:
                sent = await app.send_video(
                    chat_id,
                    video=source_msg.video.file_id,
                    caption=text
                )

                if sent and sent.video:
                    return "video", sent.video.file_id

            except Exception as e:
                logger.debug(f"Video send failed: {e}")

    except Exception as e:
        logger.debug(f"_send_afk_notification outer error: {e}")
    finally:
        if jpg_path and os.path.exists(jpg_path):
            try:
                os.remove(jpg_path)
            except Exception:
                pass

    # A photo attempt was made — never also send the plain-text fallback,
    # even if we failed to capture its file_id.
    if sent_as_photo:
        return "photo", photo_file_id

    try:
        await app.send_message(chat_id, text=text)
    except Exception:
        pass
    return None


async def _send_afk_back(
    chat_id: int,
    name: str,
    reason: str,
    gone_for: str,
    stored_photo_id: str | None,
    is_global: bool = False,
) -> None:
    label = " [ɢʟᴏʙᴀʟ ᴀꜰᴋ]" if is_global else ""
    text = (
        f"❖ <b>{name}</b> ɪs ʙᴀᴄᴋ ᴏɴʟɪɴᴇ{label}\n"
        f"ᴀɴᴅ ᴡᴀs ᴀᴡᴀʏ ꜰᴏʀ {gone_for}\n\n"
        f"• ʀᴇᴀꜱᴏɴ ➜ {reason}"
    )
    media_type = None

    if stored_photo_id:
        try:
            # Try to determine media type if it was passed separately later
            if isinstance(stored_photo_id, dict):
                media_type = stored_photo_id.get("media_type")
                media_id = stored_photo_id.get("media_file_id")
            else:
                media_id = stored_photo_id

            if media_type == "animation":
                await app.send_animation(
                    chat_id,
                    animation=media_id,
                    caption=text,
                )
                return

            elif media_type == "video":
                await app.send_video(
                    chat_id,
                    video=media_id,
                    caption=text,
                )
                return
            elif media_type == "video_sticker":
                await app.send_sticker(
                    chat_id,
                    sticker=media_id,
                )
                await app.send_message(chat_id, text)
                return

            elif media_type == "animated_sticker":
                await app.send_sticker(
                    chat_id,
                    sticker=media_id,
                )
                await app.send_message(chat_id, text)
                return

            else:
                await app.send_photo(
                    chat_id,
                    photo=media_id,
                    caption=text,
                )
                return

        except Exception as e:
            logger.debug(f"BACK media failed: {e}")
    try:
        await app.send_message(chat_id, text=text)
    except Exception as e:
        logger.debug(f"BACK send_message failed: {e}")


async def _send_afk_mention(m: Message, mid: int, afk_data: dict,
                             is_global: bool = False):
    gone_for = _format_duration(time.time() - afk_data["since"])
    since_at = _format_since_time(afk_data["since"])
    reason = afk_data.get("reason", "No reason given")
    label = " [ɢʟᴏʙᴀʟ]" if is_global else ""
    try:
        user = await app.get_users(mid)
        name = user.first_name or "User"
    except Exception:
        name = f"User {mid}"

    text = (
        f"❖ <b>{name}</b> ɪs ᴀꜰᴋ{label} since {since_at} ({gone_for})\n\n"
        f"• ʀᴇᴀꜱᴏɴ ➜ {reason}"
    )
    media_type = afk_data.get("media_type")
    media_id = afk_data.get("media_file_id")

    if media_id:

        try:
            if media_type == "photo":
                await m.reply_photo(
                    photo=media_id,
                    caption=text
                )
                return
            elif media_type == "video_sticker":
                await m.reply_sticker(
                    sticker=media_id,
                )
                await m.reply_text(text)
                return
              
            elif media_type == "animated_sticker":
                await m.reply_sticker(
                    sticker=media_id,
                )
                await m.reply_text(text)
                return

            elif media_type == "animation":
                await m.reply_animation(
                    animation=media_id,
                    caption=text
                )
                return

            elif media_type == "video":
                await m.reply_video(
                    video=media_id,
                    caption=text
                )
                return

        except Exception as e:
            logger.debug(f"AFK media failed: {e}")

    try:
        await m.reply_text(text)
    except Exception as e:
        logger.debug(f"AFK text failed: {e}")


# ──────────────────────────────────────────────
#  Shared AFK-set logic (used by both handlers)
# ──────────────────────────────────────────────


async def _process_afk_set(m: Message, source_msg: Message | None,
                             reason: str, is_global: bool = False):
    if not m.from_user:
        return

    user_id = m.from_user.id
    chat_id = m.chat.id
    name = m.from_user.first_name or "User"
    reason = reason[:200]

    # Guard: already AFK
    if not is_global:
        if await db.get_afk(chat_id, user_id):
            return
        if await db.get_gafk(user_id):
            return
    else:
        if await db.get_gafk(user_id):
            return

    # Atomic claim — only ONE handler proceeds
    if not await _claim_afk_notification(chat_id, user_id):
        return

    try:
        await m.delete()
    except Exception:
        pass

    # Register in DB
    if not is_global:
        await db.set_afk(chat_id, user_id, reason)
        label = "ɴᴏᴡ ᴀꜰᴋ"
    else:
        await db.set_gafk(user_id, reason)
        label = "ɴᴏᴡ ɢʟᴏʙᴀʟ ᴀꜰᴋ"

    afk_text = (
        f"❖ <b>{name}</b> ɪs {label} !\n\n"
        f"• ʀᴇᴀꜱᴏɴ ➜ {reason}"
    )

    stored_file_id = None
    media_type = None

    if source_msg:
        if source_msg.photo:
            media_type = "photo"

        elif source_msg.sticker:
            if source_msg.sticker.is_video:
                media_type = "video_sticker"
            elif source_msg.sticker.is_animated:
                media_type = "animated_sticker"
            else:
                media_type = "photo"

        elif source_msg.animation:
            media_type = "animation"

        elif source_msg.video:
            media_type = "video"

    media_type, stored_file_id = await _send_afk_notification(
        chat_id,
        afk_text,
        source_msg,
    )

    if stored_file_id:

        if media_type is None:

            if source_msg:

                if source_msg.photo:
                    media_type = "photo"

                elif source_msg.sticker:
                    media_type = "photo"

                elif source_msg.animation:
                    media_type = "animation"

                elif source_msg.video:
                    media_type = "video"

        if not is_global:

            await db.set_afk(
                chat_id=chat_id,
                user_id=user_id,
                reason=reason,
                media_type=media_type,
                media_file_id=stored_file_id,
            )

        else:

            await db.set_gafk(
                user_id=user_id,
                reason=reason,
                media_type=media_type,
                media_file_id=stored_file_id,
            )


# ──────────────────────────────────────────────
#  /afk — text command handler
# ──────────────────────────────────────────────


@app.on_message(
    filters.command("afk") & filters.group & ~app.bl_users,
    group=9
)
async def afk_set(_, m: Message):
    cmd, reason = _get_trigger(m)
    if cmd != "afk":
        return

    source_msg = m.reply_to_message if m.reply_to_message else None
    await _process_afk_set(m, source_msg, reason, is_global=False)
    raise pyrogram.StopPropagation


# ──────────────────────────────────────────────
#  /afk via photo/sticker caption
# ──────────────────────────────────────────────


@app.on_message(
    (filters.photo | filters.sticker | filters.animation | filters.video) &
    filters.caption & filters.group & ~app.bl_users,
    group=9
)
async def afk_set_caption(_, m: Message):
    cmd, reason = _parse_command_and_reason(m.caption or "")
    if cmd != "afk":
        return

    await _process_afk_set(m, m, reason, is_global=False)
    raise pyrogram.StopPropagation


# ──────────────────────────────────────────────
#  /gafk command — Global AFK
# ──────────────────────────────────────────────


@app.on_message(
    filters.command("gafk") & filters.group & ~app.bl_users,
    group=9
)
async def gafk_set(_, m: Message):
    cmd, reason = _get_trigger(m)
    if cmd != "gafk":
        return

    source_msg = m.reply_to_message if (m.text and m.reply_to_message) else None
    await _process_afk_set(m, source_msg, reason, is_global=True)
    raise pyrogram.StopPropagation


# ──────────────────────────────────────────────
#  /unafk
# ──────────────────────────────────────────────


@app.on_message(
    filters.command("unafk") & filters.group & ~app.bl_users,
    group=9
)
async def afk_unset(_, m: Message):
    if not m.from_user:
        return

    user_id = m.from_user.id
    name=m.from_user.first_name or "User"
    chat_id = m.chat.id
    afk_data = await db.get_afk(chat_id, user_id)

    if not afk_data:
        try:
            await m.reply_text("ℹ️ You are not AFK in this group.")
        except Exception:
            pass
        return

    gone_for = _format_duration(time.time() - afk_data["since"])
    reason = afk_data.get("reason", "No reason given")
    photo_id = afk_data.get("media_file_id")
    await db.remove_afk(chat_id, user_id)

    try:
        await m.delete()
    except Exception:
        pass

    await _send_afk_back(
        chat_id,
        name,
        reason,
        gone_for,
        {
            "media_type": afk_data.get("media_type"),
            "media_file_id": afk_data.get("media_file_id"),
        },
    )
    raise pyrogram.StopPropagation



@app.on_message(
    filters.command("ungafk") & filters.group & ~app.bl_users,
    group=9
)
async def gafk_unset(_, m: Message):
    if not m.from_user:
        return

    user_id = m.from_user.id
    name=m.from_user.first_name or "User",
    chat_id = m.chat.id
    gafk_data = await db.get_gafk(user_id)

    if not gafk_data:
        try:
            await m.reply_text("ℹ️ You don't have global AFK set.")
        except Exception:
            pass
        return

    gone_for = _format_duration(time.time() - gafk_data["since"])
    reason = gafk_data.get("reason", "No reason given")
    photo_id = gafk_data.get("media_file_id")
    await db.remove_gafk(user_id)

    try:
        await m.delete()
    except Exception:
        pass

    await _send_afk_back(
        chat_id,
        name,
        reason,
        gone_for,
        {
            "media_type": gafk_data.get("media_type"),
            "media_file_id": gafk_data.get("media_file_id"),
        },
    )
    raise pyrogram.StopPropagation


@app.on_message(
    filters.command("afklist") & filters.group & ~app.bl_users,
    group=9
)
async def afk_list(_, m: Message):
    chat_id = m.chat.id
    afk_users = await db.get_all_afk(chat_id)

    if not afk_users:
        return await m.reply_text("ℹ️ No users are currently AFK in this group.")

    now = time.time()
    lines = ["<b>💤 AFK Users:</b>\n"]
    for entry in afk_users:
        uid = entry["user_id"]
        reason = entry.get("reason", "—")
        since = entry.get("since", now)
        duration = _format_duration(now - since)
        try:
            user = await app.get_users(uid)
            mention = _mention(user)
        except Exception:
            mention = f"User {uid}"
        lines.append(f"❖ {mention}\n   ⏱ {duration} ago  •  ʀᴇᴀꜱᴏɴ ➜ {reason}")

    await m.reply_text("\n\n".join(lines))


# Auto-watcher — every group message
_SKIP_CMDS = {"/afk", "/unafk", "/afklist", "/gafk", "/ungafk"}


@app.on_message(
    filters.group & ~app.bl_users,
    group=10
)
async def afk_watcher(_, m: Message):
    if not m.from_user or m.from_user.is_bot:
        return

    user_id = m.from_user.id
    chat_id = m.chat.id
    name = m.from_user.first_name or "User"

    raw = (m.text or m.caption or "").strip().lower()
    first_word = raw.split()[0].split("@")[0] if raw else ""
    if first_word in _SKIP_CMDS:
        return

    cmd, _ = _get_trigger(m)
    if cmd in ("afk", "gafk"):
        return

    # 1. Sender came back from LOCAL AFK
    local_afk = await db.get_afk(chat_id, user_id)
    if local_afk:
        gone_for = _format_duration(time.time() - local_afk["since"])
        reason = local_afk.get("reason", "No reason given")
        photo_id = local_afk.get("media_file_id")
        await db.remove_afk(chat_id, user_id)
        await _send_afk_back(
            chat_id,
            name,
            reason,
            gone_for,
            {
                "media_type": local_afk.get("media_type"),
                "media_file_id": local_afk.get("media_file_id"),
            },
        )

    # 2. Sender came back from GLOBAL AFK
    global_afk = await db.get_gafk(user_id)
    if global_afk:
        gone_for = _format_duration(time.time() - global_afk["since"])
        reason = global_afk.get("reason", "No reason given")
        photo_id = global_afk.get("media_file_id")
        await db.remove_gafk(user_id)
        await _send_afk_back(
            chat_id,
            name,
            reason,
            gone_for,
            {
                "media_type": local_afk.get("media_type"),
                "media_file_id": local_afk.get("media_file_id"),
            },
        )

    # 3. Mentioned/replied-to user is AFK
    mentioned_ids: list[int] = []
    for entity_list in (m.entities or [], m.caption_entities or []):
        for entity in entity_list:
            if entity.type == MessageEntityType.TEXT_MENTION and entity.user:
                mentioned_ids.append(entity.user.id)
            elif entity.type == MessageEntityType.MENTION:

                text = m.text or m.caption or ""

                username = text[
                    entity.offset:
                    entity.offset + entity.length
                ]

                username = username.lstrip("@")

                try:
                    user = await app.get_users(username)

                    if user:
                        mentioned_ids.append(user.id)

                except Exception:
                    pass
    if m.reply_to_message and m.reply_to_message.from_user:
        mentioned_ids.append(m.reply_to_message.from_user.id)

    for mid in set(mentioned_ids):
        if not await _should_notify(chat_id, mid):
            continue
        if mid == user_id:
            continue
        mid_local = await db.get_afk(chat_id, mid)
        if mid_local:
            await _send_afk_mention(m, mid, mid_local, is_global=False)
            continue
        mid_global = await db.get_gafk(mid)
        if mid_global:
            await _send_afk_mention(m, mid, mid_global, is_global=True)
