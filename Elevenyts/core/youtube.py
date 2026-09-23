# ==========================================================
# Copyright (c) 2026 VelocityBots
# All Rights Reserved.
#
# Project      : VelocityBots ꭙ Music Telegram Bot
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

import os
import re
import time
import random
import asyncio
import aiohttp
from dataclasses import replace
from typing import Optional, Union

from pyrogram import enums, types
from py_yt import Playlist, VideosSearch
from Elevenyts import config, logger
from Elevenyts.helpers import Track, utils


class YouTube:
    def __init__(self):
        """Initialize YouTube handler with configuration and caching."""
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.warned = False

        # Get API configuration from config
        self.api_url = config.ARTISTBOTS_API_URL
        self.artistbots_key = config.ARTISTBOTS_KEY
        self.enable_api = config.ENABLE_API
        self.enable_cookies_fallback = config.ENABLE_COOKIES_FALLBACK
        self.api_timeout = config.API_TIMEOUT
        self.api_stream_timeout = config.API_STREAM_TIMEOUT

        # Regular expression to match YouTube URLs
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|live/|embed/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )

        # Cache search results (10 minute TTL)
        self.search_cache = {}
        self._download_semaphore = asyncio.Semaphore(5)
        self._max_video_height = config.VIDEO_MAX_HEIGHT

        # Log configuration
        logger.info("=" * 50)
        logger.info("📹 YouTube Handler Initialized")
        logger.info(f"🎵 API Priority: {'ENABLED' if self.enable_api else 'DISABLED'}")
        if self.enable_api:
            logger.info(f"🔗 API URL: {self.api_url}")
            if self.artistbots_key:
                masked_key = self.artistbots_key[:8] + "..." if len(self.artistbots_key) > 8 else "***"
                logger.info(f"🔑 API Key: {masked_key}")
            else:
                logger.warning("⚠️ No API Key configured!")
        logger.info(f"🍪 Cookies Fallback: {'ENABLED' if self.enable_cookies_fallback else 'DISABLED'}")
        logger.info("=" * 50)

    async def download_via_api(self, link: str, video: bool = False) -> Optional[str]:
        """Download media directly from the ArtistBots streaming API.

        The API performs yt-dlp extraction server-side and returns the finished
        media file in the same HTTP response, avoiding the slower JSON metadata
        + /files second-request flow.
        """
        if not self.enable_api:
            logger.debug("API is disabled in config")
            return None
        if not self.api_url:
            logger.debug("ARTISTBOTS_API_URL not configured")
            return None

        if "v=" in link:
            video_id = link.split("v=")[-1].split("&")[0]
        elif "youtu.be" in link:
            video_id = link.split("/")[-1].split("?")[0]
        else:
            video_id = link

        if not video_id or len(video_id) < 3:
            logger.debug(f"Invalid video ID: {video_id}")
            return None

        download_dir = "downloads"
        os.makedirs(download_dir, exist_ok=True)
        file_ext = ".mp4" if video else ".mp3"
        file_path = os.path.join(download_dir, f"{video_id}{file_ext}")
        part_path = file_path + ".part"

        if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
            logger.debug(f"File already exists: {file_path}")
            return file_path
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass

        try:
            download_type = "video" if video else "audio"
            api_started = time.monotonic()
            logger.info(f"🚀 [API DIRECT] Downloading {download_type} for {video_id}")
            endpoint = "/download"
            api_endpoint = f"{self.api_url.rstrip('/')}{endpoint}"
            headers = {
                "Accept": "audio/mpeg,video/mp4,application/octet-stream,*/*",
            }

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.api_stream_timeout)
            ) as session:
                async with session.get(
                    api_endpoint,
                    params={
                        "url": video_id,
                        "type": "video" if video else "audio",
                        "api_key": self.artistbots_key,
                    },
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.api_stream_timeout),
                ) as response:
                    headers_received = time.monotonic()
                    header_wait = headers_received - api_started
                    logger.info(f"⏱️ [API TIMING] Response headers received for {video_id} after {header_wait:.2f}s (HTTP {response.status})")
                    if response.status != 200:
                        try:
                            error_text = await response.text()
                            logger.error(f"API returned status {response.status}: {error_text[:250]}")
                        except Exception:
                            logger.error(f"API returned status {response.status}")
                        return None

                    content_type = (response.headers.get("Content-Type") or "").lower()
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        logger.info(f"📦 API file size: {int(content_length) / 1048576:.2f} MB")
                    if "json" in content_type or "html" in content_type:
                        logger.error(f"API returned unexpected content type: {content_type}")
                        return None

                    downloaded = 0
                    last_log = 0
                    first_byte_at = None
                    transfer_started = None
                    with open(part_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            if not chunk:
                                continue
                            if first_byte_at is None:
                                first_byte_at = time.monotonic()
                                transfer_started = first_byte_at
                                logger.info(f"⚡ [API TIMING] First audio bytes received for {video_id} after {first_byte_at - api_started:.2f}s (API preparation/TTFB: {first_byte_at - api_started:.2f}s)")
                            f.write(chunk)
                            downloaded += len(chunk)
                            if downloaded - last_log >= 10 * 1024 * 1024:
                                elapsed = max(time.monotonic() - transfer_started, 0.001)
                                speed = (downloaded / 1048576) / elapsed
                                logger.info(f"📊 API progress: {downloaded / 1048576:.1f} MB ({speed:.2f} MB/s)")
                                last_log = downloaded

                    api_finished = time.monotonic()
                    transfer_elapsed = (api_finished - transfer_started) if transfer_started else 0.0
                    transfer_speed = (downloaded / 1048576) / max(transfer_elapsed, 0.001) if downloaded else 0.0
                    logger.info(f"🏁 [API TIMING] Transfer finished for {video_id}: {downloaded / 1048576:.2f} MB in {transfer_elapsed:.2f}s ({transfer_speed:.2f} MB/s)")
                    logger.info(f"⏱️ [API TIMING] API total: {api_finished - api_started:.2f}s (headers {header_wait:.2f}s + transfer {transfer_elapsed:.2f}s)")

            if downloaded <= 1024 or not os.path.exists(part_path):
                logger.error("❌ API direct download returned an empty/invalid file")
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                return None

            os.replace(part_path, file_path)
            file_size_mb = os.path.getsize(file_path) / 1048576
            logger.info(f"✅ [API DIRECT SUCCESS] Downloaded: {file_path} ({file_size_mb:.2f} MB)")
            return file_path

        except asyncio.TimeoutError:
            logger.error(f"⏰ Direct API timeout for {video_id} after {self.api_stream_timeout} seconds")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"🌐 Direct API client error for {video_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Direct API download failed for {video_id}: {type(e).__name__}: {e}")
            return None
        finally:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass

    def valid(self, url: str) -> bool:
        """Check if URL is a valid YouTube URL."""
        return bool(re.match(self.regex, url))

    def url(self, message_1: types.Message) -> Union[str, None]:
        """Extract YouTube URL from message."""
        messages = [message_1]
        link = None
        
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            text = message.text or message.caption or ""

            if message.entities:
                for entity in message.entities:
                    if entity.type == enums.MessageEntityType.URL:
                        link = text[entity.offset: entity.offset + entity.length]
                        break

            if message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == enums.MessageEntityType.TEXT_LINK:
                        link = entity.url
                        break

        if link:
            # Remove tracking parameters
            return link.split("&si")[0].split("?si")[0]
        return None


    async def search(self, query: str, m_id: int) -> Track | None:
        """Search for a song on YouTube."""
        cache_key = query
        current_time = asyncio.get_running_loop().time()

        # Check cache
        if cache_key in self.search_cache:
            cached_result, cache_timestamp = self.search_cache[cache_key]
            if current_time - cache_timestamp < 600:  # 10 minutes TTL
                fresh = replace(cached_result)
                fresh.message_id = m_id
                fresh.file_path = None
                fresh.user = None
                fresh.time = 0
                fresh.video = False
                return fresh

        try:
            _search = VideosSearch(query, limit=1)
            results = await _search.next()
        except Exception as e:
            logger.warning(f"⚠️ YouTube search failed for '{query}': {e}")
            return None

        if results and results["result"]:
            data = results["result"][0]
            duration = data.get("duration")
            is_live = duration is None or duration == "LIVE"

            track = Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name"),
                duration=duration if not is_live else "LIVE",
                duration_sec=0 if is_live else utils.to_seconds(duration),
                message_id=m_id,
                title=data.get("title")[:25],
                ytitle=data.get("title"),
                thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                url=data.get("link"),
                view_count=data.get("viewCount", {}).get("short"),
                is_live=is_live,
            )

            # Cache result
            self.search_cache[cache_key] = (track, current_time)
            
            # Clean old cache entries
            if len(self.search_cache) > 100:
                oldest_key = min(self.search_cache.keys(),
                                 key=lambda k: self.search_cache[k][1])
                del self.search_cache[oldest_key]

            return replace(track)
        return None

    async def search_many(self, query: str, m_id: int, limit: int = 8) -> list[Track]:
        """Search YouTube and return several distinct tracks for autoplay/selection."""
        try:
            _search = VideosSearch(query, limit=max(1, min(limit, 20)))
            results = await _search.next()
        except Exception as e:
            logger.warning(f"⚠️ YouTube multi-search failed for '{query}': {e}")
            return []

        tracks = []
        for data in (results or {}).get("result", []):
            try:
                duration = data.get("duration")
                is_live = duration is None or duration == "LIVE"
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name"),
                    duration=duration if not is_live else "LIVE",
                    duration_sec=0 if is_live else utils.to_seconds(duration),
                    message_id=m_id,
                    title=(data.get("title") or "Unknown")[:25],
                    ytitle=data.get("title") or "Unknown",
                    thumbnail=(data.get("thumbnails") or [{}])[-1].get("url", "").split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                    is_live=is_live,
                )
                if track.id:
                    tracks.append(track)
            except Exception as e:
                logger.debug(f"Could not parse autoplay result: {e}")
        return tracks

    async def playlist(self, limit: int, user: str, url: str) -> list[Track]:
        """Extract tracks from a YouTube playlist."""
        try:
            plist = await Playlist.get(url)
            tracks = []

            if not plist or "videos" not in plist or not plist["videos"]:
                return []

            for data in plist["videos"][:limit]:
                try:
                    thumbnails = data.get("thumbnails", [])
                    thumbnail_url = ""
                    if thumbnails and len(thumbnails) > 0:
                        thumbnail_url = thumbnails[-1].get("url", "").split("?")[0]

                    link = data.get("link", "")
                    if "&list=" in link:
                        link = link.split("&list=")[0]

                    track = Track(
                        id=data.get("id", ""),
                        channel_name=data.get("channel", {}).get("name", ""),
                        duration=data.get("duration", "0:00"),
                        duration_sec=utils.to_seconds(data.get("duration", "0:00")),
                        title=(data.get("title", "Unknown")[:25]),
                        ytitle=data.get("title", "Unknown"),
                        thumbnail=thumbnail_url,
                        url=link,
                        user=user,
                        view_count="",
                    )
                    tracks.append(track)
                except Exception as e:
                    logger.warning(f"Failed to parse playlist item: {e}")
                    continue

            return tracks
        except KeyError as e:
            raise Exception(f"Failed to parse playlist. YouTube may have changed their structure.")
        except Exception as e:
            logger.error(f"Playlist extraction error: {e}")
            raise

    async def download(self, video_id: str, is_live: bool = False, video: bool = False) -> Optional[str]:
        """Download media exclusively through the remote ArtistBots/MAGMA API.

        The Telegram bot never contacts YouTube directly. YouTube extraction,
        cookies, anti-bot handling, and media conversion are handled by the API.
        """
        if not video_id:
            return None

        # API is the only normal download path.
        if not self.enable_api or not self.api_url or not self.artistbots_key:
            logger.error("❌ API download is not configured (URL/key missing or API disabled)")
            return None

        if is_live:
            logger.info(f"🔴 Live stream requested for {video_id}; using API stream endpoint")

        logger.info(f"🎯 [API ONLY] Downloading {video_id} via API")
        result = await self.download_via_api(self.base + video_id, video=video)
        if result:
            logger.info(f"✅ [API SUCCESS] Downloaded via API: {video_id}")
            return result

        logger.error(f"❌ [API FAILED] Could not download {video_id}")
        return None
