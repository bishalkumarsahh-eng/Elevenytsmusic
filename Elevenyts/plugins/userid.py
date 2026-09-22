from pyrogram import Client, filters, types
from Elevenyts import app

def _user_link(user):
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.id}">{user.first_name or "User"}</a>'

@app.on_message(filters.command("id"))
async def getid(client: Client, message: types.Message):
    try:
        if not message.from_user:
            await message.reply_text("❌ I couldn't identify the sender of this message.")
            return
        target = message.from_user
        if message.command and len(message.command) > 1:
            try:
                target = await client.get_users(message.command[1].strip())
            except Exception:
                await message.reply_text("❌ User not found. Use /id or /id @username.")
                return
        text = f"<b>👤 User ID</b>\nName: {_user_link(target)}\nID: <code>{target.id}</code>"
        if message.chat and message.chat.type in ("group", "supergroup"):
            text += f"\nChat ID: <code>{message.chat.id}</code>"
        await message.reply_text(text, disable_web_page_preview=True)
    except Exception:
        try:
            await message.reply_text("❌ Failed to get the user ID.")
        except Exception:
            pass
