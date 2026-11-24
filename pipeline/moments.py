"""Moment finder: turn a stream VOD into ranked hype windows.

Signals (all free, all local):
  1. keyword hits in the Whisper transcript ("insane", "let's go", ...)
  2. speaking rate spikes (excited fast speech)
  3. audio loudness spikes (screaming / explosions)
  4. optional Twitch chat message-rate spikes (TwitchDownloader JSON)
"""
import json
import math
from pathlib import Path

import numpy as np

from .config import work_dir
from .utils import log

WHISPER = None  # lazy singleton


def _get_whisper(model_name: str):
    global WHISPER
    if WHISPER is None:
        from faster_whisper import WhisperModel

        log.info("loading whisper model '%s'", model_name)
        WHISPER = WhisperModel(model_name, device="cpu", compute_type="int8")
    return WHISPER


def _load_wav_float(path: Path) -> np.ndarray:
    """Read a 16 kHz mono wav as float32 — avoids PyAV version quirks."""
    import wave

    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1, (
            "expected the 16 kHz mono wav produced by utils.extract_audio"
        )
        raw = wf.readframes(wf.getnframes())
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return data


def transcribe(audio_wav: Path, model_name: str) -> list[dict]:
    """Word-level transcript: [{word, start, end}]."""
    model = _get_whisper(model_name)
    audio = _load_wav_float(audio_wav)
    segments, _info = model.transcribe(
        audio, word_timestamps=True, vad_filter=True
    )
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            token = w.word.strip()
            if token:
                words.append({"word": token.lower(), "start": w.start, "end": w.end})
    log.info("transcript: %d words", len(words))
    return words


def audio_energy(audio_wav: Path, fps: int = 2) -> np.ndarray:
    """RMS loudness per 0.5s window, normalised to 0..1."""
    import wave

    with wave.open(str(audio_wav), "rb") as wf:
        rate = wf.getframerate()
        n = wf.getnframes()
        data = np.frombuffer(wf.readframes(n), dtype=np.int16).astype(np.float32)
    win = max(1, rate // fps)
    nwin = len(data) // win
    if nwin == 0:
        return np.zeros(1)
    rms = np.sqrt(np.mean(data[: nwin * win].reshape(nwin, win) ** 2, axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    db -= db.min()
    peak = db.max() if db.max() > 0 else 1.0
    return db / peak


def chat_rates(chat_json: Path | None, duration_s: float) -> np.ndarray | None:
    """Messages per 10s bucket from a TwitchDownloader chat JSON (optional)."""
    if not chat_json or not chat_json.exists():
        return None
    try:
        data = json.loads(chat_json.read_text(encoding="utf-8"))
        comments = data.get("comments", data if isinstance(data, list) else [])
        offsets = [c.get("content_offset_seconds", 0) for c in comments]
    except (json.JSONDecodeError, AttributeError):
        return None
    if not offsets:
        return None
    buckets = np.zeros(int(duration_s // 10) + 1)
    for t in offsets:
        idx = int(t // 10)
        if 0 <= idx < len(buckets):
            buckets[idx] += 1
    if buckets.sum() == 0:
        return None
    return buckets / buckets.max()


def _keyword_hits(words_in_window: list[dict], keywords: list[str]) -> tuple[int, list]:
    """(hit_count, [(word_start, keyword)]) — works for single words AND
    multi-word keywords ("let's go", "oh my god") via a joined-text match."""
    hits = 0
    times: list[tuple[float, str]] = []
    for k in keywords:
        if not k:
            continue
        if " " in k:
            text = " ".join(w["word"] for w in words_in_window)
            idx = text.lower().find(k)
            if idx < 0:
                continue
            # map the char offset back to the nearest word's start time
            pos = 0
            for w in words_in_window:
                if pos + len(w["word"]) > idx:
                    times.append((w["start"], k))
                    break
                pos += len(w["word"]) + 1
            hits += 1
        else:
            for w in words_in_window:
                if k in w["word"]:
                    times.append((w["start"], k))
                    hits += 1
    return hits, times


def _hook_from(words_in_window: list[dict], keywords: list[str]) -> str:
    """Pick a short punchy hook line: prefer a keyword-bearing phrase."""
    text = " ".join(w["word"] for w in words_in_window)
    for k in keywords:
        if k in text:
            idx = text.lower().find(k)
            start = text.rfind(" ", 0, max(0, idx - 40)) + 1
            chunk = text[start : idx + 45].strip()
            return " ".join(chunk.split()[:5]).upper()
    first = " ".join(w["word"] for w in words_in_window[:5])
    return first.strip().upper()[:40]


def find_moments(
    words: list[dict],
    energy: np.ndarray,
    keywords: list[str],
    duration: float,
    min_len: int,
    max_len: int,
    chat_json: Path | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Slide a window over the timeline, score each position, return the best k."""
    if duration < min_len + 2:
        return []

    chat = chat_rates(chat_json, duration)
    fps = 2  # energy resolution: 0.5s per sample
    step = 5.0  # test a candidate every 5 seconds
    cands: list[dict] = []

    t = 0.0
    while t + min_len <= duration:
        wlen = min(max_len, max(min_len, duration - t))
        wend = t + wlen

        in_win = [w for w in words if w["start"] >= t and w["end"] <= wend]
        kw, kw_times = _keyword_hits(in_win, keywords)

        # speaking rate: words per second, scaled
        wps = len(in_win) / wlen

        e0, e1 = int(t * fps), int(wend * fps)
        energy_score = float(np.mean(energy[e0:e1])) if e1 > e0 else 0.0

        score = kw * 3.0 + wps * 1.5 + energy_score * 2.0
        if chat is not None:
            c0, c1 = int(t // 10), int(wend // 10)
            c1 = max(c1, c0 + 1)
            chat_score = float(np.mean(chat[c0:c1]))
            score += chat_score * 4.0

        if kw > 0 or wps > 1.2 or energy_score > 0.35:
            cands.append(
                {
                    "start": round(t, 2),
                    "end": round(wend, 2),
                    "duration": round(wlen, 2),
                    "score": round(score, 3),
                    "hook": _hook_from(in_win, keywords) if in_win else "",
                    "keywords": kw,
                    "kw_times": kw_times,
                }
            )
        t += step

    # greedy non-overlapping pick, best score first
    cands.sort(key=lambda c: c["score"], reverse=True)
    picked: list[dict] = []
    for c in cands:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= top_k:
            break
    picked.sort(key=lambda c: c["start"])
    for c in picked:
        if not c["hook"]:
            c["hook"] = "watch this"
    log.info(
        "moments: %s",
        [(m["start"], m["end"], m["score"], m["hook"]) for m in picked],
    )
    return picked
