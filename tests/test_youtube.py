import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "hash")
os.environ.setdefault("BOT_TOKEN", "token")
os.environ.setdefault("LOGGER_ID", "1")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("MONGO_DB_URI", "mongodb://localhost:27017")
os.environ.setdefault("STRING_SESSION", "session")

from Elevenyts.core.youtube import YouTube


def test_resolve_timeout_caps_values():
    yt = YouTube()

    assert yt._resolve_timeout(600, 10, 20) == 20
    assert yt._resolve_timeout(5, 10, 20) == 10
    assert yt._resolve_timeout(15, 10, 20) == 15


def test_pick_stream_url_prefers_direct_audio_stream():
    yt = YouTube()
    info = {
        "url": "https://cdn.example.com/stream/audio.mp3",
        "formats": [
            {"url": "https://cdn.example.com/slow.mp4", "vcodec": "avc1", "acodec": "none"},
            {"url": "https://cdn.example.com/fast.m4a", "vcodec": "none", "acodec": "mp4a"},
        ],
    }

    assert yt._pick_stream_url(info) == "https://cdn.example.com/stream/audio.mp3"
