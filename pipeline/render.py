"""Renderer: cut a moment from the source VOD into a vertical Short,
burning in the full viral overlay set (captions, hook, HUD frame, badge,
progress bar) and popping keyword emojis on screen."""
import shutil
import subprocess
from pathlib import Path

from .captions import build_ass
from .config import Config, assets_dir, work_dir
from .utils import ffprobe_duration, log, run_ffmpeg

# keyword fragments -> twemoji sprite (assets/emoji/<code>.png)
EMOJI_MAP: list[tuple[tuple[str, ...], str]] = [
    (("police", "cops", "cop ", "wanted", "busted", "siren", "jail"), "1f694"),
    (("money", "rob", "heist", "bank", "rich", "dollar", "million"), "1f4b0"),
    (("crash", "explode", "boom", "failed", "mission", "wanted"), "1f6a8"),
    (("insane", "crazy", "wtf", "unreal", "no way", "omg", "ridiculous"), "1f92f"),
    (("oh my god", "scream", "scared", "horror", "jumpscare", "shut up"), "1f631"),
    (("funny", "laugh", "lmao", "meme", "bruh", "hilarious"), "1f602"),
    (("dead", "died", "rip ", "killed", "death", "gone"), "1f480"),
    (("fire", "lit ", "burn", "clutch", "let's go", "les go"), "1f525"),
    (("chat", "awkward", "oops", "flushed", "my bad"), "1f633"),
]


def _emoji_for(keyword: str) -> Path | None:
    kw = keyword.strip().lower()
    if not kw:
        return None
    for fragments, code in EMOJI_MAP:
        for frag in fragments:
            if frag in kw or kw in frag:
                p = assets_dir("emoji") / f"{code}.png"
                if p.exists():
                    return p
    return None


def _emoji_overlays(cfg: Config, kw_times: list) -> list[tuple[Path, float]]:
    """(png_path, clip_relative_time) — max 8 pops, >=1.5s apart."""
    overlays: list[tuple[Path, float]] = []
    last = -10.0
    for t, kw in kw_times:
        if len(overlays) >= 8:
            break
        if t - last < 1.5:
            continue
        png = _emoji_for(kw)
        if png:
            overlays.append((png, max(0.0, t)))
            last = t
    return overlays


def _video_filters(cfg: Config, src_label: str = "0:v") -> str:
    """Landscape -> vertical conversion filters (input: the pre-cut clip)."""
    w, h = cfg.width, cfg.height
    if cfg.crop_mode == "center":
        return (
            f"[{src_label}]crop=ih*{w}/{h}:ih,scale={w}:{h}:flags=bicubic,setsar=1,fps={cfg.fps}[base]"
        )
    # blur_pad (default): full frame over a blurred background
    return (
        f"[{src_label}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"boxblur=24:6[bg];"
        f"[{src_label}]scale=-2:{h}:flags=bicubic[fg];"
        f"[bg][fg]overlay=(W-w)/2:0,setsar=1,fps={cfg.fps}[base]"
    )


def _keyframe_before(video: Path, t: float) -> float:
    """Find the last keyframe at or before t — lets pass 1 fast-seek there
    while the output-side -ss still lands frame-accurately on t."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-skip_frame", "nokey", "-show_entries", "frame=pts_time",
            "-of", "csv=p=0",
            "-read_intervals", f"{max(0.0, t - 30):.3f}%{t + 0.1:.3f}",
            str(video),
        ],
        capture_output=True, text=True, check=True,
    )
    kfs = []
    for line in out.stdout.strip().splitlines():
        try:
            k = float(line.strip().rstrip(","))
        except ValueError:
            continue
        if k <= t:
            kfs.append(k)
    return max(kfs) if kfs else 0.0


def render_moment(
    source_video: Path,
    moment: dict,
    all_words: list[dict],
    cfg: Config,
    out_path: Path,
    draft_id: str,
) -> Path:
    """Two passes (both proven-stable, no trim/atrim filters):

      pass 1 "cut":  exact window -> near-lossless intermediate, 0-based pts
                     (input -ss = fast keyframe pre-seek, output -ss = precise)
      pass 2 "style": vertical conversion -> breathing zoom -> emoji pops
                      -> caption/overlay burn-in -> loudness normalize
    """
    start = float(moment["start"])
    dur = float(moment["duration"])
    words_window = [
        w for w in all_words if w["start"] >= start and w["end"] <= start + dur
    ]
    kw_times = [
        (t - start, kw)
        for (t, kw) in (moment.get("kw_times") or [])
        if start <= t <= start + dur
    ]

    work = work_dir()
    ass_path = build_ass(
        words_window, moment.get("hook", ""), cfg, work / f"{draft_id}.ass",
        offset=start, credit=moment.get("credit", ""), kw_times=kw_times,
        duration=dur, palette_seed=draft_id,
    )
    safe_path = (
        ass_path.as_posix()
        .replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )

    cut_path = work / f"{draft_id}.cut.mp4"
    seek_in = _keyframe_before(source_video, start)
    log.info("rendering %s (%.1fs from %.1fs)", draft_id, dur, start)

    # pass 1 — exact cut, high-quality intermediate
    run_ffmpeg(
        [
            "-ss", f"{seek_in:.3f}", "-i", str(source_video),
            "-ss", f"{start - seek_in:.3f}", "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            str(cut_path),
        ]
    )

    # pass 2 — style. Build the filter chain:
    w, h, fps = cfg.width, cfg.height, cfg.fps
    chain = _video_filters(cfg)
    stage = "base"

    if cfg.punch_zoom:
        # subtle breathing zoom so the gameplay never feels static
        chain += (
            f";[{stage}]zoompan=z='1+0.05*sin(2*PI*on/150)'"
            f":x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2'"
            f":d=1:s={w}x{h}:fps={fps}[zoomed]"
        )
        stage = "zoomed"

    emoji_inputs: list[str] = []
    for i, (png, t) in enumerate(_emoji_overlays(cfg, kw_times)):
        idx = i + 1
        emoji_inputs.extend(["-i", str(png)])
        bounce = f"'{h}*0.24-14*abs(sin((t-{t:.2f})*6))'"
        chain += (
            f";[{idx}:v]scale=132:132[em{i}];"
            f"[{stage}][em{i}]overlay=(W-w)/2:{bounce}"
            f":enable='between(t,{t:.2f},{t + 1.1:.2f})'[e{i}]"
        )
        stage = f"e{i}"

    chain += f";[{stage}]ass='{safe_path}'[vout]"
    chain += ";[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"

    run_ffmpeg(
        [
            "-i", str(cut_path),
            *emoji_inputs,
            "-filter_complex", chain,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart", "-shortest",
            str(out_path),
        ]
    )
    cut_path.unlink(missing_ok=True)

    _enforce_telegram_size(out_path)
    return out_path


def _enforce_telegram_size(out_path: Path, limit_mb: float = 47.0) -> None:
    """Telegram bot API rejects videos > 50 MB — re-encode smaller if needed."""
    size_mb = out_path.stat().st_size / 1e6
    if size_mb <= limit_mb:
        return
    log.info("clip is %.1f MB — re-encoding at lower bitrate", size_mb)
    tmp = out_path.with_suffix(".small.mp4")
    run_ffmpeg(
        [
            "-i", str(out_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            str(tmp),
        ]
    )
    shutil.move(str(tmp), str(out_path))


def probe_ok(path: Path) -> bool:
    """Sanity check a rendered clip: real duration, not corrupted."""
    try:
        dur = ffprobe_duration(path)
        return dur > 1.0
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return False
