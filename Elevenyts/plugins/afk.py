# ==========================================================
# Copyright (c) 2026 Juno X Music
# All Rights Reserved.
# ==========================================================

import time
import re
from typing import Dict, List, Tuple
from collections import defaultdict

from pyrogram import filters, types
import pymongo
import asyncio

from Elevenyts import config, tasks, db

from Elevenyts import app

AFK_USERS: Dict[int, Dict[str, object]] = {}
AFK_MENTIONS: Dict[int, List[Dict[str, object]]] = defaultdict(list)
AFK_HEADER = "❖ ⎯꯭̽🦚⤹‌⋆‌‌‌‌𝅃͢𝐓𝛋֟͡‌‌‌𝐬 ≛ ͓͢‌‌𝛃 ͓𝛊֟͜͡ ͓𝛅 ͓𝝸̵̵𝐥 ͓𝛌 ͓𝐥 ⤹💙ˎ˗"

# How many seconds to wait before sending another AFK auto-reply to the same sender
DEFAULT_REPLY_COOLDOWN = 300  # 5 minutes
MONGO_AFK_COLLECTION = None
MONGO_AFK_SETTINGS = None


def _init_mongo_collections():
    global MONGO_AFK_COLLECTION, MONGO_AFK_SETTINGS
    try:
        client = pymongo.MongoClient(config.MONGO_URL, serverSelectionTimeoutMS=5000)
        dbname = client.get_default_database().name if client.get_default_database() else "elevenyts"
        coll = client[dbname]
        MONGO_AFK_COLLECTION = coll["afk_entries"]
        MONGO_AFK_SETTINGS = coll["afk_settings"]
    except Exception:
        MONGO_AFK_COLLECTION = None
        MONGO_AFK_SETTINGS = None


def _persist_afk(user_id: int, data: Dict[str, object]):
    """Persist AFK entry to MongoDB (best-effort)."""
    if not MONGO_AFK_COLLECTION:
        return
    try:
        MONGO_AFK_COLLECTION.update_one({"user_id": user_id}, {"$set": data}, upsert=True)
    except Exception:
        return


def _remove_afk_persist(user_id: int):
    if not MONGO_AFK_COLLECTION:
        return
    try:
        MONGO_AFK_COLLECTION.delete_one({"user_id": user_id})
    except Exception:
        return


async def _load_persisted_afk():
    if not MONGO_AFK_COLLECTION:
        return
    try:
        for doc in MONGO_AFK_COLLECTION.find({}):
            uid = int(doc.get("user_id"))
            AFK_USERS[uid] = doc.get("data", {})
    except Exception:
        return


async def _afk_expiry_worker():
    """Background task to expire timed AFK entries and optionally notify users."""
    while True:
        now = time.time()
        expired = []
        for uid, state in list(AFK_USERS.items()):
            until = state.get("until")
            if until and now > until:
                expired.append((uid, state))

        for uid, state in expired:
            # Remove and persist removal
            AFK_USERS.pop(uid, None)
            AFK_MENTIONS.pop(uid, None)
            _remove_afk_persist(uid)
            # Try to DM the user to notify them their AFK expired
            try:
                # best-effort; user may not have started bot
                await app.send_message(uid, "Your AFK period has ended and AFK status was cleared.")
            except Exception:
                pass

        await asyncio.sleep(60)


# initialize mongo collections at import time (best-effort)
_init_mongo_collections()
tasks.append(asyncio.create_task(_afk_expiry_worker()))


def _parse_duration_token(token: str) -> int:
    """Parse a simple duration token like '30s', '10m', '2h', '1d' into seconds.
    Returns seconds or 0 if unparsable.
    """
    match = re.match(r"^(\d+)([smhd])$", token.lower())
    if not match:
        return 0
    value, unit = match.groups()
    value = int(value)
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    return 0


def _parse_kv_tokens(tokens: List[str]) -> Dict[str, object]:
    """Parse tokens like 'cd=30s' or 'msg=Busy' or 'scope=chat' into a dict."""
    out = {}
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            out[k.lower()] = v
    return out


def _chat_opted_out(chat_id: int) -> bool:
    if not MONGO_AFK_SETTINGS:
        return False
    try:
        doc = MONGO_AFK_SETTINGS.find_one({"chat_id": chat_id})
        if not doc:
            return False
        return bool(doc.get("disabled", False))
    except Exception:
        return False


def _format_duration(seconds: int) -> str:
    """Format seconds into a human-readable duration string."""
    seconds = max(seconds, 0)
    if seconds < 60:
        return f"{seconds} seconds"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    hours = minutes // 60
    minutes = minutes % 60
    if minutes > 0:
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''}"


def _build_afk_message(name: str = "", reason: str = "", seconds: int = 0, dnd: bool = False) -> str:
    """Build an AFK notification message."""
    mode = "DND" if dnd else "AFK"
    text = f"{AFK_HEADER} is now {mode}!" if not name else f"{AFK_HEADER} {name} is now {mode}!"
    if reason:
        text += f"\n● Reason: {reason}"
    text += f"\n● Away for: {_format_duration(seconds)}"
    return text


def _build_back_message(seconds: int = 0, mentions: int = 0) -> str:
    """Build a welcome back message with activity stats."""
    text = f"❖ Welcome back {AFK_HEADER}!\n● Away for: {_format_duration(seconds)}"
    if mentions > 0:
        text += f"\n● You were mentioned {mentions} time{'s' if mentions != 1 else ''}"
    return text


def _get_user_identifier(user: types.User) -> Tuple[int, str, str]:
    """Extract user identification info."""
    return user.id, user.username or "", user.first_name or "User"


def _track_mention(user_id: int, mention_data: Dict[str, object]):
    """Track a mention for an AFK user."""
    AFK_MENTIONS[user_id].append(mention_data)
    # Keep only last 50 mentions
    if len(AFK_MENTIONS[user_id]) > 50:
        AFK_MENTIONS[user_id] = AFK_MENTIONS[user_id][-50:]


@app.on_message(filters.command(["afk", "away"]))
async def afk_set(_, message: types.Message):
    """Set user as AFK with optional reason."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    tokens = message.command[1:]
    duration_seconds = 0
    reason = ""
    custom = _parse_kv_tokens(tokens)

    # Duration may be first token
    if tokens:
        first = tokens[0]
        dur = _parse_duration_token(first)
        if dur > 0:
            duration_seconds = dur
            tokens = tokens[1:]

    # Remove kv tokens from tokens list for reason assembly
    tokens = [t for t in tokens if ("=" not in t)]
    if tokens:
        reason = " ".join(tokens).strip()

    # Determine scope: 'chat' or 'global'
    scope = custom.get("scope") or custom.get("s")
    if scope and scope.lower() == "chat" and message.chat:
        scope_val = message.chat.id
    else:
        scope_val = "global"

    # custom cooldown
    cd = DEFAULT_REPLY_COOLDOWN
    if custom.get("cd"):
        cd_val = _parse_duration_token(custom.get("cd"))
        if cd_val > 0:
            cd = cd_val

    AFK_USERS[user_id] = {
        "reason": reason,
        "time": time.time(),
        "until": time.time() + duration_seconds if duration_seconds > 0 else None,
        "username": message.from_user.username,
        "name": message.from_user.first_name or "User",
        "dnd": False,
        "scope": scope_val,
        "last_activity": time.time(),
        "mention_count": 0,
        "last_notified": {},
        "reply_cooldown": cd,
        "custom_msg": custom.get("msg") or None,
    }

    # Persist
    _persist_afk(user_id, {"user_id": user_id, "data": AFK_USERS[user_id]})

    extra = f" (for {_format_duration(duration_seconds)})" if duration_seconds > 0 else ""
    await message.reply_text(_build_afk_message(reason=reason + extra if reason else reason, seconds=0, dnd=False))


@app.on_message(filters.command(["dnd", "donotdisturb"]))
async def dnd_set(_, message: types.Message):
    """Set user as DND (Do Not Disturb) - stricter AFK that doesn't auto-clear."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    tokens = message.command[1:]
    duration_seconds = 0
    reason = ""
    custom = _parse_kv_tokens(tokens)

    if tokens:
        first = tokens[0]
        dur = _parse_duration_token(first)
        if dur > 0:
            duration_seconds = dur
            tokens = tokens[1:]

    tokens = [t for t in tokens if ("=" not in t)]
    if tokens:
        reason = " ".join(tokens).strip()

    scope = custom.get("scope") or custom.get("s")
    if scope and scope.lower() == "chat" and message.chat:
        scope_val = message.chat.id
    else:
        scope_val = "global"

    cd = DEFAULT_REPLY_COOLDOWN
    if custom.get("cd"):
        cd_val = _parse_duration_token(custom.get("cd"))
        if cd_val > 0:
            cd = cd_val

    AFK_USERS[user_id] = {
        "reason": reason,
        "time": time.time(),
        "until": time.time() + duration_seconds if duration_seconds > 0 else None,
        "username": message.from_user.username,
        "name": message.from_user.first_name or "User",
        "dnd": True,
        "scope": scope_val,
        "last_activity": time.time(),
        "mention_count": 0,
        "last_notified": {},
        "reply_cooldown": cd,
        "custom_msg": custom.get("msg") or None,
    }

    _persist_afk(user_id, {"user_id": user_id, "data": AFK_USERS[user_id]})

    extra = f" (for {_format_duration(duration_seconds)})" if duration_seconds > 0 else ""
    await message.reply_text(_build_afk_message(reason=reason + extra if reason else reason, seconds=0, dnd=True))


@app.on_message(filters.command(["afkoff", "back", "dndoff"]))
async def afk_clear(_, message: types.Message):
    """Remove AFK/DND status and show statistics."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    state = AFK_USERS.get(user_id)
    
    if not state:
        await message.reply_text("❌ You are not AFK!")
        return
    
    elapsed = int(time.time() - state.get("time", time.time()))
    mention_count = len(AFK_MENTIONS.get(user_id, []))
    
    # Build welcome back message
    text = _build_back_message(seconds=elapsed, mentions=mention_count)
    
    # Add mention details if any
    if AFK_MENTIONS.get(user_id):
        text += "\n\n**📌 Mentions:**"
        for mention_data in AFK_MENTIONS[user_id][-10:]:  # Show last 10
            text += f"\n• {mention_data.get('sender', 'Unknown')} in {mention_data.get('chat', 'Unknown')}"
    
    # Clean up
    AFK_USERS.pop(user_id, None)
    AFK_MENTIONS.pop(user_id, None)
    _remove_afk_persist(user_id)
    
    await message.reply_text(text)


@app.on_message(filters.command(["afklist", "whoisafk"]))
async def afk_list(_, message: types.Message):
    """Show list of all AFK users."""
    if not AFK_USERS:
        await message.reply_text("❌ No users are AFK right now!")
        return
    
    text = "**📋 AFK Users:**\n"
    for user_id, state in AFK_USERS.items():
        name = state.get("name", "Unknown")
        reason = state.get("reason", "No reason")
        elapsed = int(time.time() - state.get("time", time.time()))
        dnd = "🔴 DND" if state.get("dnd") else "💛 AFK"
        mentions = len(AFK_MENTIONS.get(user_id, []))
        mention_str = f" ({mentions} mentions)" if mentions > 0 else ""
        until = state.get("until")
        until_str = ""
        if until:
            remaining = int(until - time.time())
            if remaining > 0:
                until_str = f" • Expires in: {_format_duration(remaining)}"
            else:
                until_str = " • (expired)"
        text += f"\n• {name} {dnd}{mention_str}\n  ⏱ Away: {_format_duration(elapsed)}{until_str}\n  📝 {reason}"
    
    await message.reply_text(text)


@app.on_message(filters.command(["afkstats"]))
async def afk_stats(_, message: types.Message):
    """Show personal AFK statistics."""
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    state = AFK_USERS.get(user_id)
    
    if not state:
        await message.reply_text("❌ You are not AFK!")
        return
    
    elapsed = int(time.time() - state.get("time", time.time()))
    mention_count = len(AFK_MENTIONS.get(user_id, []))
    mode = "🔴 DND Mode" if state.get("dnd") else "💛 AFK Mode"
    until = state.get("until")
    until_str = ""
    if until:
        remaining = int(until - time.time())
        if remaining > 0:
            until_str = f"\n• Expires in: {_format_duration(remaining)}"
        else:
            until_str = "\n• Expires in: (expired)"

    text = f"""**📊 Your AFK Statistics:**

• Mode: {mode}
• Reason: {state.get('reason', 'None')}
• Away for: {_format_duration(elapsed)}{until_str}
• Mentions: {mention_count}
"""
    
    await message.reply_text(text)


@app.on_message(filters.text & ~filters.command & ~filters.service, group=25)
async def afk_reply(_, message: types.Message):
    """Handle AFK interactions and notifications."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    
    # If sender is AFK and not in DND mode, auto-disable AFK
    if user_id in AFK_USERS:
        state = AFK_USERS[user_id]
        if not state.get("dnd"):  # Only auto-clear if not in DND mode
            elapsed = int(time.time() - state.get("time", time.time()))
            AFK_USERS.pop(user_id, None)
            AFK_MENTIONS.pop(user_id, None)
            await message.reply_text(_build_back_message(seconds=elapsed, mentions=0))
        return

    # Check if replying to an AFK user
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        state = AFK_USERS.get(target_id)
        if state and target_id != user_id:
            # Expire timed AFK
            now = time.time()
            until = state.get("until")
            if until and now > until:
                AFK_USERS.pop(target_id, None)
                AFK_MENTIONS.pop(target_id, None)
                return

            # Respect per-chat opt-out
            if message.chat and _chat_opted_out(message.chat.id):
                return

            # Respect scope: if scoped to a chat, only reply inside that chat
            scope = state.get("scope")
            if scope != "global" and scope is not None:
                if not message.chat or message.chat.id != scope:
                    return

            reason = state.get("reason") or ""
            name = state.get("name") or message.reply_to_message.from_user.first_name or "User"
            elapsed = int(now - state.get("time", now))
            dnd = state.get("dnd", False)

            # Per-sender cooldown to avoid spamming the same person
            sender_id = message.from_user.id
            last_notified = state.get("last_notified", {})
            last = last_notified.get(sender_id, 0)
            cooldown = state.get("reply_cooldown", DEFAULT_REPLY_COOLDOWN)

            # Track mention data regardless
            _track_mention(target_id, {
                "sender": message.from_user.first_name or "Unknown",
                "chat": message.chat.title or "Private",
                "time": now,
            })

            if now - last < cooldown:
                # Update last activity but do not reply again
                state["last_activity"] = now
                return

            # Send reply and update tracking
            state.setdefault("last_notified", {})[sender_id] = now
            state["mention_count"] = state.get("mention_count", 0) + 1
            # Use custom message if provided
            if state.get("custom_msg"):
                await message.reply_text(state.get("custom_msg"))
            else:
                await message.reply_text(_build_afk_message(name=name, reason=reason, seconds=elapsed, dnd=dnd))
            return

    # Check for mentions
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mention = message.text[entity.offset : entity.offset + entity.length]
                username = mention.lstrip("@")
                for target_id, state in AFK_USERS.items():
                    if target_id != user_id and str(state.get("username") or "").lower() == username.lower():
                        now = time.time()
                        # Expire timed AFK
                        until = state.get("until")
                        if until and now > until:
                            AFK_USERS.pop(target_id, None)
                            AFK_MENTIONS.pop(target_id, None)
                            continue

                        # Respect per-chat opt-out
                        if message.chat and _chat_opted_out(message.chat.id):
                            continue

                        # Respect scope
                        scope = state.get("scope")
                        if scope != "global" and scope is not None:
                            if not message.chat or message.chat.id != scope:
                                continue

                        reason = state.get("reason") or ""
                        name = state.get("name") or username
                        elapsed = int(now - state.get("time", now))
                        dnd = state.get("dnd", False)

                        sender_id = message.from_user.id
                        last_notified = state.get("last_notified", {})
                        last = last_notified.get(sender_id, 0)
                        cooldown = state.get("reply_cooldown", DEFAULT_REPLY_COOLDOWN)

                        # Track mention data regardless
                        _track_mention(target_id, {
                            "sender": message.from_user.first_name or "Unknown",
                            "chat": message.chat.title or "Private",
                            "time": now,
                        })

                        if now - last < cooldown:
                            state["last_activity"] = now
                            continue

                        state.setdefault("last_notified", {})[sender_id] = now
                        state["mention_count"] = state.get("mention_count", 0) + 1
                        await message.reply_text(_build_afk_message(name=name, reason=reason, seconds=elapsed, dnd=dnd))
                        return
