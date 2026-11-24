"""Source resolution: local files or yt-dlp downloads (Twitch/Kick/YouTube/direct)."""
from pathlib import Path

import yt_dlp

from .config import work_dir
from .utils import extract_audio, log


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
    outtmpl = str(work / "%(id)s.%(ext)s")
    opts = {
        "outtmpl": outtmpl,
        # cap at 1080p: Shorts are 720x1280, no need for more
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
    }
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
