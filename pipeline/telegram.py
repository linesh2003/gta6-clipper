"""Telegram: finished-clip delivery (no approvals — you upload manually)."""
import os
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def _chat() -> str | None:
    return os.environ.get("TELEGRAM_CHAT_ID") or None


def configured() -> bool:
    return bool(_token() and _chat())


def send_video(path: Path, caption: str) -> bool:
    """Send a finished clip. False = skipped/failed (non-fatal)."""
    if not configured():
        print("telegram not configured — clip saved locally, nothing sent")
        return False
    try:
        with open(path, "rb") as fh:
            r = requests.post(
                API.format(token=_token(), method="sendVideo"),
                data={
                    "chat_id": _chat(),
                    "caption": caption[:1000],
                    "supports_streaming": "true",
                },
                files={"video": fh},
                timeout=900,
            )
        r.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"telegram send_video failed (clip kept): {exc}")
        return False


def send_message(text: str) -> bool:
    if not configured():
        print(text)
        return False
    try:
        r = requests.post(
            API.format(token=_token(), method="sendMessage"),
            json={"chat_id": _chat(), "text": text[:4000]},
            timeout=60,
        )
        r.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"telegram send_message failed: {exc}")
        return False
