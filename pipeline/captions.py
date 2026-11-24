"""ASS subtitle builder — the viral "GTA neon" look.

Everything burns in via libass (fast, no frame-by-frame compositing):
  - karaoke captions: Anton, white -> accent fill exactly on each word,
    a scale-pop on every line, alternating Vice City accent colors
  - big hook banner (white on a neon box) for the first few seconds
  - "● LIVE — streamer" badge, top-left, whole clip
  - GTA HUD-style neon corner brackets around the frame (vector drawings)
  - thin progress bar filling along the bottom
  - a short frame flash exactly when a hype keyword is spoken
"""
from pathlib import Path

from .utils import log

# ASS colours are &HAABBGGRR (alpha, blue, green, red) — 00 alpha = opaque


def _ass_from_hex(hex_color: str, alpha: int = 0) -> str:
    """'#FF2D78' -> '&H00782DFF' (ASS BGR, with alpha)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# Vice City neon palettes: accent = caption fill + hook box, accent2 = alt fill
PALETTES = [
    {"name": "vice", "accent": "#FF2D78", "accent2": "#12D7FF", "glow": "#FF2D78"},
    {"name": "neon", "accent": "#B026FF", "accent2": "#FFD60A", "glow": "#B026FF"},
    {"name": "heat", "accent": "#FF6B00", "accent2": "#FFD60A", "glow": "#FF6B00"},
    {"name": "mint", "accent": "#00FFB2", "accent2": "#12D7FF", "glow": "#00FFB2"},
    {"name": "gold", "accent": "#FFD60A", "accent2": "#FF2D78", "glow": "#FFD60A"},
]


def pick_palette(name: str, seed: str = "") -> dict:
    if name and name != "auto":
        for p in PALETTES:
            if p["name"] == name:
                return p
    idx = sum(ord(c) for c in seed) % len(PALETTES) if seed else 0
    return PALETTES[idx]


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def _chunk_words(words: list[dict], max_words: int = 4, max_chars: int = 18) -> list[list[dict]]:
    """Split words into short caption lines (2-4 words is the Shorts norm)."""
    lines: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        candidate_len = len(" ".join(x["word"] for x in current + [w]))
        if current and (len(current) >= max_words or candidate_len > max_chars):
            lines.append(current)
            current = []
        current.append(w)
    if current:
        lines.append(current)
    return lines


def _caption_events(words_window: list[dict], cfg, offset: float, palette: dict) -> list[str]:
    """Karaoke caption dialogue lines, times relative to clip start."""
    events: list[str] = []
    margin_v = cfg.caption_margin_bottom
    accent = _ass_from_hex(palette["accent"])
    accent2 = _ass_from_hex(palette["accent2"])

    for i, line_words in enumerate(_chunk_words(words_window)):
        line_start = line_words[0]["start"] - offset
        line_end = line_words[-1]["end"] - offset + 0.25
        if line_start < 0:
            continue

        # \k durations in centiseconds, incl. silent gaps before each word
        karaoke = ""
        prev_end = line_words[0]["start"]
        for w in line_words:
            dur_cs = max(8, round((w["end"] - prev_end) * 100))
            karaoke += f"{{\\k{dur_cs}}}{_escape(w['word']).upper()} "
            prev_end = w["end"]

        pop = "{\\fad(60,40)\\t(0,110,\\fscx116\\fscy116)\\t(110,220,\\fscx100\\fscy100)}"
        style = "CaptionA" if i % 2 == 0 else "CaptionB"
        events.append(
            f"Dialogue: 2,{_ass_time(line_start)},{_ass_time(line_end)},"
            f"{style},,0,0,{margin_v},,{pop}{karaoke.strip()}"
        )
    return events


def _fit_hook(hook: str, cfg) -> tuple[str, int]:
    """Wrap the hook to <=2 lines and shrink font until it fits the width."""
    text = _escape(hook).upper()
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > 14:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    lines = lines[:2]  # never more than 2 lines

    size = int(cfg.font_size * 1.5)
    longest = max(len(l) for l in lines)
    # Anton is very condensed; ~0.5 px/char per pt of font size is safe
    while size > 40 and longest * size * 0.55 > (cfg.width - 56):
        size -= 4
    return "\\N".join(lines), size


def _hook_event(hook: str, cfg) -> str:
    end = max(1.2, cfg.hook_seconds)
    text, size = _fit_hook(hook, cfg)
    pop = "{\\fad(120,180)\\t(0,150,\\fscx118\\fscy118)\\t(150,300,\\fscx100\\fscy100)}"
    return (
        f"Dialogue: 3,{_ass_time(0)},{_ass_time(end)},"
        f"Hook,,0,0,96,,{pop}{{\\fs{size}}}{text}"
    )


def _badge_event(credit: str) -> str:
    label = f"● LIVE — {_escape(credit).upper()}" if credit else "● LIVE"
    dur = 5400  # 1.5 h; event simply outlives any clip (ASS clips to video end)
    return f"Dialogue: 2,0:00:00.00,{_ass_time(dur)},Badge,,0,0,26,,{label}"


def _bracket_shape(W: int, H: int, inset: int, stroke: int, arm: int) -> str:
    """The four GTA HUD corner brackets as one ASS vector drawing.

    libass notes (verified by test): every point after the first must come
    as an explicit `l x y` pair — implicit pairs after `m` do not render.
    """
    m, s, a = inset, stroke, arm

    def L(x: int, y: int, dx: int, dy: int) -> str:
        # an L-bracket polygon anchored at the outer corner (x, y)
        pts = [
            (x, y),
            (x + dx * a, y),
            (x + dx * a, y + dy * s),
            (x + dx * s, y + dy * s),
            (x + dx * s, y + dy * a),
            (x, y + dy * a),
        ]
        body = " ".join(f"{px} {py}" for px, py in pts[1:])
        return f"m {pts[0][0]} {pts[0][1]} l {body}"

    tl = L(m, m, 1, 1)
    tr = L(W - m, m, -1, 1)
    bl = L(m, H - m, 1, -1)
    br = L(W - m, H - m, -1, -1)
    return f"{{\\p1\\an7\\pos(0,0)}}{tl} {tr} {bl} {br}{{\\p0}}"


def _frame_events(duration: float, kw_times: list, palette: dict) -> list[str]:
    """Neon corner brackets + progress track, plus keyword-moment flashes."""
    W, H = 720, 1280  # drawings are authored at PlayRes; cfg.width/height used below
    events: list[str] = []
    shape = _bracket_shape(W, H, inset=16, stroke=8, arm=110)

    # static neon frame, whole clip
    events.append(
        f"Dialogue: 1,0:00:00.00,{_ass_time(5400)},Frame,,0,0,0,,{shape}"
    )

    # bright flash for ~0.45 s on every keyword hit
    flash_shape = _bracket_shape(W, H, inset=12, stroke=13, arm=120)
    for t_abs, _kw in (kw_times or []):
        t = t_abs - 0.0
        if t < 0:
            continue
        end = min(t + 0.45, max(0.5, duration))
        events.append(
            f"Dialogue: 1,{_ass_time(t)},{_ass_time(end)},Flash,,0,0,0,,"
            f"{{\\fad(40,220)}}{flash_shape}"
        )
    return events


def _progress_events(duration: float, palette: dict) -> list[str]:
    """Bottom progress bar: faint track + an accent fill that grows over time."""
    events: list[str] = []
    step = 0.5
    n = max(1, int(duration / step) + 1)
    y0, y1 = 1280 - 18, 1280 - 8

    # track
    track = f"{{\\p1\\an7\\pos(0,0)}}m 0 {y0} l 720 {y0} 720 {y1} 0 {y1}{{\\p0}}"
    events.append(f"Dialogue: 1,0:00:00.00,{_ass_time(5400)},Track,,0,0,0,,{track}")

    # fill — one short event per step, width grows with t
    for i in range(n):
        t0 = i * step
        w = max(4, int(720 * min(1.0, (t0 + step) / max(1.0, duration))))
        fill = f"{{\\p1\\an7\\pos(0,0)}}m 0 {y0} l {w} {y0} {w} {y1} 0 {y1}{{\\p0}}"
        events.append(
            f"Dialogue: 1,{_ass_time(t0)},{_ass_time(t0 + step)},Bar,,0,0,0,,{fill}"
        )
    return events


def build_ass(
    words_window: list[dict],
    hook: str,
    cfg,
    out_path: Path,
    offset: float = 0.0,
    credit: str = "",
    kw_times: list | None = None,
    duration: float = 30.0,
    palette_seed: str = "",
) -> Path:
    """Write the .ass file for one clip.

    words_window: transcript words whose times are absolute (VOD time)
    offset: clip start time — event times are relative to it
    kw_times: [(abs_time, keyword)] hype hits — drive the frame flashes
    """
    palette = pick_palette(cfg.palette, palette_seed or hook)
    accent = _ass_from_hex(palette["accent"])
    accent2 = _ass_from_hex(palette["accent2"])
    glow = _ass_from_hex(palette["glow"], alpha=0x55)
    white = "&H00FFFFFF"
    black = "&H00000000"
    soft_black = "&H78000000"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {cfg.width}
PlayResY: {cfg.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CaptionA,{cfg.font},{cfg.font_size},{accent},{white},{black},{soft_black},-1,0,0,0,100,100,0,0,1,8,2,2,40,40,{cfg.caption_margin_bottom},1
Style: CaptionB,{cfg.font},{cfg.font_size},{accent2},{white},{black},{soft_black},-1,0,0,0,100,100,0,0,1,8,2,2,40,40,{cfg.caption_margin_bottom},1
Style: Hook,{cfg.font},{int(cfg.font_size * 1.5)},{white},{white},{black},{glow},-1,0,0,0,100,100,0,0,3,16,0,8,30,30,96,1
Style: Badge,{cfg.font},30,{white},{white},&H00303BFF,{soft_black},-1,0,0,0,100,100,0,0,1,9,2,7,26,26,26,1
Style: Frame,{cfg.font},40,{accent},{accent},{black},{black},-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Flash,{cfg.font},40,{white},{white},{black},{black},-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Track,{cfg.font},40,&H48FFFFFF,&H48FFFFFF,{black},{black},-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Bar,{cfg.font},40,{accent2},{accent2},{black},{black},-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    if hook:
        events.append(_hook_event(hook, cfg))
    events.append(_badge_event(credit))
    events.extend(_frame_events(duration, kw_times, palette))
    events.extend(_progress_events(duration, palette))
    caption_events = _caption_events(words_window, cfg, offset, palette)
    if caption_events:
        events.extend(caption_events)
    else:
        log.info("no words in this window — captions skipped, hook only")

    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out_path
