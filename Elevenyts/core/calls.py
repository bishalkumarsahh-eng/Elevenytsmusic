# ==========================================================
# Copyright (c) 2026 ArtistBots
# All Rights Reserved.
#
# Project      : ArtistBots API Telegram Music Bot
# Powered By   : Artist
# Type         : API Based Telegram Music Bot
#
# Bot          : @ArtistApibot
# Channel      : https://t.me/artistbots
# GitHub       : https://github.com/elevenyts
#
# Unauthorized copying, modification, or redistribution
# of this source code without permission is prohibited.
# ==========================================================

import asyncio
import logging
from collections import defaultdict
from collections import defaultdict
from ntgcalls import ConnectionNotFound, TelegramServerError
from pyrogram import enums, errors
from pyrogram.errors import MessageIdInvalid
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from Elevenyts import app, config, db, lang, logger, preload, queue, userbot, yt
from Elevenyts.helpers import Media, Track, buttons, thumb
from Elevenyts.helpers.rich_player import send_player, edit_player

# Suppress pytgcalls harmless errors (library bugs - not critical)


class PyTgCallsErrorFilter(logging.Filter):
    def filter(self, record):
        # Filter out UpdateGroupCall errors
        if 'UpdateGroupCall' in record.getMessage():
            return False
        # Filter out ConnectionNotFound errors (happens when call ends but updates still arrive)
        if 'Connection with chat id' in record.getMessage() and 'not found' in record.getMessage():
            return False
        return True


logging.getLogger('pyrogram.dispatcher').addFilter(PyTgCallsErrorFilter())


class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        self._play_next_locks = {}  # Lock to prevent concurrent play_next calls per chat
        self._stream_end_cache = {}  # Cache to prevent duplicate stream end processing
        self._autoplay = defaultdict(bool)  # Per-chat autoplay state
        self._autoplay = defaultdict(bool)  # Per-chat autoplay state

    async def _edit_media_with_retry(self, message: Message, media_obj: InputMediaPhoto, reply_markup):
        """Edit media with basic FloodWait handling."""
        try:
            return await message.edit_media(media=media_obj, reply_markup=reply_markup)
        except errors.FloodWait as fw:
            await asyncio.sleep(fw.value + 1)
            try:
                return await message.edit_media(media=media_obj, reply_markup=reply_markup)
            except Exception:
                return None
        except errors.MessageNotModified:
            return None
        except Exception:
            return None

    async def _send_photo_with_retry(self, chat_id: int, photo, caption: str, reply_markup):
        """Send photo with FloodWait handling."""
        try:
            return await app.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
            )
        except errors.FloodWait as fw:
            await asyncio.sleep(fw.value + 1)
            try:
                return await app.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    reply_markup=reply_markup,
                )
            except Exception:
                return None
        except Exception:
            return None

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        try:
            await client.pause(chat_id)
            await db.playing(chat_id, paused=True)
            return True
        except (ConnectionNotFound, exceptions.NotInCallError):
            await db.playing(chat_id, paused=False)
            await db.remove_call(chat_id)
            queue.clear(chat_id)
            logger.warning(
                f"Pause requested but assistant not in call for {chat_id}, syncing state")
            return False
        except Exception as e:
            await db.playing(chat_id, paused=False)
            logger.error(f"Pause failed for {chat_id}: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        try:
            await client.resume(chat_id)
            await db.playing(chat_id, paused=False)
            return True
        except (ConnectionNotFound, exceptions.NotInCallError):
            await db.playing(chat_id, paused=False)
            await db.remove_call(chat_id)
            queue.clear(chat_id)
            logger.warning(
                f"Resume requested but assistant not in call for {chat_id}, syncing state")
            return False
        except Exception as e:
            logger.error(f"Resume failed for {chat_id}: {e}")
            return False

    async def stop(self, chat_id: int) -> None:
        client = await db.get_assistant(chat_id)

        # Cancel any active preload tasks when stopping
        try:
            await preload.cancel_preload(chat_id)
        except Exception as e:
            logger.debug(f"Error cancelling preload for {chat_id}: {e}")

        try:
            queue.clear(chat_id)
            await db.remove_call(chat_id)
        except Exception as e:
            logger.warning(f"Error clearing queue/call for {chat_id}: {e}")

        try:
            await client.leave_call(chat_id, close=False)
            # Small delay to let group call state stabilize after leaving
            await asyncio.sleep(0.5)
        except (ConnectionNotFound, exceptions.NotInCallError):
            # Expected: userbot is not in a call
            pass
        except Exception as e:
            # Only log unexpected errors
            error_msg = str(e).lower()
            if not any(ignore in error_msg for ignore in [
                "not in a call",
                "not in the group call",
                "groupcall_forbidden",
                "no active group call",
                "call was already stopped",
                "call already disconnected"
            ]):
                logger.warning(f"Error leaving call for {chat_id}: {e}")

    async def play_media(
        self,
        chat_id: int,
        message: Message | None,
        media: Media | Track,
        seek_time: int = 0,
        message_chat_id: int = None,
        reuse_message: bool = False,
    ) -> None:
        """Play media in voice chat.

        Args:
            chat_id: Where to stream audio (could be channel in channel play mode)
            message: Message to edit/delete (if any)
            media: Media object to play
            seek_time: Position to seek to (seconds)
            message_chat_id: Where to send control messages (group chat in channel play mode)
                           If None, messages go to same chat as audio (chat_id)
        """
        client = await db.get_assistant(chat_id)
        _lang = await lang.get_lang(chat_id)

        # Determine where messages should go:
        # - If message_chat_id provided (channel play): send to group
        # - Otherwise: send to same chat as audio
        target_chat_for_messages = message_chat_id if message_chat_id else chat_id

        # IMPORTANT: Do not generate the custom thumbnail here.
        # Thumbnail generation performs network + PIL work and used to block
        # voice-chat startup. Playback must start first.
        _thumb = config.DEFAULT_THUMB

        if not media.file_path:
            if message:
                return await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            else:
                logger.error(f"No file path for media in {chat_id}")
                return

        # FAST PATH: normal group playback does not need an extra get_chat RPC.
        # Channels still require membership validation before starting the call.
        try:
            chat = None
            if message_chat_id is not None:
                # Keep the existing channel safety check, but don't turn ordinary
                # group playback into an extra validation round-trip.
                try:
                    chat = await app.get_chat(chat_id)
                except errors.RPCError:
                    chat = None
            if chat is not None and chat.type == enums.ChatType.CHANNEL:
                # Get the userbot (Pyrogram client) to access .me attribute
                userbot_client = await db.get_client(chat_id)
                if not userbot_client:
                    logger.error(f"No userbot client available for {chat_id}")
                    if message:
                        await message.edit_text("❌ No assistant available.")
                    return

                try:
                    assistant_member = await app.get_chat_member(chat_id, userbot_client.me.id)
                    if assistant_member.status == enums.ChatMemberStatus.BANNED:
                        logger.error(f"Assistant banned in channel {chat_id}")
                        if message:
                            await message.edit_text("❌ Assistant is banned in this channel.")
                        # Disable channel play
                        await db.set_cmode(chat_id, None)
                        return
                except errors.RPCError as e:
                    if "CHANNEL_INVALID" in str(e) or "USER_NOT_PARTICIPANT" in str(e):
                        logger.error(
                            f"Assistant not in channel {chat_id}: {e}")
                        if message:
                            await message.edit_text(
                                "❌ <b>Assistant not in channel!</b>\n\n"
                                f"<blockquote>Please add @{userbot_client.me.username} to the channel as admin with voice chat permissions.</blockquote>"
                            )
                        # Disable channel play
                        await db.set_cmode(chat_id, None)
                        return
        except errors.RPCError as e:
            if "CHANNEL_INVALID" in str(e):
                logger.error(f"Invalid channel {chat_id}: {e}")
                if message:
                    await message.edit_text("❌ Invalid channel. Disabling channel play.")
                await db.set_cmode(chat_id, None)  # Disable channel play
                return
            raise

        # Configure audio stream with optimized buffering for lag-free playback
        # PERFORMANCE FIX: Increased buffers prevent stuttering/lagging during playback
        if seek_time > 1:
            # Seeking: Still need buffers but skip to position first
            ffmpeg_params = f"-ss {seek_time} -probesize 2M -analyzeduration 1M -rtbufsize 2M -fflags +genpts+igndts"
        else:
            # Normal playback with aggressive buffering:
            # - probesize 10M: Large input buffer (prevents underruns)
            # - analyzeduration 5M: Analyze more data (better format detection)
            # - rtbufsize 5M: Real-time buffer (crucial for network streams)
            # - fflags +genpts+igndts: Generate PTS, ignore DTS (smooth playback)
            # - sync ext: External sync (reduces A/V desync)
            ffmpeg_params = "-probesize 2M -analyzeduration 1M -rtbufsize 2M -fflags +genpts+igndts -sync ext"

        is_video = getattr(media, "video", False)
        video_flags = (
            types.MediaStream.Flags.AUTO_DETECT
            if is_video
            else types.MediaStream.Flags.IGNORE
        )

        stream = types.MediaStream(
            media_path=media.file_path,
            audio_parameters=types.AudioQuality.STUDIO,
            audio_flags=types.MediaStream.Flags.REQUIRED,
            video_flags=video_flags,
            ffmpeg_parameters=ffmpeg_params,
        )

        # FAST VC JOIN:
        # Try to start/reuse the call immediately.  The previous implementation
        # always performed get_call() + leave_call() first, adding an extra RPC
        # round-trip even when the assistant was already connected.
        # If PyTgCalls reports a stale connection, only then do we disconnect
        # and retry.
        max_retries = 3
        retry_delays = (0.0, 0.20, 0.45)

        try:
            for attempt in range(max_retries):
                try:
                    await client.play(
                        chat_id=chat_id,
                        stream=stream,
                        config=types.GroupCallConfig(auto_start=True),
                    )
                    break
                except (exceptions.NoActiveGroupCall, errors.RPCError) as e:
                    error_msg = str(e)
                    if "GROUPCALL_INVALID" in error_msg or "GROUPCALL" in error_msg or isinstance(e, exceptions.NoActiveGroupCall):
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delays[attempt + 1])
                            continue
                        raise
                    raise
                except Exception as e:
                    error_msg = str(e).lower()
                    if "cannot be initialized more than once" in error_msg or "connection" in error_msg:
                        if attempt < max_retries - 1:
                            try:
                                await client.leave_call(chat_id, close=False)
                            except Exception:
                                pass
                            await asyncio.sleep(retry_delays[attempt + 1])
                            continue
                    raise

            # Playback is already started at this point. Generate the custom
            # thumbnail only now, so image processing/network latency cannot
            # delay joining the VC or starting audio.
            if config.THUMB_GEN and isinstance(media, Track):
                try:
                    _thumb = await thumb.generate(media)
                except Exception as e:
                    logger.debug(f"Thumbnail generation skipped for {chat_id}: {e}")
                    _thumb = config.DEFAULT_THUMB

            if seek_time:
                media.time = seek_time
            else:
                media.time = 1
            media._clock_last = asyncio.get_running_loop().time()

            if not seek_time:
                await db.add_call(chat_id)
                text = _lang["play_media"].format(
                    media.url,
                    media.title,
                    media.duration,
                    media.user,
                )
                if not media.is_live and media.duration_sec:
                    import time as time_module
                    played = media.time
                    duration = media.duration_sec
                    bar_length = 12
                    if duration == 0:
                        percentage = 0
                    else:
                        percentage = min((played / duration) * 100, 100)
                    filled = int(round(bar_length * percentage / 100))
                    timer_bar = "—" * filled + "●" + \
                        "—" * (bar_length - filled)
                    if duration >= 3600:
                        played_time = time_module.strftime(
                            '%H:%M:%S', time_module.gmtime(played))
                        total_time = time_module.strftime(
                            '%H:%M:%S', time_module.gmtime(duration))
                    else:
                        played_time = time_module.strftime(
                            '%M:%S', time_module.gmtime(played))
                        total_time = time_module.strftime(
                            '%M:%S', time_module.gmtime(duration))
                    timer_text = f"{played_time} {timer_bar} {total_time}"
                    keyboard = buttons.controls(chat_id, timer=timer_text)
                else:
                    keyboard = buttons.controls(chat_id)

                # Rich player: controls live inside the same Rich Message.
                # When reuse_message=True (skip/replay), update that message in-place
                # so the player card and thumbnail never disappear or get replaced.
                if reuse_message and message is not None and int(getattr(message, "id", 0) or 0):
                    media.message_id = int(message.id)
                    try:
                        ok = await edit_player(
                            target_chat_for_messages, media.message_id, text, media,
                            playing=True, photo=_thumb, autoplay=self.autoplay_enabled(chat_id),
                        )
                    except Exception as rich_error:
                        ok = False
                        logger.warning(f"In-place Rich player update failed: {rich_error}")
                    if ok:
                        try:
                            message.chat.id
                        except Exception:
                            pass
                    else:
                        # Last resort: create a fresh player only if in-place edit fails.
                        try:
                            media.message_id = await send_player(
                                target_chat_for_messages, text, _thumb, media, playing=True, autoplay=self.autoplay_enabled(chat_id)
                            )
                        except Exception as rich_error:
                            logger.warning(f"Rich player send failed: {rich_error}")
                else:
                    if message:
                        try:
                            await message.delete()
                        except Exception:
                            pass
                    try:
                        media.message_id = await send_player(
                            target_chat_for_messages, text, _thumb, media, playing=True, autoplay=self.autoplay_enabled(chat_id)
                        )
                    except Exception as rich_error:
                        logger.warning(f"Rich player failed: {rich_error}")
                        sent_photo = await self._send_photo_with_retry(
                            chat_id=target_chat_for_messages,
                            photo=_thumb,
                            caption=text,
                            reply_markup=keyboard,
                        )
                        if sent_photo:
                            media.message_id = sent_photo.id

                try:
                    asyncio.create_task(
                        preload.start_preload(chat_id, count=2))
                except Exception as e:
                    logger.debug(f"Error starting preload for {chat_id}: {e}")
        except FileNotFoundError:
            if message:
                try:
                    await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
                except Exception:
                    pass
            await self.play_next(chat_id)
        except exceptions.NoActiveGroupCall:
            await self.stop(chat_id)
            if message:
                try:
                    await message.edit_text(_lang["error_vc_disabled"])
                except Exception:
                    pass
        except errors.RPCError as e:
            error_str = str(e)

            if any(x in error_str for x in ["CHAT_ADMIN_REQUIRED", "phone.CreateGroupCall", "GROUPCALL_FORBIDDEN", "GROUPCALL_CREATE_FORBIDDEN", "VOICE_MESSAGES_FORBIDDEN"]):
                await self.stop(chat_id)
                if message:
                    try:
                        await message.edit_text(_lang["error_vc_disabled"])
                    except Exception:
                        pass
            elif "GROUPCALL_INVALID" in error_str or "GROUPCALL" in error_str:
                await self.stop(chat_id)
                if message:
                    try:
                        await message.edit_text(_lang["error_no_call"])
                    except Exception:
                        pass
            else:
                logger.error(f"RPC error in play_media for {chat_id}: {e}")
                await self.stop(chat_id)
        except exceptions.NoAudioSourceFound:
            if message:
                try:
                    await message.edit_text(_lang["error_no_audio"])
                except Exception:
                    pass
            await self.play_next(chat_id)
        except (ConnectionNotFound, TelegramServerError):
            await self.stop(chat_id)
            if message:
                try:
                    await message.edit_text(_lang["error_tg_server"])
                except Exception:
                    pass
        except TimeoutError as e:
            error_msg = str(e)
            logger.warning(
                f"⏱️ Timeout joining voice chat {chat_id}: {error_msg}")
            await self.stop(chat_id)
            if message:
                try:
                    await message.edit_text(
                        "⏱️ <b>Connection timed out!</b>\n\n"
                        "<blockquote>Failed to join voice chat. Please check your network and try again.</blockquote>"
                    )
                except Exception:
                    pass
            await asyncio.sleep(2)
            await self.play_next(chat_id)
        except Exception as e:
            logger.error(
                f"Unexpected error in play_media for {chat_id}: {e}", exc_info=True)
            await self.stop(chat_id)
            if message:
                try:
                    await message.edit_text(f"❌ Playback error: {str(e)[:100]}")
                except Exception:
                    pass

    async def replay(self, chat_id: int, control_message=None) -> None:
        try:
            if not await db.get_call(chat_id):
                return

            message_chat_id = None
            try:
                chat = await app.get_chat(chat_id)
                if chat.type == enums.ChatType.CHANNEL:
                    group_id = await db.get_group_for_channel(chat_id)
                    if group_id:
                        message_chat_id = group_id
            except Exception:
                pass

            media = queue.get_current(chat_id)
            _lang = await lang.get_lang(chat_id)
            target_chat = message_chat_id if message_chat_id else chat_id
            msg = control_message or await app.send_message(chat_id=target_chat, text=_lang["play_again"])
            await self.play_media(chat_id, msg, media, message_chat_id=message_chat_id, reuse_message=bool(control_message))
        except Exception as e:
            logger.error(f"Error in replay for {chat_id}: {e}", exc_info=True)

    async def seek_stream(self, chat_id: int, seconds: int) -> bool:
        """Seek to a specific position in the current stream."""
        try:
            if not await db.get_call(chat_id):
                return False

            media = queue.get_current(chat_id)
            if not media or media.is_live:
                return False

            client = await db.get_assistant(chat_id)
            _lang = await lang.get_lang(chat_id)

            message_chat_id = None
            try:
                chat = await app.get_chat(chat_id)
                if chat.type == enums.ChatType.CHANNEL:
                    group_id = await db.get_group_for_channel(chat_id)
                    if group_id:
                        message_chat_id = group_id
            except Exception:
                pass

            media.time = seconds

            target_chat = message_chat_id if message_chat_id else chat_id

            try:
                msg = await app.get_messages(target_chat, media.message_id)
            except Exception:
                msg = None

            if not msg:
                _lang = await lang.get_lang(chat_id)
                msg = await app.send_message(chat_id=target_chat, text=_lang["seeking"])

            await self.play_media(chat_id, msg, media, seek_time=seconds, message_chat_id=message_chat_id)
            return True
        except Exception as e:
            logger.warning(f"Seek stream failed for {chat_id}: {e}")
            return False

    async def play_next(self, chat_id: int, control_message=None, force_new_message: bool = False) -> None:
        if chat_id not in self._play_next_locks:
            self._play_next_locks[chat_id] = asyncio.Lock()

        lock = self._play_next_locks[chat_id]

        if lock.locked():
            logger.info(
                f"play_next already running for {chat_id}, skipping duplicate call")
            return

        async with lock:
            try:
                if not await db.get_call(chat_id):
                    return

                message_chat_id = None
                try:
                    chat = await app.get_chat(chat_id)
                    if chat.type == enums.ChatType.CHANNEL:
                        group_id = await db.get_group_for_channel(chat_id)
                        if group_id:
                            message_chat_id = group_id
                except Exception:
                    pass

                target_chat = message_chat_id if message_chat_id else chat_id

                loop_mode = await db.get_loop(chat_id)

                if loop_mode == 1:
                    media = queue.get_current(chat_id)
                    if media:
                        _lang = await lang.get_lang(chat_id)
                        try:
                            if force_new_message:
                                old_id = getattr(media, "message_id", None)
                                if old_id:
                                    try:
                                        await app.delete_messages(chat_id=target_chat, message_ids=[int(old_id)], revoke=True)
                                    except Exception:
                                        pass
                                msg = await app.send_message(chat_id=target_chat, text=_lang["play_again"])
                            else:
                                msg = control_message or await app.send_message(chat_id=target_chat, text=_lang["play_again"])
                            await self.play_media(chat_id, msg, media, message_chat_id=message_chat_id, reuse_message=bool(control_message and not force_new_message))
                        except errors.ChannelPrivate:
                            logger.warning(
                                f"Bot removed from {chat_id}, cleaning up")
                            try:
                                await self.leave_call(chat_id)
                            except (AttributeError, Exception) as leave_ex:
                                logger.debug(
                                    f"Could not leave call for {chat_id}: {leave_ex}")
                            await db.rm_chat(chat_id)
                        return

                current = queue.get_current(chat_id)
                old_current_message_id = getattr(current, "message_id", None) if current else None
                media = queue.get_next(chat_id)

                if not media:
                    # Autoplay: when the queue is empty, search for a related
                    # track based on the song that just finished and continue
                    # playback automatically.
                    if self._autoplay.get(chat_id) and current and not getattr(current, "is_live", False):
                        base_title = getattr(current, "ytitle", None) or getattr(current, "title", None) or ""
                        if base_title:
                            queries = [
                                f"{base_title} official audio",
                                f"{base_title} song",
                                base_title,
                            ]
                            next_track = None
                            for related_query in queries:
                                try:
                                    candidate = await yt.search(related_query, 0)
                                except Exception as search_ex:
                                    logger.warning(f"[AUTOPLAY] Search failed for {chat_id}: {search_ex}")
                                    candidate = None
                                if candidate and getattr(candidate, "id", None) != getattr(current, "id", None):
                                    next_track = candidate
                                    break
                            if next_track:
                                next_track.user = "Autoplay"
                                queue.add(chat_id, next_track)
                                logger.info(
                                    f"🎵 [AUTOPLAY] Continuing playback in {chat_id}: "
                                    f"{getattr(next_track, 'ytitle', next_track.title)}"
                                )
                                # queue.get_next() removes the finished track;
                                # the newly added track is now the current item.
                                return await self.play_next(chat_id)
                            logger.warning(f"🎵 [AUTOPLAY] Could not find a different track for {chat_id}")

                    if config.AUTO_END:
                        _lang = await lang.get_lang(chat_id)
                        try:
                            await app.send_message(
                                chat_id=chat_id,
                                text=_lang.get(
                                    "auto_end", "✅ Queue finished. Stream ended automatically.")
                            )
                        except Exception as e:
                            logger.debug(
                                f"Could not send auto_end message in {chat_id}: {e}")
                    return await self.stop(chat_id)

                _lang = await lang.get_lang(chat_id)

                # On a manual skip, remove both the old player message and the
                # queued-song status message for the track that is becoming
                # current (for example: "ADDED TO QUEUE: 1"). Then create a
                # completely new player message instead of reusing the old one.
                if force_new_message:
                    ids_to_delete = []
                    for mid in (old_current_message_id, getattr(media, "message_id", None)):
                        try:
                            mid = int(mid)
                        except (TypeError, ValueError):
                            continue
                        if mid and mid not in ids_to_delete:
                            ids_to_delete.append(mid)
                    if ids_to_delete:
                        try:
                            await app.delete_messages(
                                chat_id=target_chat,
                                message_ids=ids_to_delete,
                                revoke=True,
                            )
                        except Exception as e:
                            logger.debug(f"Could not delete old queue/player messages for {chat_id}: {e}")

                msg = None
                if not media.file_path:
                    is_live = getattr(media, 'is_live', False)
                    media.file_path = await yt.download(
                        media.id,
                        is_live=is_live,
                        video=getattr(media, 'video', False),
                    )
                    if not media.file_path:
                        await self.stop(chat_id)
                        if msg:
                            try:
                                await msg.edit_text(
                                    _lang["error_no_file"].format(
                                        config.SUPPORT_CHAT)
                                )
                            except Exception:
                                pass
                        return

                try:
                    if force_new_message:
                        msg = await app.send_message(chat_id=target_chat, text=_lang["play_next"])
                    else:
                        msg = control_message or await app.send_message(chat_id=target_chat, text=_lang["play_next"])
                except errors.FloodWait as fw:
                    # Do not block playback on UI flood waits; continue without message.
                    logger.warning(
                        f"FloodWait in play_next for {chat_id}: skipping status message ({fw.value}s)")
                    msg = None
                except errors.ChannelPrivate:
                    logger.warning(f"Bot removed from {chat_id}, cleaning up")
                    await self.leave_call(chat_id)
                    await db.rm_chat(chat_id)
                    return
                except Exception as e:
                    logger.error(
                        f"Failed to send play_next message for {chat_id}: {e}")
                    msg = None

                media.message_id = (msg.id if msg else 0) if (force_new_message or not control_message) else int(control_message.id)
                if msg:
                    await self.play_media(
                        chat_id,
                        msg,
                        media,
                        message_chat_id=message_chat_id,
                        reuse_message=bool(control_message and not force_new_message),
                    )
                else:
                    logger.info(
                        f"Playing next track for {chat_id} without message update")
                    await self.play_media(chat_id, None, media, message_chat_id=message_chat_id)

                try:
                    asyncio.create_task(
                        preload.start_preload(chat_id, count=2))
                except Exception as e:
                    logger.debug(
                        f"Error starting preload after play_next for {chat_id}: {e}")
            except Exception as e:
                logger.error(
                    f"Error in play_next for {chat_id}: {e}", exc_info=True)
                try:
                    await self.stop(chat_id)
                except Exception:
                    pass

    async def set_autoplay(self, chat_id: int, enabled: bool | None = None) -> bool:
        """Enable/disable autoplay for a chat and return the new state."""
        if enabled is None:
            enabled = not self._autoplay.get(chat_id, False)
        self._autoplay[chat_id] = bool(enabled)
        return bool(enabled)

    def autoplay_enabled(self, chat_id: int) -> bool:
        return bool(self._autoplay.get(chat_id, False))

    async def set_autoplay(self, chat_id: int, enabled: bool | None = None) -> bool:
        """Enable/disable autoplay for a chat and return the new state."""
        if enabled is None:
            enabled = not self._autoplay.get(chat_id, False)
        self._autoplay[chat_id] = bool(enabled)
        return bool(enabled)

    def autoplay_enabled(self, chat_id: int) -> bool:
        return bool(self._autoplay.get(chat_id, False))

    async def ping(self) -> float:
        pings = [client.ping for client in self.clients]
        return round(sum(pings) / len(pings), 2)

    async def decorators(self, client: PyTgCalls) -> None:
        for client in self.clients:
            @client.on_update()
            async def update_handler(_, update: types.Update) -> None:
                if isinstance(update, types.StreamEnded):
                    if update.stream_type == types.StreamEnded.Type.AUDIO:
                        chat_id = update.chat_id
                        current_time = asyncio.get_event_loop().time()

                        if chat_id in self._stream_end_cache:
                            if current_time - self._stream_end_cache[chat_id] < 2.0:
                                return

                        self._stream_end_cache[chat_id] = current_time

                        self._stream_end_cache = {
                            cid: t for cid, t in self._stream_end_cache.items()
                            if current_time - t < 5.0
                        }

                        await self.play_next(chat_id)
                elif isinstance(update, types.ChatUpdate):
                    if update.status in [
                        types.ChatUpdate.Status.KICKED,
                        types.ChatUpdate.Status.LEFT_GROUP,
                        types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
                    ]:
                        await self.stop(update.chat_id)

    async def boot(self) -> None:
        PyTgCallsSession.notice_displayed = True
        for ub in userbot.clients:
            client = PyTgCalls(ub, cache_duration=100)
            await client.start()
            self.clients.append(client)
            await self.decorators(client)
        logger.info("📞 PyTgCalls client(s) started.")
