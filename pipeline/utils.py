"""Small shared helpers: logging, ffmpeg calls, misc."""
import json
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("shorts")


def setup_logging(level: int = logging.INFO) -> None:
    if not log.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


def run_ffmpeg(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run ffmpeg quietly; raise with the tail of stderr on failure."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    log.debug("ffmpeg %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{proc.stderr[-2000:]}")
    return proc


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def slugify(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-")) or "clip"


def extract_audio(video: Path, out_wav: Path) -> Path:
    """16 kHz mono wav — what faster-whisper wants."""
    run_ffmpeg(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(out_wav)])
    return out_wav
