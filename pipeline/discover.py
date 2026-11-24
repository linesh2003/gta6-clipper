"""Auto-discovery: find the newest stream VODs on a creator's channel.

Config entries like

  - type: channel
    url: "https://www.youtube.com/@IShowSpeed/streams"
    credit: "iShowSpeed"
    max_new_per_run: 1        # newest unseen VODs to queue per run
    min_vod_minutes: 20       # ignore shorts/highlights, want full streams

are expanded into concrete VOD URLs the first time each is seen (tracked in
state/state.json), so every new stream the creator posts gets clipped exactly
once — that is what makes the pipeline "unlimited".

The same /streams tab pattern works for any YouTube channel. Twitch VODs can
be queued manually with type: vod_url (https://www.twitch.tv/videos/<id>).
"""
from .utils import log


def latest_vods(channel_url: str, max_items: int = 6) -> list[dict]:
    """Most recent VODs on a channel (flat, fast — no downloads).

    Returns [{id, url, title, duration}] newest first. Upcoming (scheduled)
    and currently-live streams are skipped — they get clipped on a later run
    once they have finished.
    """
    import yt_dlp

    from .download import base_opts

    opts = base_opts()
    opts.update(
        {
            "extract_flat": "in_playlist",
            "playlist_items": f"1:{max_items}",
            "skip_download": True,
        }
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    entries = (info or {}).get("entries") or []
    out: list[dict] = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        if e.get("live_status") in ("is_live", "is_upcoming"):
            continue  # scheduled or still running — nothing finished to clip
        url = e.get("url") or e.get("webpage_url") or ""
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={e['id']}"
        out.append(
            {
                "id": str(e["id"]),
                "url": url,
                "title": (e.get("title") or "")[:120],
                "duration": e.get("duration") or 0,
            }
        )
    log.info("discovery on %s -> %d vod(s)", channel_url, len(out))
    return out


def discover_sources(cfg, state: dict) -> list[dict]:
    """Expand config sources into concrete, un-clipped VOD sources.

    channel entries -> newest unseen VODs (respecting max_new_per_run and
    min_vod_minutes). vod_url / local_path entries pass through unchanged.
    """
    seen = state.setdefault("seen_vods", {})
    fails = state.setdefault("vod_failures", {})
    sources: list[dict] = []

    for src in cfg.sources:
        stype = src.get("type", "vod_url")
        if stype in ("vod_url", "local_path"):
            sources.append(dict(src))
            continue
        if stype != "channel":
            log.warning("unknown source type '%s' — skipped", stype)
            continue

        channel = src.get("url", "")
        credit = src.get("credit", "")
        max_new = int(src.get("max_new_per_run", 1))
        min_seconds = int(src.get("min_vod_minutes", 20)) * 60
        try:
            vods = latest_vods(channel, max_items=8)
        except Exception as exc:
            log.error("discovery failed for %s: %s", channel, exc)
            continue

        fresh = 0
        for v in vods:
            if fresh >= max_new:
                break
            if v["id"] in seen:
                continue
            if fails.get(v["id"], 0) >= 3:
                continue  # gave up on this one before
            if v["duration"] and v["duration"] < min_seconds:
                continue  # a highlights clip, not a real stream
            log.info("new vod on %s: %s", credit or channel, v["title"] or v["id"])
            entry = {"type": "vod_url", "url": v["url"], "credit": credit}
            entry["_vod_id"] = v["id"]
            entry["_vod_title"] = v["title"]
            sources.append(entry)
            fresh += 1

    return sources
