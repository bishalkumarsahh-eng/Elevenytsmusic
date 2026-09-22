from pyrogram import filters, types, enums
from Elevenyts import app, config, logger

@app.on_message(filters.command("admin", prefixes=["/"]) & (filters.group | filters.private))
async def mention_admins(client, message: types.Message):
    if not message.chat or message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        await message.reply_text("❌ /admin can only be used in a group.")
        return
    try:
        admins = []
        async for member in client.get_chat_members(message.chat.id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                continue
            privileges = getattr(member, "privileges", None)
            if privileges and getattr(privileges, "is_anonymous", False):
                continue
            admins.append(user)

        excluded = {str(u).lstrip("@").lower() for u in getattr(config, "EXCLUDED_USERNAMES", []) if u}
        mentions = []
        seen = set()
        for user in admins:
            if user.id in seen or (user.username and user.username.lower() in excluded):
                continue
            seen.add(user.id)
            if user.username:
                mentions.append(f"@{user.username}")
            else:
                name = (user.first_name or "Admin").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                mentions.append(f'<a href="tg://user?id={user.id}">{name}</a>')

        sender = message.from_user
        reported_by = "Anonymous"
        if sender:
            reported_by = sender.first_name or "User"
            if sender.username:
                reported_by += f" (@{sender.username})"

        if not mentions:
            await message.reply_text("<blockquote>❌ No visible human admins found.</blockquote>")
            return

        text = f"<blockquote>🔔 <b>Admin requested</b>\nReported by: {reported_by}</blockquote>\n\n" + ", ".join(mentions)
        await message.reply_text(text, disable_web_page_preview=True)
    except Exception as e:
        logger.exception("/admin failed for chat %s: %s", getattr(message.chat, "id", None), e)
        await message.reply_text("<blockquote>❌ I couldn't fetch the group administrators. Please make sure I am a member of this group and have permission to view administrators.</blockquote>")
