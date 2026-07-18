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
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow may be optional in some environments
    Image = None

from pyrogram import errors, filters
from pyrogram.enums import MessageEntityType, ParseMode
from pyrogram.types import Message

from Elevenyts import app, db, logger

AFK_CMDS = ("afk", "gafk", "unafk", "ungafk", "afklist")
DIVIDER = "━━━━━━━━━━━━━━━━━━"
TMP_DIR = "cache"
os.makedirs(TMP_DIR, exist_ok=True)

AFK_COLLECTION = "afk"
NOTIFICATION_COLLECTION = "afk_notifications"

AFK_MEMORY_STORE: Dict[Tuple[int, bool, Optional[int]], Dict[str, Any]] = {}
AFK_NOTIFICATION_MEMORY_STORE: Dict[Tuple[int, int, int, int], Dict[str, Any]] = {}


async def _get_collection(name: str):
    try:
        return db.db[name]
    except Exception as exc:
        logger.exception("Failed to access Mongo collection %s: %s", name, exc)
        return None


def _is_collection_available(collection: Any) -> bool:
    return collection is not None


def _mention(user) -> str:
    """HTML mention anchor. Safe against missing first_name."""
    name = (getattr(user, "first_name", None) or "User").strip() or "User"
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def _format_since_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y, %H:%M IST")
    except Exception:
        return "unknown"


def _parse_command_and_reason(message: Message) -> Tuple[str, str]:
    text = (message.text or message.caption or "").strip()
    if not text:
        return "", ""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@", 1)[0].lower()
    reason = parts[1].strip() if len(parts) > 1 else ""
    return cmd, reason


def _get_trigger(message: Message) -> str:
    text = (message.text or message.caption or "").strip()
    if not text:
        return ""
    first = text.split(maxsplit=1)[0]
    return first.lstrip("/").split("@", 1)[0].lower()


async def _sticker_to_jpeg(client, sticker_file_id: str) -> Optional[str]:
    src_path = os.path.join(TMP_DIR, f"stk_{uuid.uuid4().hex}")
    jpg_path = src_path + ".jpg"
    downloaded = None
    try:
        downloaded = await client.download_media(sticker_file_id, file_name=src_path)
        if not downloaded or not os.path.exists(downloaded):
            return None

        ok = False
        if Image is not None:
            try:
                with Image.open(downloaded) as im:
                    im.load()
                    if im.mode != "RGB":
                        im = im.convert("RGB")
                    im.save(jpg_path, "JPEG", quality=90)
                    ok = True
            except Exception:
                ok = False

        if not ok:
            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        downloaded,
                        "-vframes",
                        "1",
                        "-vf",
                        "scale=512:-1",
                        jpg_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                ok = (proc.returncode == 0 and os.path.exists(jpg_path))
            except Exception:
                ok = False

        if not ok or not os.path.exists(jpg_path):
            return None

        try:
            sent = await client.send_photo(chat_id="me", photo=jpg_path, disable_notification=True)
            file_id = None
            if sent and sent.photo:
                file_id = sent.photo.file_id
            try:
                await sent.delete()
            except Exception:
                pass
            return file_id
        except Exception:
            return None
    finally:
        for p in (downloaded, jpg_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def _extract_afk_media(client, message: Message) -> Optional[str]:
    candidates = [message]
    if message.reply_to_message:
        candidates.append(message.reply_to_message)

    for m in candidates:
        if m.photo:
            return m.photo.file_id
        if m.animation:
            return m.animation.file_id
        if m.video:
            return m.video.file_id
        if m.sticker:
            converted = await _sticker_to_jpeg(client, m.sticker)
            if converted:
                return converted
    return None


async def _claim_afk_notification(chat_id: int, user_id: int, ttl: int = 5) -> bool:
    key = f"_afk_notif_{chat_id}_{user_id}"
    now = time.time()
    try:
        collection = await _get_collection(NOTIFICATION_COLLECTION)
        if _is_collection_available(collection):
            res = await collection.find_one_and_update(
                {"_id": key, "$or": [{"exp": {"$lte": now}}, {"exp": {"$exists": False}}]},
                {"$set": {"_id": key, "exp": now + ttl}},
                upsert=True,
                return_document=False,
            )
            return res is None or res.get("exp", 0) <= now
        return True
    except Exception:
        return False


async def _claim_welcome_back(chat_id: int, user_id: int, ttl: int = 5) -> bool:
    key = f"_wb_notif_{chat_id}_{user_id}"
    now = time.time()
    try:
        collection = await _get_collection(NOTIFICATION_COLLECTION)
        if _is_collection_available(collection):
            res = await collection.find_one_and_update(
                {"_id": key, "$or": [{"exp": {"$lte": now}}, {"exp": {"$exists": False}}]},
                {"$set": {"_id": key, "exp": now + ttl}},
                upsert=True,
                return_document=False,
            )
            return res is None or res.get("exp", 0) <= now
        return True
    except Exception:
        return False


def _format_media_caption(media_type: str, caption: str) -> str:
    if not media_type or media_type == "text":
        return ""

    label_map = {
        "photo": "photo",
        "animation": "gif",
        "video": "video",
        "sticker": "sticker telegram",
        "audio": "audio",
        "voice": "voice",
        "document": "document",
    }
    label = label_map.get(media_type, media_type)
    safe_caption = (caption or "").strip()
    if safe_caption:
        return f"\n[{label}] caption: {safe_caption}\n"
    return f"\n[{label}] caption:\n"


def _afk_card(name_html: str, duration: str, since: str, reason: str, is_global: bool, media_type: Optional[str] = None, media_caption: Optional[str] = None) -> str:
    label = " [ɢʟᴏʙᴀʟ]" if is_global else ""
    reason = reason.strip() or "No reason provided"
    media_section = _format_media_caption(media_type or "", media_caption or "")
    return (
        f"<blockquote><b>{name_html}</b>{label} is now AFK</blockquote>\n"
        f"<blockquote><b>⏱ Away:</b> {duration}</blockquote>\n"
        f"<blockquote><b>📅 Since:</b> {since}</blockquote>\n"
        f"<blockquote><b>📝 Reason:</b> {reason}</blockquote>\n"
        f"{media_section}"
    )


def _welcome_back_card(name_html: str, duration: str, reason: str, media_type: Optional[str] = None, media_caption: Optional[str] = None) -> str:
    reason = reason.strip() or "No reason provided"
    media_section = _format_media_caption(media_type or "", media_caption or "")
    return (
        f"<blockquote><b>✨ Welcome Back</b></blockquote>\n"
        f"<blockquote><b>{name_html}</b> is back!</blockquote>\n"
        f"<blockquote><b>⏱ AFK Time:</b> {duration}</blockquote>\n"
        f"<blockquote><b>📝 Reason:</b> {reason}</blockquote>\n"
        f"{media_section}"
    )


async def _safe_send(send_func, *args: Any, **kwargs: Any) -> Optional[Message]:
    attempt = 0
    while True:
        try:
            return await send_func(*args, **kwargs)
        except errors.FloodWait as e:
            attempt += 1
            if attempt >= 5:
                logger.warning("FloodWait exceeded retries for AFK send: %s", e)
                return None
            logger.warning("FloodWait in AFK module, sleeping for %ss", e.value + 1)
            await asyncio.sleep(e.value + 1)
        except Exception as exc:
            logger.exception("Telegram send failed in AFK module: %s", exc)
            return None


async def _send_text_message(chat_id: int, text: str, reply_to: int, parse_mode: ParseMode = ParseMode.HTML) -> Optional[Message]:
    return await _safe_send(
        app.send_message,
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
        reply_to_message_id=reply_to,
    )


async def _extract_media_data(message: Message) -> Dict[str, Any]:
    if message.photo:
        return {"media_type": "photo", "media_file_id": message.photo.file_id, "caption": message.caption or ""}
    if message.video:
        return {"media_type": "video", "media_file_id": message.video.file_id, "caption": message.caption or ""}
    if message.animation:
        return {"media_type": "animation", "media_file_id": message.animation.file_id, "caption": message.caption or ""}
    if message.audio:
        return {"media_type": "audio", "media_file_id": message.audio.file_id, "caption": message.caption or ""}
    if message.voice:
        return {"media_type": "voice", "media_file_id": message.voice.file_id, "caption": message.caption or ""}
    if message.sticker:
        converted = await _sticker_to_jpeg(app, message.sticker.file_id)
        if converted:
            return {"media_type": "photo", "media_file_id": converted, "caption": message.caption or ""}
    if message.document and not getattr(message.document, "mime_type", "") == "image/webp":
        return {"media_type": "document", "media_file_id": message.document.file_id, "caption": message.caption or ""}
    if message.text or message.caption:
        return {"media_type": "text", "media_file_id": "", "caption": message.text or message.caption or ""}
    return {"media_type": "text", "media_file_id": "", "caption": ""}


async def _send_afk_media(chat_id: int, reply_to: int, media_payload: Dict[str, Any], caption_override: Optional[str] = None) -> Optional[Message]:
    media_type = media_payload.get("media_type", "text")
    media_file_id = media_payload.get("media_file_id", "")
    caption = caption_override if caption_override is not None else media_payload.get("caption", "")

    if media_type == "photo":
        return await _safe_send(app.send_photo, chat_id=chat_id, photo=media_file_id, caption=caption, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
    if media_type == "video":
        return await _safe_send(app.send_video, chat_id=chat_id, video=media_file_id, caption=caption, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
    if media_type == "animation":
        return await _safe_send(app.send_animation, chat_id=chat_id, animation=media_file_id, caption=caption, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
    if media_type == "audio":
        return await _safe_send(app.send_audio, chat_id=chat_id, audio=media_file_id, caption=caption, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
    if media_type == "voice":
        return await _safe_send(app.send_voice, chat_id=chat_id, voice=media_file_id, caption=caption, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
    if media_type == "document":
        return await _safe_send(app.send_document, chat_id=chat_id, document=media_file_id, caption=caption, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
    return await _send_text_message(chat_id, caption or "", reply_to)


async def _send_welcome_back(chat_id: int, reply_to: int, user: Any, reason: str, duration: str, media_payload: Optional[Dict[str, Any]] = None) -> None:
    try:
        display_name = user.first_name if user and getattr(user, "first_name", None) else "User"
        media_type = media_payload.get("media_type", "text") if media_payload else "text"
        caption = _welcome_back_card(
            _mention(user),
            duration,
            reason,
            media_payload.get("media_type", "text") if media_payload else "text",
            media_payload.get("caption", "") if media_payload else "",
        )
        if media_payload and media_type != "text":
            await _send_afk_media(chat_id, reply_to, media_payload, caption_override=caption)
        else:
            await _send_text_message(chat_id, caption, reply_to)
    except Exception as exc:
        logger.exception("Failed to send welcome back card: %s", exc)


async def _normalize_afk_document(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    doc = dict(doc)
    doc.setdefault("reason", "No reason provided")
    doc.setdefault("time", int(time.time()))
    doc.setdefault("media_type", "text")
    doc.setdefault("media_file_id", "")
    doc.setdefault("caption", "")
    doc.setdefault("is_global", False)
    doc.setdefault("chat_id", None)
    doc.setdefault("user_id", None)
    doc.setdefault("username", None)
    return doc


async def _save_afk_entry(user_id: int, chat_id: int, reason: str, is_global: bool, media_payload: Dict[str, Any], username: Optional[str] = None) -> bool:
    try:
        payload = {
            "user_id": user_id,
            "chat_id": None if is_global else chat_id,
            "is_global": is_global,
            "reason": reason or "No reason provided",
            "time": int(time.time()),
            "media_type": media_payload.get("media_type", "text"),
            "media_file_id": media_payload.get("media_file_id", ""),
            "caption": media_payload.get("caption", ""),
            "username": username or "",
        }
        collection = await _get_collection(AFK_COLLECTION)
        if _is_collection_available(collection):
            await collection.update_one(
                {"user_id": user_id, "is_global": is_global, "chat_id": None if is_global else chat_id},
                {"$set": payload},
                upsert=True,
            )
        else:
            AFK_MEMORY_STORE[(user_id, is_global, None if is_global else chat_id)] = payload
        return True
    except Exception as exc:
        logger.exception("Failed to save AFK entry: %s", exc)
        return False


async def _remove_afk_entry(user_id: int, chat_id: int, is_global: bool) -> bool:
    try:
        collection = await _get_collection(AFK_COLLECTION)
        if _is_collection_available(collection):
            query = {"user_id": user_id}
            if is_global:
                query["is_global"] = True
            else:
                query["chat_id"] = chat_id
            await collection.delete_one(query)
        else:
            AFK_MEMORY_STORE.pop((user_id, is_global, None if is_global else chat_id), None)
        return True
    except Exception as exc:
        logger.exception("Failed to remove AFK entry: %s", exc)
        return False


async def _get_afk_entry(user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
    try:
        collection = await _get_collection(AFK_COLLECTION)
        if _is_collection_available(collection):
            local_doc = await collection.find_one({"user_id": user_id, "is_global": False, "chat_id": chat_id})
            if local_doc:
                return await _normalize_afk_document(local_doc)
            global_doc = await collection.find_one({"user_id": user_id, "is_global": True})
            return await _normalize_afk_document(global_doc)

        local_doc = AFK_MEMORY_STORE.get((user_id, False, chat_id))
        if local_doc:
            return await _normalize_afk_document(local_doc)
        global_doc = AFK_MEMORY_STORE.get((user_id, True, None))
        return await _normalize_afk_document(global_doc)
    except Exception as exc:
        logger.exception("Failed to fetch AFK entry: %s", exc)
        return None


async def _list_afk_entries(chat_id: int) -> List[Dict[str, Any]]:
    try:
        collection = await _get_collection(AFK_COLLECTION)
        if _is_collection_available(collection):
            docs = []
            async for doc in collection.find({"$or": [{"is_global": True}, {"chat_id": chat_id}]}).sort("time", 1):
                docs.append(await _normalize_afk_document(doc))
            return [doc for doc in docs if doc]

        docs = [doc for doc in AFK_MEMORY_STORE.values() if doc.get("is_global") or doc.get("chat_id") == chat_id]
        return [await _normalize_afk_document(doc) for doc in docs if await _normalize_afk_document(doc)]
    except Exception as exc:
        logger.exception("Failed to list AFK entries: %s", exc)
        return []


async def _store_notification_cache(sender_id: int, afk_user_id: int, chat_id: int, message_id: int) -> None:
    try:
        payload = {
            "sender_id": sender_id,
            "afk_user_id": afk_user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "expires_at": int(time.time()) + 300,
        }
        collection = await _get_collection(NOTIFICATION_COLLECTION)
        if _is_collection_available(collection):
            await collection.replace_one(
                {"sender_id": sender_id, "afk_user_id": afk_user_id, "chat_id": chat_id, "message_id": message_id},
                payload,
                upsert=True,
            )
        else:
            AFK_NOTIFICATION_MEMORY_STORE[(sender_id, afk_user_id, chat_id, message_id)] = payload
    except Exception as exc:
        logger.exception("Failed to cache AFK notification: %s", exc)


async def _is_duplicate_notification(sender_id: int, afk_user_id: int, chat_id: int, message_id: int) -> bool:
    try:
        collection = await _get_collection(NOTIFICATION_COLLECTION)
        if _is_collection_available(collection):
            doc = await collection.find_one({
                "sender_id": sender_id,
                "afk_user_id": afk_user_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "expires_at": {"$gt": int(time.time())},
            })
            return bool(doc)

        doc = AFK_NOTIFICATION_MEMORY_STORE.get((sender_id, afk_user_id, chat_id, message_id))
        if doc:
            return int(doc.get("expires_at", 0)) > int(time.time())
        return False
    except Exception as exc:
        logger.exception("Failed to detect duplicate AFK notification: %s", exc)
        return False


def _format_age(timestamp: int) -> str:
    try:
        age = max(1, int(time.time()) - int(timestamp))
    except Exception:
        age = 1
    seconds = age % 60
    minutes = (age // 60) % 60
    hours = (age // 3600) % 24
    days = age // 86400
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _format_since(timestamp: int) -> str:
    try:
        dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        return dt.strftime("%d %b %Y %H:%M:%S UTC")
    except Exception:
        return "Unknown"


async def _resolve_mention_targets(message: Message) -> List[int]:
    targets: List[int] = []
    if not message or not message.from_user:
        return targets

    sender_id = message.from_user.id

    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            targets.append(message.reply_to_message.from_user.id)
    except Exception:
        pass

    try:
        if message.entities:
            for entity in message.entities:
                if entity.type == MessageEntityType.TEXT_MENTION and entity.user:
                    targets.append(entity.user.id)
                if entity.type == MessageEntityType.MENTION:
                    username = message.text[entity.offset + 1:entity.offset + entity.length] if message.text else ""
                    if username:
                        try:
                            user = await app.get_users(username)
                            if user:
                                targets.append(user.id)
                        except Exception:
                            continue
    except Exception:
        pass

    try:
        if message.caption_entities:
            for entity in message.caption_entities:
                if entity.type == MessageEntityType.TEXT_MENTION and entity.user:
                    targets.append(entity.user.id)
                if entity.type == MessageEntityType.MENTION:
                    username = message.caption[entity.offset + 1:entity.offset + entity.length] if message.caption else ""
                    if username:
                        try:
                            user = await app.get_users(username)
                            if user:
                                targets.append(user.id)
                        except Exception:
                            continue
    except Exception:
        pass

    targets = [uid for uid in dict.fromkeys(targets) if uid != sender_id]
    return targets


async def _handle_afk_notification(message: Message) -> None:
    if not message or not message.from_user or message.from_user.is_self:
        return

    try:
        targets = await _resolve_mention_targets(message)
        if not targets:
            return
        for target_id in targets:
            afk_entry = await _get_afk_entry(target_id, message.chat.id)
            if not afk_entry:
                continue
            if target_id == message.from_user.id:
                continue
            if await _is_duplicate_notification(message.from_user.id, target_id, message.chat.id, message.id):
                continue

            await _store_notification_cache(message.from_user.id, target_id, message.chat.id, message.id)
            media_payload = {
                "media_type": afk_entry.get("media_type", "text"),
                "media_file_id": afk_entry.get("media_file_id", ""),
                "caption": afk_entry.get("caption", ""),
            }
            reason = afk_entry.get("reason") or "No reason provided"
            since_timestamp = int(afk_entry.get("time", int(time.time())))
            since_label = _format_age(since_timestamp)
            user_name = message.reply_to_message.from_user.first_name if message.reply_to_message and message.reply_to_message.from_user else (message.from_user.first_name if message.from_user else "User")
            card_text = (
                f"{_afk_card(
                    user_name,
                    since_label,
                    _format_since_time(since_timestamp),
                    reason,
                    bool(afk_entry.get('is_global', False)),
                    media_payload.get('media_type', 'text'),
                    media_payload.get('caption', ''),
                )}\n"
                f"<i>Triggered by:</i> {message.from_user.first_name}"
            )
            if media_payload.get("media_type", "text") == "text":
                await _send_text_message(message.chat.id, card_text, message.id)
            else:
                await _send_afk_media(message.chat.id, message.id, media_payload, caption_override=card_text)
    except Exception as exc:
        logger.exception("AFK notification failed: %s", exc)


async def _run_welcome_back(client, message: Message, user, *, force_local=False, force_global=False):
    chat_id = message.chat.id
    user_id = user.id

    local = await _get_afk_entry(user_id, chat_id)
    global_entry = None
    if local and local.get("is_global"):
        global_entry = local
        local = None
    else:
        try:
            collection = await _get_collection(AFK_COLLECTION)
            if _is_collection_available(collection):
                global_doc = await collection.find_one({"user_id": user_id, "is_global": True})
                if global_doc:
                    global_entry = await _normalize_afk_document(global_doc)
        except Exception:
            global_entry = None

    remove_local = bool(local) and (force_local or not force_global)
    remove_global = bool(global_entry) and (force_global or not force_local)

    if force_local and not force_global:
        remove_global = False
    if force_global and not force_local:
        remove_local = False

    picked = local or global_entry
    if not picked:
        return False

    if not await _claim_welcome_back(chat_id, user_id, ttl=5):
        if remove_local and local:
            await _remove_afk_entry(user_id, chat_id, False)
        if remove_global and global_entry:
            await _remove_afk_entry(user_id, chat_id, True)
        return False

    started = float(picked.get("time") or picked.get("since") or time.time())
    reason = picked.get("reason") or ""
    media_payload = {
        "media_type": picked.get("media_type", "text"),
        "media_file_id": picked.get("media_file_id", ""),
        "caption": picked.get("caption", ""),
    }
    duration = _format_duration(time.time() - started)

    if remove_local and local:
        await _remove_afk_entry(user_id, chat_id, False)
    if remove_global and global_entry:
        await _remove_afk_entry(user_id, chat_id, True)

    await _send_welcome_back(
        chat_id=chat_id,
        reply_to=message.id,
        user=user,
        reason=reason,
        duration=duration,
        media_payload=media_payload,
    )
    return True


async def _handle_afk_command(message: Message, is_global: bool, remove: bool = False) -> None:
    if not message.from_user:
        return

    try:
        if remove:
            existing = await _get_afk_entry(message.from_user.id, message.chat.id)
            removed = await _remove_afk_entry(message.from_user.id, message.chat.id, is_global)
            if removed:
                start_time = int(existing.get("time", int(time.time())) if existing else int(time.time()))
                duration = _format_duration(int(time.time()) - start_time)
                await _send_text_message(message.chat.id, f"<b>✅ AFK removed.</b>\n\n⏱ <b>Duration:</b> {duration}", message.id)
            else:
                await _send_text_message(message.chat.id, "<b>⚠️ You were not marked AFK.</b>", message.id)
            return

        reason = "No reason provided"
        text = message.text or message.caption or ""

        if message.command:
            parts = message.command
            if len(parts) > 1:
                reason = " ".join(parts[1:])
            elif message.reply_to_message:
                reason = message.reply_to_message.text or message.reply_to_message.caption or "No reason provided"
            elif text:
                reason = text
        elif message.reply_to_message:
            reason = message.reply_to_message.text or message.reply_to_message.caption or "No reason provided"
        elif text:
            reason = text

        media_payload = await _extract_media_data(message)
        if message.reply_to_message:
            reply_media = await _extract_media_data(message.reply_to_message)
            if reply_media.get("media_type") != "text" or message.reply_to_message.text:
                media_payload = reply_media
            elif media_payload.get("media_type") == "text":
                media_payload = {"media_type": "text", "media_file_id": "", "caption": ""}

        saved = await _save_afk_entry(message.from_user.id, message.chat.id, reason, is_global, media_payload, username=message.from_user.username)
        if saved:
            user_name = message.from_user.first_name or message.from_user.username or "User"
            card = _afk_card(
                user_name,
                "Now",
                _format_since_time(int(time.time())),
                reason,
                is_global,
                media_payload.get("media_type", "text"),
                media_payload.get("caption", ""),
            )
            if media_payload.get("media_type", "text") == "text":
                await _send_text_message(message.chat.id, card, message.id)
            else:
                await _send_afk_media(message.chat.id, message.id, media_payload, caption_override=card)
        else:
            await _send_text_message(message.chat.id, "<b>⚠️ AFK mode could not be activated.</b>", message.id)
    except Exception as exc:
        logger.exception("AFK command failed: %s", exc)
        await _send_text_message(message.chat.id, "<b>⚠️ Something went wrong while handling AFK.</b>", message.id)


async def _handle_afk_list(message: Message) -> None:
    try:
        entries = await _list_afk_entries(message.chat.id)
        if not entries:
            await _send_text_message(message.chat.id, "<b>📭 No AFK users right now.</b>", message.id)
            return
        lines = [f"{DIVIDER}", "<b>💤 AFK LIST</b>", ""]
        for entry in entries[:20]:
            user_id = entry.get("user_id") or entry.get("_id") or 0
            if not user_id:
                continue
            scope = "Global" if entry.get("is_global") else "Local"
            duration = _format_age(int(entry.get("time", int(time.time()))))
            reason = (entry.get("reason") or "None").strip() or "None"
            lines.append(f"• User #{user_id} | {scope} | {duration} | {reason}")
        lines.append(DIVIDER)
        await _send_text_message(message.chat.id, "\n".join(lines), message.id)
    except Exception as exc:
        logger.exception("AFK list failed: %s", exc)


async def _handle_regular_message(message: Message) -> None:
    if not message.from_user or message.from_user.is_self:
        return
    if message.command:
        return
    try:
        afk_entry = await _get_afk_entry(message.from_user.id, message.chat.id)
        if not afk_entry:
            await _handle_afk_notification(message)
            return
        await _remove_afk_entry(message.from_user.id, message.chat.id, bool(afk_entry.get("is_global", False)))
        duration_label = _format_duration(int(time.time()) - int(afk_entry.get("time", int(time.time()))))
        media_payload = {
            "media_type": afk_entry.get("media_type", "text"),
            "media_file_id": afk_entry.get("media_file_id", ""),
            "caption": afk_entry.get("caption", ""),
        }
        await _send_welcome_back(
            message.chat.id,
            message.id,
            message.from_user,
            afk_entry.get("reason", "No reason provided"),
            duration_label,
            media_payload=media_payload,
        )
    except Exception as exc:
        logger.exception("Welcome back handling failed: %s", exc)


@app.on_message(filters.command(["afk"], prefixes=["/", ".", "!"]) & filters.group & ~app.bl_users, group=9)
async def afk_handler(client, message: Message):
    await _handle_afk_command(message, is_global=False, remove=False)


@app.on_message(filters.command(["gafk"], prefixes=["/", ".", "!"]) & filters.group & ~app.bl_users, group=9)
async def gafk_handler(client, message: Message):
    await _handle_afk_command(message, is_global=True, remove=False)


@app.on_message(filters.command(["unafk"], prefixes=["/", ".", "!"]) & filters.group & ~app.bl_users, group=9)
async def unafk_handler(client, message: Message):
    await _handle_afk_command(message, is_global=False, remove=True)


@app.on_message(filters.command(["ungafk"], prefixes=["/", ".", "!"]) & filters.group & ~app.bl_users, group=9)
async def ungafk_handler(client, message: Message):
    await _handle_afk_command(message, is_global=True, remove=True)


@app.on_message(filters.command(["afklist"], prefixes=["/", ".", "!"]) & filters.group & ~app.bl_users, group=9)
async def afklist_handler(client, message: Message):
    await _handle_afk_list(message)


_AFK_CMD_RE = re.compile(r"^[!./](afk|gafk|unafk|ungafk|afklist)(@\w+)?(\s|$)", re.IGNORECASE)


def _is_afk_command(message: Message) -> bool:
    text = (message.text or message.caption or "").strip()
    if not text:
        return False
    return bool(_AFK_CMD_RE.match(text))


@app.on_message(filters.group & ~app.bl_users, group=10)
async def afk_watcher(client, message: Message):
    if not message.from_user:
        return

    sender = message.from_user

    if not _is_afk_command(message):
        local = await _get_afk_entry(sender.id, message.chat.id)
        if local:
            await _run_welcome_back(client, message, sender)
            return

    if _is_afk_command(message):
        return

    try:
        targets = await _resolve_mention_targets(message)
    except Exception:
        targets = []

    if not targets:
        return

    noticed: set = set()
    for target in targets:
        if target in noticed:
            continue

        record = await _get_afk_entry(target, message.chat.id)
        if not record:
            continue

        if not await _claim_afk_notification(message.chat.id, target, ttl=5):
            noticed.add(target)
            continue

        started = float(record.get("time") or record.get("since") or time.time())
        reason = record.get("reason") or ""
        media_payload = {
            "media_type": record.get("media_type", "text"),
            "media_file_id": record.get("media_file_id", ""),
            "caption": record.get("caption", ""),
        }

        duration = _format_duration(time.time() - started)
        since = _format_since_time(started)
        text = _afk_card(_mention(await app.get_users(target)), duration, since, reason, bool(record.get("is_global", False)))
        await _send_afk_reply(message, text, media_payload)
        noticed.add(target)


async def _send_afk_reply(message: Message, text: str, media_payload: Dict[str, Any]) -> None:
    try:
        if media_payload.get("media_type", "text") != "text":
            await _send_afk_media(message.chat.id, message.id, media_payload, caption_override=text)
        else:
            await _send_text_message(message.chat.id, text, message.id)
    except Exception as exc:
        logger.exception("Failed to deliver AFK reply: %s", exc)


__all__ = ["afk_handler", "gafk_handler", "unafk_handler", "ungafk_handler", "afklist_handler", "afk_watcher"]
