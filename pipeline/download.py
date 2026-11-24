"""Source resolution: local files or yt-dlp downloads (Twitch/Kick/YouTube/direct)."""
import os
from pathlib import Path

import yt_dlp

from .config import work_dir
from .utils import extract_audio, log

# Error fragments that mean "not the video's fault — try again later" rather
# than "this video is dead". Deferred VODs do not burn their retry counter.
DEFER_PATTERNS = (
    "live event will begin",  # scheduled / upcoming stream — nothing to clip yet
    "sign in to confirm",     # YouTube bot-check — needs cookies (see README)
    "video unavailable",      # usually a false 'unavailable' for stale cookies / flagged IP
    "content isn't available",  # same false message, other wording
    "needs to be reloaded",   # YouTube gate when the JS challenge layer is missing
    "is not available",       # transient YouTube availability hiccups
    "upcoming",
)


def cookies_file() -> str | None:
    """Path to a Netscape cookies.txt given via YT_COOKIES_FILE (if it exists)."""
    p = os.environ.get("YT_COOKIES_FILE", "")
    return p if p and Path(p).exists() else None


def base_opts() -> dict:
    """yt-dlp options shared by discovery and download (incl. cookies when set).

    No player_client override: yt-dlp's maintained defaults + the EJS challenge
    solver (Deno, installed by the workflow) pick the right clients themselves.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    cf = cookies_file()
    if cf:
        opts["cookiefile"] = cf
        log.info("using YouTube cookies from %s", cf)
    return opts


def is_deferrable_error(exc: Exception) -> bool:
    """True = video not ready yet / YouTube wants a login — retry next run, free."""
    text = str(exc).lower()
    return any(p in text for p in DEFER_PATTERNS)


def resolve_source(source: dict) -> Path:
    """Return a local video path for a source entry from config.yaml."""
    stype = source.get("type", "vod_url")
    if stype == "local_path":
        path = Path(source["path"])
        if not path.exists():
            raise FileNotFoundError(
                f"local source not found: {path} — commit it to the repo or fix the path"
            )
        return path

    url = source["url"]
    work = work_dir()
    opts = base_opts()
    opts.update(
        {
            "outtmpl": str(work / "%(id)s.%(ext)s"),
            # relaxed selector: accept any container, re-mux to mp4 afterwards
            "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
            "merge_output_format": "mp4",
            "noplaylist": True,
        }
    )
    log.info("downloading %s", url)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        path = Path(filename).with_suffix(".mp4")  # merged container
        if not path.exists():
            path = Path(filename)
        return path


def prepare(source: dict) -> tuple[Path, Path]:
    """(video_path, audio_wav_path) for a source entry."""
    video = resolve_source(source)
    audio = extract_audio(video, work_dir() / (video.stem + ".wav"))
    return video, audio
