from pyrogram import filters, types, enums
from Elevenyts import app, logger


def _escape(text):
    if not text:
        return "User"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _mention(user):
    name = _escape(getattr(user, "first_name", None) or "User")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


@app.on_message(filters.command("id", prefixes=["/"]))
async def getid(client, message: types.Message):
    try:
        target = None
        # /id <reply> -> replied user's ID
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user

        # /id @username or /id user_id
        if len(message.command) > 1:
            query = message.command[1].strip()
            try:
                target = await client.get_users(query)
            except Exception as e:
                logger.warning("/id lookup failed for %r: %s", query, e)
                await message.reply_text("❌ User not found. Try replying to their message and use /id.")
                return

        # Plain /id -> command sender
        if target is None:
            target = message.from_user

        if target is None:
            await message.reply_text("❌ Telegram did not provide a user for this message. Reply to a user's message and use /id.")
            return

        lines = [
            "<b>👤 USER INFORMATION</b>",
            f"Name: {_mention(target)}",
            f"ID: <code>{target.id}</code>",
        ]
        if getattr(target, "username", None):
            lines.append(f"Username: @{target.username}")
        if message.chat and message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            lines.append(f"Chat ID: <code>{message.chat.id}</code>")

        await message.reply_text("\n".join(lines), disable_web_page_preview=True)
    except Exception as e:
        logger.exception("/id failed: %s", e)
        await message.reply_text("❌ Failed to get the user ID. Reply to the user's message and try /id again.")
