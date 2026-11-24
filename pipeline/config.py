"""Configuration loader: config.yaml + environment."""
import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _template(cfg_text: str, mapping: dict) -> str:
    out = cfg_text
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", str(value))
    return out


class Config:
    """Thin convenience wrapper around config.yaml with sane defaults."""

    def __init__(self, path: Path | None = None):
        cfg_path = path or REPO_ROOT / "config.yaml"
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

        sched = raw.get("schedule", {})
        self.clips_per_run = int(sched.get("clips_per_run", 3))
        self.max_vods_per_run = int(sched.get("max_vods_per_run", 3))

        self.sources = raw.get("sources", []) or []
        self.keywords = [k.lower() for k in (raw.get("keywords") or [])]

        style = raw.get("style", {})
        self.width = int(style.get("width", 720))
        self.height = int(style.get("height", 1280))
        self.fps = int(style.get("fps", 30))
        self.crop_mode = str(style.get("crop_mode", "blur_pad"))
        self.min_clip = int(style.get("min_clip_seconds", 15))
        self.max_clip = int(style.get("max_clip_seconds", 45))
        self.hook_seconds = float(style.get("hook_seconds", 2.8))
        self.font = str(style.get("font", "Anton"))
        self.font_size = int(style.get("font_size", 64))
        self.caption_margin_bottom = int(style.get("caption_margin_bottom", 170))
        self.punch_zoom = bool(style.get("punch_zoom", True))
        self.emoji_pops = bool(style.get("emoji_pops", True))
        self.palette = str(style.get("palette", "auto"))

        # Ready-to-paste Shorts metadata, delivered with every clip.
        meta = raw.get("shorts_metadata", {})
        self.title_template = str(meta.get("title_template", "{hook} 🤯 #shorts"))
        self.description_template = str(
            meta.get(
                "description_template",
                "{hook} — {credit} lost it here 😭\n\n"
                "Which moment should I clip next? Comment 👇\n\n{hashtags}",
            )
        )
        self.hashtags = [h.lstrip("#") for h in (meta.get("hashtags") or [])]
        if not self.hashtags:
            self.hashtags = ["gta6", "gtavi", "shorts", "gaming", "viral"]

        self.whisper_model = str(raw.get("whisper_model", "small"))

    # ------------------------------------------------------------ metadata
    def hashtag_block(self) -> str:
        return " ".join("#" + h for h in self.hashtags)

    def title_for(self, hook: str) -> str:
        return _template(self.title_template, {"hook": hook}).strip()

    def description_for(self, hook: str, credit: str) -> str:
        return _template(
            self.description_template,
            {"hook": hook, "credit": credit or "the streamer", "hashtags": self.hashtag_block()},
        ).strip()

    def caption_pack(self, hook: str, credit: str) -> str:
        """The copy-paste block the bot sends under every finished clip."""
        return (
            "📋 COPY-PASTE FOR YOUTUBE\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"TITLE:\n{self.title_for(hook)}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"DESCRIPTION:\n{self.description_for(hook, credit)}\n"
            "━━━━━━━━━━━━━━━━━━"
        )


def work_dir() -> Path:
    d = REPO_ROOT / "work"
    d.mkdir(exist_ok=True)
    return d


def drafts_dir() -> Path:
    d = REPO_ROOT / "drafts"
    d.mkdir(exist_ok=True)
    return d


def state_dir() -> Path:
    d = REPO_ROOT / "state"
    d.mkdir(exist_ok=True)
    return d


def assets_dir(sub: str = "") -> Path:
    d = REPO_ROOT / "assets"
    if sub:
        d = d / sub
    d.mkdir(parents=True, exist_ok=True)
    return d
