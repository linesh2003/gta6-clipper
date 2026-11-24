"""Orchestrator — one command:

  python -m pipeline.run produce   # find new VODs -> hype moments -> styled
                                   # vertical clips -> Telegram + artifacts

Local testing:
  python -m pipeline.run produce --count 1 --local path/to/video.mp4 --dry-run
"""
import argparse
import os
import sys
from pathlib import Path

from . import discover, moments, state as state_mod, telegram
from .config import Config, drafts_dir, work_dir
from .download import is_deferrable_error, prepare
from .render import probe_ok, render_moment
from .utils import ffprobe_duration, log, setup_logging, slugify


def cmd_produce(
    cfg: Config, count: int, local_file: str | None, dry_run: bool,
    model: str | None,
) -> int:
    state = state_mod.load()
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    whisper_model = model or cfg.whisper_model

    # 1) which VODs do we work on?
    if local_file:
        sources = [{"type": "local_path", "path": local_file, "credit": "local"}]
    else:
        sources = []
        try:
            sources = discover.discover_sources(cfg, state)
        except Exception as exc:
            log.error("channel discovery crashed (%s) — skipping this round", exc)
        if len(sources) > cfg.max_vods_per_run:
            sources = sources[: cfg.max_vods_per_run]
    if not sources:
        print(
            "no new VODs to clip right now (all seen / nothing new on the "
            "channels) — the next scheduled run will look again"
        )
        state_mod.save(state)
        return 0

    # 2) download + transcribe + find hype moments
    candidates = []
    for src in sources:
        vod_id = src.get("_vod_id")
        try:
            video, audio = prepare(src)
        except Exception as exc:
            log.error("source failed (%s): %s", src.get("url", src.get("path")), exc)
            if vod_id and is_deferrable_error(exc):
                log.warning(
                    "vod %s deferred (scheduled stream or YouTube bot-check) — "
                    "no retry burned, next run will try again. If bot-checks keep "
                    "happening, add the YT_COOKIES secret (see README, Cookies)",
                    vod_id,
                )
            elif vod_id:
                if state_mod.mark_failure(state, vod_id) >= 3:
                    state_mod.mark_seen(state, vod_id)
                    log.warning("giving up on vod %s after 3 failures", vod_id)
            continue
        duration = ffprobe_duration(video)
        log.info("source ready: %s (%.0fs)", video.name, duration)

        words = moments.transcribe(audio, whisper_model)
        energy = moments.audio_energy(audio)
        found = moments.find_moments(
            words, energy, cfg.keywords, duration,
            cfg.min_clip, cfg.max_clip, None, top_k=count + 2,
        )
        for m in found:
            m["video"] = str(video)
            m["credit"] = src.get("credit", "")
            m["_words"] = words
        candidates.extend(found)

        if vod_id:
            # the VOD was handled — never clip it again, even if 0 moments hit
            state_mod.mark_seen(state, vod_id)

    if not candidates:
        print("transcripts ready but no hype moments found — loosen keywords in config.yaml")
        state_mod.save(state)
        return 0

    candidates.sort(key=lambda m: m["score"], reverse=True)
    chosen = candidates[:count]

    # 3) render the viral-styled clips
    produced = []
    for i, m in enumerate(chosen):
        clip_id = state_mod.next_clip_id()
        draft_id = f"{clip_id}-{slugify(m['hook'] or 'clip', 20)}-{i}"
        out_path = drafts_dir() / f"{draft_id}.mp4"
        try:
            render_moment(Path(m["video"]), m, m["_words"], cfg, out_path, draft_id)
        except Exception as exc:
            log.error("render failed for %s: %s", draft_id, exc)
            continue
        if not probe_ok(out_path):
            log.error("render output invalid: %s", out_path)
            continue

        title = cfg.title_for(m["hook"])
        state_mod.record_clip(
            state,
            {
                "id": draft_id,
                "run_id": run_id,
                "created": clip_id,
                "hook": m["hook"],
                "title": title,
                "credit": m.get("credit", ""),
                "source": m.get("video", ""),
            },
        )
        produced.append((draft_id, out_path, m))

        # 4) deliver: clip video + ready-to-paste YouTube caption pack
        if not dry_run:
            idx = len(produced)
            head = f"🎬 CLIP {idx}/{len(chosen)} — {title}"
            telegram.send_video(out_path, head)
            telegram.send_message(cfg.caption_pack(m["hook"], m.get("credit", "")))

    state_mod.save(state)

    print(f"\n{len(produced)} clip(s) ready in drafts/:")
    for d, _p, m in produced:
        print(f'  {d}  hook="{m["hook"]}"  score={m["score"]}')
    if dry_run:
        print("dry-run: nothing sent to Telegram")
    else:
        print("delivered to Telegram with copy-paste captions — upload when ready")
    return 0


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(prog="shorts")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("produce", help="find new VODs, render styled clips, deliver")
    p.add_argument("--count", type=int, default=None, help="clips to produce this run")
    p.add_argument("--local", default=None, help="use a local video file instead of config sources")
    p.add_argument("--dry-run", action="store_true", help="skip Telegram delivery")
    p.add_argument("--whisper", default=None, help="override whisper model (tiny/base/small)")
    args = parser.parse_args()

    cfg = Config()
    return cmd_produce(
        cfg,
        args.count if args.count is not None else cfg.clips_per_run,
        args.local,
        args.dry_run,
        args.whisper,
    )


if __name__ == "__main__":
    sys.exit(main())
