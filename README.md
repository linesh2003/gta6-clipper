# 🎬 GTA 6 Clip Factory

Watches **iShowSpeed** and **CarryMinati** (add anyone else), auto-clips the hype
moments from their newest GTA 6 streams, styles them like viral Shorts, and
sends the finished clips **straight to your Telegram** — with a ready-to-paste
YouTube title, description and hashtags. **You** post them to Shorts. No
YouTube API, no Google Cloud, no auto-posting.

```
new stream drops → channels checked every 3 h
      ↓
hype moments found (keywords + screams + talking speed)
      ↓
vertical clip rendered: karaoke captions, hook banner, LIVE badge,
neon HUD frame, progress bar, emoji pops, breathing zoom
      ↓
Telegram: 🎬 video + 📋 copy-paste caption block
      ↓
you: save video → paste caption → post to Shorts
```

## The look (all automatic)

- **Karaoke captions** — Anton (the classic viral font), white → accent color
  word-by-word, pop animation on every line
- **Hook banner** — the moment's catchphrase, big, first seconds of the clip
- **🔴 LIVE — streamer** badge (top-left, whole clip)
- **GTA-style neon HUD corner brackets** around the frame
- **Progress bar** filling along the bottom
- **Emoji pops** (🤯😱🚔💰🔥💀…) exactly when hype words are spoken
- **Breathing zoom** on the gameplay so it never feels static
- **Loudness normalized** to −14 LUFS (how YouTube wants Shorts audio)
- Color scheme rotates per clip: vice pink / neon purple / heat orange /
  mint / gold

> ⚠️ **Clip responsibly.** Only clip streamers who allow clipping, and keep
> your edits transformative (the captions, crops and styling here help).
> Mass-uploading unedited other people's content can get claims or strikes —
> the pipeline makes the clips, you make the judgment calls.

---

## Setup (one time, ~15 minutes)

### Part 1 — Put the factory on GitHub

1. Go to **github.com** → sign up / log in.
2. Top-right **+** → **New repository** → name: `gta6-clipper` → **Public**
   (public = unlimited free automation minutes) → **Create repository**.
3. On the new page click **uploading an existing file**.
4. Drag the **whole `gta6-clipper` folder** (README.md, config.yaml, pipeline/,
   assets/, .github/, state/) into the upload box → **Commit changes**.
5. Click into **`.github/workflows/`** and confirm `produce.yml` is there.
   *(If the hidden folder didn't upload: Add file → Create new file → type
   `.github/workflows/produce.yml` → paste its contents → commit.)*
6. Repo → **Actions** tab → if asked, click
   **I understand my workflows, go ahead and enable them**.

### Part 2 — Make your Telegram delivery bot

1. Telegram → search **@BotFather** → **Start** → send `/newbot`.
2. Name: anything (`My Clip Factory`). Username: must end in `bot`
   (`myclipfactory_bot`).
3. BotFather replies with a **token** like `7123456789:AAHfk3s...` — copy it.
4. **Open your bot's chat** (tap its name in BotFather's message) and send it
   `hi` — bots can only message people who wrote first.
5. In a browser open: `https://api.telegram.org/bot` + your token +
   `/getUpdates` → in the JSON find `"chat":{"id":1234567890` → copy that
   number. (Empty page? Send `hi` again and refresh.)

### Part 3 — Give GitHub the 2 secrets

Repo → **Settings** → **Secrets and variables → Actions** → **New repository
secret** — add both:

| Name | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | the token from Part 2 |
| `TELEGRAM_CHAT_ID` | the number from Part 2 |

No spaces around the values. That's all the secrets there are.

### Part 4 — First run

1. Repo → **Actions** → **produce clips** → **Run workflow** → green
   **Run workflow** button (leave clips count empty = 3).
2. First run: ~10–20 min (installs + transcribes). Later runs with no new
   stream: ~2 min. With a new stream: ~15 min.
3. Telegram: your bot sends **🎬 CLIP 1/3** videos, each followed by a
   **📋 COPY-PASTE FOR YOUTUBE** block. Clips are also saved as repo
   artifacts (Actions → run → Artifacts) as backup.

### Part 5 — Upload to Shorts (manual, ~1 min per clip)

1. In Telegram tap the video → **Save to gallery / Downloads**.
2. Open the 📋 message → copy **TITLE** and **DESCRIPTION**.
3. YouTube app → **+** → **Create a Short** → pick the saved video →
   paste the title → paste the description → **Upload Short**.

From now on it runs itself: **every 3 hours** the factory checks both channels
and clips anything new (each stream clipped exactly once, tracked in
`state/state.json`).

---

## Keep it flowing — config.yaml cheatsheet

```yaml
sources:
  - type: channel                 # auto-follow = unlimited clips
    url: "https://www.youtube.com/@IShowSpeed/streams"
    credit: "iShowSpeed"
    max_new_per_run: 1            # newest unseen streams per run
    min_vod_minutes: 20
  # add as many channels as you want, same pattern
  # - type: vod_url               # one specific VOD (works for Twitch too)
  #   url: "https://www.twitch.tv/videos/123456789"
  #   credit: "Someone"
```

| Setting (style:) | What it does |
| --- | --- |
| `crop_mode: blur_pad` | gameplay centered over blurred background (default). `center` = fills the screen |
| `palette: auto` | rotates the 5 neon schemes; or fix one: `vice/neon/heat/mint/gold` |
| `punch_zoom` / `emoji_pops` | turn the zoom / emoji pops off |
| `font_size`, `caption_margin_bottom` | caption look and position |
| `min/max_clip_seconds` | clip length window (default 15–45 s) |
| `whisper_model` | `small` (default) = better hooks; `tiny` = fastest |

`schedule:` → `clips_per_run` = clips per run. `shorts_metadata:` = the
copy-paste title/description templates and hashtags.

Commit any config change → it applies from the next run.

## Test on your own machine

```bash
pip install -r requirements.txt        # ffmpeg needed locally
python -m pipeline.run produce --count 1 --local myvideo.mp4 --dry-run
```

The clip lands in `drafts/` (dry-run skips Telegram).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Run log says "no new VODs to clip" | Normal — the streamers haven't posted a new stream since the last run. It checks again in 3 h. |
| Bot never messages you | You must send the bot `hi` once first (Part 2 step 4). Check both secrets for spaces. |
| "Chat not found" in logs | `TELEGRAM_CHAT_ID` wrong — redo the getUpdates step. |
| Clips look unstyled (no Anton font) | The workflow installs `assets/fonts/` automatically; locally, copy the .ttf into your user fonts folder. |
| A run failed red | Open the failed step; most common is a YouTube hiccup — just **Run workflow** again (the VOD is retried, up to 3 tries). |
| Hooks are weird/nonsense | Raise `whisper_model` to `small`/`medium`, or sharpen `keywords:`. |
| Telegram upload failed for a big clip | Handled automatically (re-encodes under 50 MB). Rare: run again. |

## Under the hood / credits

- `pipeline/discover.py` — finds the newest streams (yt-dlp flat playlist)
- `pipeline/moments.py` — faster-whisper word timestamps + keyword/loudness/
  speaking-rate scoring
- `pipeline/captions.py` — the whole overlay look as a libass `.ass` file
- `pipeline/render.py` — two-pass ffmpeg render (exact cut → style pass)
- Fonts: [Anton](https://fonts.google.com/specimen/Anton) (SIL OFL) ·
  Emoji: [Twemoji](https://github.com/jdecked/twemoji) (CC-BY 4.0) ·
  STT: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
