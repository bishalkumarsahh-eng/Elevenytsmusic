import asyncio
import glob
import os
import random
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional, Union

import aiohttp
import yt_dlp
from py_yt import Playlist, VideosSearch
from pyrogram import enums, types

from Elevenyts import config, logger
from Elevenyts.helpers import Track, utils


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.warned = False

        self.api_url = config.ARTISTBOTS_API_URL
        self.artistbots_key = config.ARTISTBOTS_KEY
        self.enable_api = config.ENABLE_API
        self.enable_cookies_fallback = config.ENABLE_COOKIES_FALLBACK
        self.api_timeout = config.API_TIMEOUT
        self.api_stream_timeout = config.API_STREAM_TIMEOUT

        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|live/|embed/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )

        self.search_cache = {}
        self._download_semaphore = asyncio.Semaphore(5)
        self._max_video_height = config.VIDEO_MAX_HEIGHT

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

    def _locate_download_file(self, video_id: str, video: bool = False) -> Optional[str]:
        pattern = f"downloads/{video_id}*"
        candidates = sorted(
            [path for path in glob.glob(pattern) if not path.endswith((".part", ".ytdl", ".info.json", ".temp"))]
        )

        video_exts = {".mp4", ".mkv", ".webm", ".mov"}
        audio_exts = {".m4a", ".webm", ".opus", ".mp3", ".ogg", ".wav", ".flac"}

        if video:
            for path in candidates:
                if os.path.isdir(path):
                    continue
                if Path(path).suffix.lower() in video_exts:
                    return path
        else:
            for path in candidates:
                if os.path.isdir(path):
                    continue
                if Path(path).suffix.lower() in audio_exts:
                    return path

        for path in candidates:
            if os.path.isdir(path):
                continue
            return path
        return None

    def _resolve_timeout(self, requested_timeout: int, min_timeout: int = 10, max_timeout: int = 45) -> int:
        if requested_timeout is None:
            return max_timeout
        try:
            requested_timeout = int(requested_timeout)
        except (TypeError, ValueError):
            return max_timeout
        if requested_timeout <= 0:
            return min_timeout
        return max(min_timeout, min(requested_timeout, max_timeout))

    def get_cookies(self):
        if not self.checked:
            cookies_dir = "Elevenyts/cookies"
            if os.path.exists(cookies_dir):
                for file in os.listdir(cookies_dir):
                    if file.endswith(".txt"):
                        self.cookies.append(file)
            self.checked = True

        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("🍪 Cookies are missing; downloads might fail.")
            return None

        cookie_file = f"Elevenyts/cookies/{random.choice(self.cookies)}"
        logger.debug(f"Using cookie file: {cookie_file}")
        return cookie_file

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("🍪 Saving cookies from urls...")
        saved_count = 0
        cookies_dir = Path("Elevenyts/cookies")
        cookies_dir.mkdir(parents=True, exist_ok=True)

        for url in urls:
            try:
                path = cookies_dir / f"cookie{random.randint(10000, 99999)}.txt"
                if "pastebin.com" in url:
                    link = url.replace("pastebin.com", "pastebin.com/raw")
                elif "batbin.me" in url:
                    link = url.replace("batbin.me", "batbin.me/raw")
                else:
                    link = url

                async with aiohttp.ClientSession() as session:
                    async with session.get(link, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status != 200:
                            logger.error(f"❌ Cookie download failed: HTTP {resp.status} from {url}")
                            continue
                        content = await resp.read()
                        if not content or len(content) < 50:
                            logger.error(f"❌ Cookie file empty or invalid from {url}")
                            continue
                        with open(path, "wb") as fw:
                            fw.write(content)
                        if path.exists() and path.stat().st_size > 0:
                            saved_count += 1
                            cookie_filename = path.name
                            if cookie_filename not in self.cookies:
                                self.cookies.append(cookie_filename)
                            logger.info(f"✅ Saved: {cookie_filename} ({len(content)} bytes)")
            except asyncio.TimeoutError:
                logger.error(f"❌ Cookie download timeout from {url}")
            except Exception as e:
                logger.error(f"❌ Cookie download error from {url}: {e}")

        self.checked = True
        if saved_count > 0:
            logger.info(f"✅ Cookies saved successfully! ({saved_count} file(s))")
        else:
            logger.error("❌ No cookies saved! Check COOKIE_URL in .env.")

    async def download_via_api(self, link: str, video: bool = False) -> Optional[str]:
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

        download_dir = Path("downloads")
        download_dir.mkdir(parents=True, exist_ok=True)

        file_ext = ".mp4" if video else ".mp3"
        file_path = download_dir / f"{video_id}{file_ext}"
        if file_path.exists():
            logger.debug(f"File already exists: {file_path}")
            return str(file_path)

        try:
            download_type = "video" if video else "audio"
            logger.info(f"🚀 [API PRIMARY] Trying ArtistBots API for {video_id} (type: {download_type})")
            params = {"url": video_id, "type": download_type}
            if self.artistbots_key:
                params["api_key"] = self.artistbots_key
            else:
                logger.warning("No ArtistBots API key configured!")
                return None

            timeout_seconds = self._resolve_timeout(self.api_stream_timeout, 10, 30)
            async with aiohttp.ClientSession() as session:
                api_endpoint = f"{self.api_url.rstrip('/')}/download"
                async with session.get(
                    api_endpoint,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"API returned status {response.status}: {error_text[:200]}")
                        return None
                    with open(file_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(65536):
                            f.write(chunk)
                    if file_path.exists() and file_path.stat().st_size > 0:
                        logger.info(f"✅ [API SUCCESS] Downloaded: {file_path}")
                        return str(file_path)
                    logger.error("API download failed: file is empty or not created")
                    if file_path.exists():
                        file_path.unlink()
                    return None
        except asyncio.TimeoutError:
            logger.error(f"⏰ API timeout for {video_id} after {timeout_seconds} seconds")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"🌐 API client error for {video_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ API download failed for {video_id}: {type(e).__name__}: {e}")
            return None

    async def download_via_cookies(self, video_id: str, video: bool = False) -> Optional[str]:
        if not self.enable_cookies_fallback:
            logger.debug("Cookies fallback is disabled in config")
            return None

        url = self.base + video_id
        filename_pattern = f"downloads/{video_id}"
        existing_files = [f for f in glob.glob(f"{filename_pattern}.*") if not f.endswith(".part")]
        if video:
            video_candidates = [f for f in existing_files if Path(f).suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
            if video_candidates:
                return video_candidates[0]
        else:
            audio_candidates = [f for f in existing_files if Path(f).suffix.lower() in {".m4a", ".webm", ".opus", ".mp3", ".ogg", ".wav", ".flac"}]
            if audio_candidates:
                return audio_candidates[0]
            container_fallbacks = [f for f in existing_files if Path(f).suffix.lower() in {".mp4", ".mkv", ".mov"}]
            if container_fallbacks:
                return container_fallbacks[0]

        Path("downloads").mkdir(parents=True, exist_ok=True)

        async with self._download_semaphore:
            cookie = self.get_cookies()
            base_opts = {
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "quiet": True,
                "noplaylist": True,
                "geo_bypass": True,
                "no_warnings": True,
                "overwrites": False,
                "nocheckcertificate": True,
                "continuedl": True,
                "noprogress": True,
                "concurrent_fragment_downloads": 2,
                "http_chunk_size": 262144,
                "socket_timeout": 10,
                "retries": 1,
                "fragment_retries": 1,
                "extractor_retries": 2,
                "sleep_interval_requests": 1,
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            }

            if video:
                height_filter = f"[height<={self._max_video_height}]" if self._max_video_height and self._max_video_height > 0 else ""
                format_chain = f"bestvideo[ext=mp4]{height_filter}+bestaudio[ext=m4a]/bestvideo{height_filter}+bestaudio/best"
                ydl_opts = {
                    **base_opts,
                    "format": format_chain,
                    "merge_output_format": "mp4",
                    "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
                }
            else:
                ydl_opts = {
                    **base_opts,
                    "format": "bestaudio[ext=m4a]/bestaudio[acodec=opus]/bestaudio/best",
                    "postprocessors": [],
                }

            ydl_opts_cookie = {**ydl_opts, "cookiefile": cookie}

            def _download(ydl_runtime_opts):
                ydl_instance = None
                try:
                    ydl_instance = yt_dlp.YoutubeDL(ydl_runtime_opts)
                    info = ydl_instance.extract_info(url, download=True)
                    if not info:
                        return None
                    time.sleep(0.2)
                    located = self._locate_download_file(video_id, video=video)
                    if located:
                        logger.info(f"✅ Download completed: {located}")
                        return located
                    return None
                except Exception as ex:
                    logger.warning(f"⚠️ Download error for {video_id}: {ex}")
                    recovered = self._locate_download_file(video_id, video=video)
                    if recovered:
                        logger.info(f"✅ Recovered existing file: {recovered}")
                        return recovered
                    return None
                finally:
                    if ydl_instance:
                        try:
                            ydl_instance.close()
                        except Exception:
                            pass

            logger.info(f"🍪 [COOKIES FALLBACK] Downloading {video_id} with cookies...")
            timeout_seconds = self._resolve_timeout(self.api_stream_timeout, 10, 25)
            try:
                result = await asyncio.wait_for(asyncio.to_thread(_download, ydl_opts_cookie), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning(f"⏰ Cookies fallback timed out for {video_id} after {timeout_seconds} seconds")
                result = None
            if result:
                logger.info(f"✅ [COOKIES SUCCESS] Downloaded: {result}")
            else:
                logger.warning(f"⚠️ [COOKIES FAILED] Could not download {video_id}")
            return result

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def url(self, message_1: types.Message) -> Union[str, None]:
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
            return link.split("&si")[0].split("?si")[0]
        return None

    async def search_related(self, title: str, channel_name: str = None, exclude_id: str = None, limit: int = 8) -> "Track | None":
        queries = []
        if channel_name:
            queries.append(f"{channel_name} songs")
        clean_title = re.sub(r"\s*[-|].*", "", title).strip()
        queries += [
            f"{clean_title} similar songs",
            f"songs like {clean_title}",
            f"{clean_title} best songs",
        ]
        if channel_name:
            queries.append(f"{channel_name} best songs")

        tried = set()
        for query in queries:
            if query in tried:
                continue
            tried.add(query)
            try:
                _search = VideosSearch(query, limit=limit)
                results = await _search.next()
            except Exception as e:
                logger.debug(f"search_related query failed '{query}': {e}")
                continue

            if not results or not results.get("result"):
                continue

            candidates = [
                r for r in results["result"]
                if r.get("id") and r.get("link") and r.get("id") != exclude_id
            ]
            if not candidates:
                continue

            random.shuffle(candidates)
            data = candidates[0]
            duration = data.get("duration")
            is_live = duration is None or duration == "LIVE"
            return Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name"),
                duration=duration if not is_live else "LIVE",
                duration_sec=0 if is_live else utils.to_seconds(duration),
                message_id=0,
                title=data.get("title")[:25],
                ytitle=data.get("title"),
                thumbnail=data.get("thumbnails", [{}])[-1].get("url", "").split("?")[0],
                url=data.get("link"),
                view_count=data.get("viewCount", {}).get("short"),
                is_live=is_live,
            )
        return None

    async def search(self, query: str, m_id: int) -> Track | None:
        cache_key = query
        current_time = asyncio.get_running_loop().time()

        if cache_key in self.search_cache:
            cached_result, cache_timestamp = self.search_cache[cache_key]
            if current_time - cache_timestamp < 600:
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
            self.search_cache[cache_key] = (track, current_time)
            if len(self.search_cache) > 100:
                oldest_key = min(self.search_cache.keys(), key=lambda k: self.search_cache[k][1])
                del self.search_cache[oldest_key]
            return replace(track)
        return None

    async def playlist(self, limit: int, user: str, url: str) -> list[Track]:
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
            raise Exception(f"Failed to parse playlist. YouTube may have changed their structure.") from e
        except Exception as e:
            logger.error(f"Playlist extraction error: {e}")
            raise

    async def download(self, video_id: str, is_live: bool = False, video: bool = False) -> Optional[str]:
        if is_live:
            logger.info(f"🔴 Live stream detected for {video_id}, using cookies method...")
            cookie = self.get_cookies()
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "cookiefile": cookie,
                "format": "bestaudio/best",
                "noplaylist": True,
                "socket_timeout": 10,
                "extractor_retries": 2,
                "sleep_interval_requests": 1,
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            }

            def _extract_url():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    try:
                        info = ydl.extract_info(self.base + video_id, download=False)
                        if not info:
                            return None
                        direct = info.get("url")
                        if direct:
                            return direct
                        for fmt in info.get("formats", []):
                            if fmt.get("acodec") != "none" and fmt.get("url"):
                                return fmt["url"]
                        return info.get("manifest_url")
                    except Exception as ex:
                        logger.error(f"Live stream extraction failed: {ex}")
                        return None

            try:
                stream_url = await asyncio.wait_for(asyncio.to_thread(_extract_url), timeout=20)
                if stream_url:
                    logger.info(f"✅ Live stream URL extracted for {video_id}")
                return stream_url
            except asyncio.TimeoutError:
                logger.error(f"Live stream URL extraction timed out for {video_id}")
                return None

        result = None
        if self.enable_api and self.api_url and self.artistbots_key:
            logger.info(f"🎯 [PRIORITY 1] Trying API download for {video_id}")
            result = await self.download_via_api(self.base + video_id, video=video)
            if result:
                logger.info(f"✅ [SUCCESS] Downloaded via API: {video_id}")
                return result
            logger.warning(f"⚠️ [API FAILED] {video_id}, trying cookies fallback...")

        if self.enable_cookies_fallback:
            logger.info(f"🍪 [PRIORITY 2] Trying cookies download for {video_id}")
            result = await self.download_via_cookies(video_id, video=video)
            if result:
                logger.info(f"✅ [SUCCESS] Downloaded via cookies: {video_id}")
                return result
            logger.error(f"❌ [COOKIES FAILED] Could not download {video_id}")

        if not result:
            logger.error(f"❌ [FAILED] All download methods failed for {video_id}")
        return result
