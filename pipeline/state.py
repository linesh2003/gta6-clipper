"""Pipeline state: state/state.json (committed back to the repo by Actions).

Tracks which channel VODs were already clipped (so every new stream is
processed exactly once) and a small log of produced clips.
"""
import datetime as _dt
import json
from pathlib import Path

from .config import state_dir

STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "state.json"

SEEN_CAP = 300  # keep state.json small forever


def load() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"seen_vods": {}, "vod_failures": {}, "clips": []}


def save(state: dict) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def next_clip_id() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("c%Y%m%d-%H%M%S")


def today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def mark_seen(state: dict, vod_id: str) -> None:
    seen = state.setdefault("seen_vods", {})
    seen[vod_id] = today()
    # trim oldest entries so the file never grows unbounded
    if len(seen) > SEEN_CAP:
        for old in sorted(seen, key=seen.get)[:-SEEN_CAP]:
            seen.pop(old, None)


def mark_failure(state: dict, vod_id: str) -> int:
    """Increment the retry counter; returns the new count (3 = give up)."""
    fails = state.setdefault("vod_failures", {})
    fails[vod_id] = int(fails.get(vod_id, 0)) + 1
    return fails[vod_id]


def record_clip(state: dict, clip: dict) -> None:
    clips = state.setdefault("clips", [])
    clips.append(clip)
    state["clips"] = clips[-100:]
