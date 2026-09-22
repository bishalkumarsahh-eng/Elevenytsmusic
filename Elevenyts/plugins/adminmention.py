from pyrogram import filters, types, enums
from Elevenyts import app, config

@app.on_message(filters.group & filters.command("admin"))
async def mention_admins(_, message: types.Message):
    try:
        sender = message.from_user
        reported_by = (sender.first_name or "User") if sender else "Anonymous Admin"
        if sender and sender.username:
            reported_by += f" (@{sender.username})"
        excluded = {u.lstrip("@").lower() for u in config.EXCLUDED_USERNAMES if u}
        mentions = []
        for member in await app.get_chat_administrators(message.chat.id):
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                continue
            privileges = getattr(member, "privileges", None)
            if privileges and getattr(privileges, "is_anonymous", False):
                continue
            if user.username and user.username.lower() in excluded:
                continue
            if user.username:
                mentions.append(f"@{user.username}")
            else:
                mentions.append(f'<a href="tg://user?id={user.id}">{user.first_name or "Admin"}</a>')
        if mentions:
            text = f"<blockquote>🔔 <b>Admin requested</b>\nReported by: {reported_by}</blockquote>\n\n" + ", ".join(mentions)
        else:
            text = "<blockquote>❌ No visible human admins found.</blockquote>"
        await message.reply_text(text, disable_web_page_preview=True)
    except Exception as e:
        try:
            await message.reply_text("<blockquote>❌ I couldn't fetch the group administrators. Make sure I am a member of this group and try again.</blockquote>")
        except Exception:
            pass
