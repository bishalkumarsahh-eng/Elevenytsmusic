# ArtistMusic Font System
# Usage: /font Bishal
# The bot shows Rich Inline Buttons; clicking one sends the supplied text.

import secrets
import time
from typing import Dict

from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from Elevenyts import app, logger

_PENDING: Dict[str, dict] = {}
TTL = 300

_STYLE_SPECS = {
    "bold": (0x1D400, 0x1D41A, 0x1D7CE),
    "italic": (0x1D434, 0x1D44E, None),
    "bolditalic": (0x1D468, 0x1D482, None),
    "script": (0x1D49C, 0x1D4B6, None),
    "boldscript": (0x1D4D0, 0x1D4EA, None),
    "fraktur": (0x1D504, 0x1D51E, None),
    "boldfraktur": (0x1D56C, 0x1D586, None),
    "double": (0x1D538, 0x1D552, None),
    "sans": (0x1D5A0, 0x1D5BA, 0x1D7E2),
    "sansbold": (0x1D5D4, 0x1D5EE, 0x1D7EC),
    "sansitalic": (0x1D608, 0x1D622, None),
    "sansbolditalic": (0x1D63C, 0x1D656, None),
    "monospace": (0x1D670, 0x1D68A, 0x1D7F6),
}

_SPECIAL = {
    ("script", "C"): "ℭ", ("script", "H"): "ℋ", ("script", "I"): "ℐ", ("script", "R"): "ℛ", ("script", "Z"): "ℤ",
    ("double", "C"): "ℂ", ("double", "H"): "ℍ", ("double", "N"): "ℕ", ("double", "P"): "ℙ", ("double", "Q"): "ℚ", ("double", "R"): "ℝ", ("double", "Z"): "ℤ",
    ("script", "e"): "ℯ", ("script", "g"): "ℊ", ("script", "o"): "ℴ",
}

_CIRCLED = {c: chr(0x24B6 + i) for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
_CIRCLED.update({c: chr(0x24D0 + i) for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")})
_CIRCLED.update({str(i): ("⓪" if i == 0 else chr(0x2460 + i - 1)) for i in range(10)})

_SQUARED = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "🅰🅱🅲🅳🅴🅵🅶🅷🅸🅹🅺🅻🅼🅽🅾🅿🆀🆁🆂🆃🆄🆅🆆🆇🆈🆉"))
_FULLWIDTH = {chr(ord('A') + i): chr(0xFF21 + i) for i in range(26)}
_FULLWIDTH.update({chr(ord('a') + i): chr(0xFF41 + i) for i in range(26)})
_FULLWIDTH.update({str(i): chr(0xFF10 + i) for i in range(10)})
_SMALLCAPS = str.maketrans(dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ")))


def _convert_char(ch: str, style: str) -> str:
    if style == "circled":
        return _CIRCLED.get(ch, _CIRCLED.get(ch.upper(), ch))
    if style == "squared":
        return _SQUARED.get(ch.upper(), ch)
    if style == "fullwidth":
        return _FULLWIDTH.get(ch, ch)
    if style == "smallcaps":
        return ch.translate(_SMALLCAPS)
    # Unicode has no separate plain serif/Times-Roman alphabet; normal text is
    # the closest text-only representation.
    if style == "serif":
        return ch
    if style == "serifbold":
        # Unicode has no true Times/serif-bold alphabet; use Unicode bold as the
        # closest text-only representation.
        spec = _STYLE_SPECS["bold"]
        upper, lower, digits = spec
        if "A" <= ch <= "Z":
            return chr(upper + ord(ch) - 65)
        if "a" <= ch <= "z":
            return chr(lower + ord(ch) - 97)
        if digits is not None and "0" <= ch <= "9":
            return chr(digits + ord(ch) - 48)
        return ch

    spec = _STYLE_SPECS.get(style)
    if not spec:
        return ch
    upper, lower, digits = spec
    if (style, ch) in _SPECIAL:
        return _SPECIAL[(style, ch)]
    if "A" <= ch <= "Z":
        return chr(upper + ord(ch) - 65)
    if "a" <= ch <= "z":
        return chr(lower + ord(ch) - 97)
    if digits is not None and "0" <= ch <= "9":
        return chr(digits + ord(ch) - 48)
    return ch


def stylize(text: str, style: str) -> str:
    return "".join(_convert_char(ch, style) for ch in text)


def _cleanup():
    now = time.time()
    for token, data in list(_PENDING.items()):
        if now - data["time"] > TTL:
            _PENDING.pop(token, None)


def _buttons(token: str) -> InlineKeyboardMarkup:
    labels = [
        ("ㅤㅤㅤㅤㅤ𝗕𝗼𝗹𝗱ㅤㅤㅤㅤㅤ", "bold"), ("ㅤㅤㅤㅤㅤ𝘐𝘵𝘢𝘭𝘪𝘤ㅤㅤㅤㅤㅤ", "italic"),
        ("ㅤㅤㅤ𝑩𝒐𝒍𝒅 𝑰𝒕𝒂𝒍𝒊𝒄ㅤㅤㅤ", "bolditalic"), ("ㅤㅤㅤㅤㅤ𝒮𝒸𝓇𝒾𝓅𝓉ㅤㅤㅤㅤㅤ", "script"),
        ("ㅤㅤㅤ𝓑𝓸𝓵𝓭 𝓢𝓬𝓻𝓲𝓹𝓽ㅤㅤㅤ", "boldscript"), ("ㅤㅤㅤㅤㅤ𝔉𝔯𝔞𝔨𝔱𝔲𝔯ㅤㅤㅤㅤㅤ", "fraktur"),
        ("ㅤㅤㅤ𝕭𝖔𝖑𝖉 𝕱𝖗𝖆𝖐𝖙𝖚𝖗ㅤㅤㅤ", "boldfraktur"), ("ㅤㅤㅤㅤㅤ𝔻𝕠𝕦𝕓𝕝𝕖ㅤㅤㅤㅤㅤ", "double"),
        ("ㅤㅤㅤㅤㅤ𝖲𝖺𝗇𝗌ㅤㅤㅤㅤㅤ", "sans"), ("ㅤㅤㅤㅤ𝗦𝗮𝗻𝘀 𝗕𝗼𝗹𝗱ㅤㅤㅤㅤ", "sansbold"),
        ("ㅤㅤㅤㅤ𝘚𝘢𝘯𝘴 𝘐𝘵𝘢𝘭𝘪𝘤ㅤㅤㅤㅤ", "sansitalic"), ("ㅤㅤㅤㅤ𝙎𝙖𝙣𝙨 𝘽𝙤𝙡𝙙ㅤㅤㅤㅤ", "sansbolditalic"),
        ("ㅤㅤㅤㅤㅤ𝙼𝚘𝚗𝚘ㅤㅤㅤㅤㅤ", "monospace"), ("ㅤㅤㅤSerif / Timesㅤㅤㅤ", "serif"),
        ("ㅤㅤㅤㅤㅤ𝐒𝐞𝐫𝐢𝐟 𝐁𝐨𝐥𝐝ㅤㅤㅤㅤㅤㅤ", "serifbold"),
        ("ㅤㅤㅤⒸⓘⓡⓒⓛⓔⓓㅤㅤㅤ", "circled"),
        ("ㅤㅤ🅂🅀🅄🄰🅁🄴ㅤㅤ", "squared"), ("Ｆｕｌｌｗｉｄｔｈ", "fullwidth"),
        ("ㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤSᴍᴀʟʟ Cᴀᴘsㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ", "smallcaps"),
    ]
    rows = []
    for i in range(0, len(labels), 2):
        row = [InlineKeyboardButton(labels[i][0], callback_data=f"font:{token}:{labels[i][1]}")]
        if i + 1 < len(labels):
            row.append(InlineKeyboardButton(labels[i + 1][0], callback_data=f"font:{token}:{labels[i + 1][1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data=f"font:{token}:cancel")])
    return InlineKeyboardMarkup(rows)


@app.on_message(filters.command("font") & ~app.bl_users)
async def font_command(client, message: Message):
    """Use /font TEXT, e.g. /font Bishal."""
    if not message.from_user:
        return

    # /font Bishal -> "Bishal"
    text = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""

    # Also allow /font followed by text on the next line.
    if not text and message.text:
        parts = message.text.split(None, 1)
        if len(parts) == 2:
            text = parts[1].strip()

    if not text:
        return await message.reply_text(
            "❗ <b>Usage:</b> <code>/font Bishal</code>\n\n"
            "Example: <code>/font Hello World</code>"
        )

    if len(text) > 4096:
        return await message.reply_text("❌ Text is too long. Maximum is 4096 characters.")

    _cleanup()
    token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:10]
    _PENDING[token] = {
        "user_id": message.from_user.id,
        "chat_id": message.chat.id,
        "text": text,
        "time": time.time(),
    }

    await message.reply_text(
        f"✨ <b>Choose a font for:</b>\n<code>{text}</code>",
        reply_markup=_buttons(token),
    )


@app.on_callback_query(filters.regex(r"^font:[^:]+:[a-z]+$"))
async def font_callback(client, callback_query: CallbackQuery):
    _cleanup()
    try:
        _, token, style = callback_query.data.split(":", 2)
    except ValueError:
        return await callback_query.answer("Invalid font request.", show_alert=True)

    data = _PENDING.get(token)
    if not data:
        return await callback_query.answer("This font menu has expired.", show_alert=True)

    if callback_query.from_user.id != data["user_id"]:
        return await callback_query.answer("Only the person who used /font can choose it.", show_alert=True)

    _PENDING.pop(token, None)
    if style == "cancel":
        await callback_query.answer("Cancelled.")
        try:
            await callback_query.message.edit_text("❌ <b>Font selection cancelled.</b>")
        except Exception:
            pass
        return

    result = stylize(data["text"], style)
    await callback_query.answer("Font selected!")
    await client.send_message(data["chat_id"], result)
    try:
        await callback_query.message.edit_text("✅ <b>Font selected.</b>")
    except Exception:
        pass
