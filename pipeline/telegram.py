"""Telegram: finished-clip delivery (no approvals — you upload manually)."""
import os
import time
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def _chat() -> str | None:
    return os.environ.get("TELEGRAM_CHAT_ID") or None


def configured() -> bool:
    return bool(_token() and _chat())


def _post(method: str, data: dict, files: dict | None = None, timeout: int = 60):
    """POST one Telegram call, waiting out 429 rate limits (Telegram tells us how long)."""
    last_exc: requests.RequestException | None = None
    for _attempt in range(6):
        try:
            r = requests.post(
                API.format(token=_token(), method=method),
                data=data,
                files=files,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(10)
            continue
        if r.status_code != 429:
            r.raise_for_status()
            return r
        # rate-limited: respect retry_after, capped at 60 s per wait
        wait = 30
        try:
            wait = min(int(r.json().get("parameters", {}).get("retry_after", 30)), 60)
        except Exception:
            pass
        print(f"telegram {method}: rate-limited, waiting {wait}s ...", flush=True)
        time.sleep(wait + 2)
        last_exc = requests.RequestException(f"429 persisted: {r.text[:200]}")
    raise last_exc  # type: ignore[misc]


def send_video(path: Path, caption: str) -> bool:
    """Send a finished clip. False = skipped/failed (non-fatal)."""
    if not configured():
        print("telegram not configured — clip saved locally, nothing sent")
        return False
    try:
        # read fully into memory so retries resending the same bytes are safe
        blob = path.read_bytes()
        _post(
            "sendVideo",
            {
                "chat_id": _chat(),
                "caption": caption[:1000],
                "supports_streaming": "true",
            },
            files={"video": ("clip.mp4", blob, "video/mp4")},
            timeout=900,
        )
        return True
    except requests.RequestException as exc:
        print(f"telegram send_video failed (clip kept): {exc}")
        return False


def send_message(text: str) -> bool:
    if not configured():
        print(text)
        return False
    try:
        _post("sendMessage", {"chat_id": _chat(), "text": text[:4000]})
        return True
    except requests.RequestException as exc:
        print(f"telegram send_message failed: {exc}")
        print(text)  # keep the caption pack recoverable from the run log
        return False
