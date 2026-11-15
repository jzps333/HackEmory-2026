"""Builds the 2-minute Devpost video from the server recordings, the cards and the voice-over.

    /tmp/ssvenv/bin/python video/build.py            # -> video/out/toolstone-demo.mp4

Missing clips get a grey placeholder panel, so the cut can be checked before every clip exists.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
RAW, CARDS, SCREENS = HERE / "raw", HERE / "cards", HERE / "cards" / "screens"
OUT, TMP = HERE / "out", HERE / "out" / "tmp"
VO = HERE / "voiceover_final.m4a"
W, H, FPS = 1920, 1080, 30
BG = (11, 11, 13)
GREEN, GREY, WHITE = (10, 228, 72), (150, 150, 160), (245, 245, 247)
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REG = "/System/Library/Fonts/Supplemental/Arial.ttf"

# Voice-over pieces (seconds in voiceover_final.m4a) and where each starts in the video.
VO_PARTS = [(0.0, 10.5, 0.3), (10.5, 28.8, 11.3), (28.8, 38.2, 43.3), (38.2, 56.2, 55.3),
            (56.2, 60.1, 74.3), (60.1, 76.6, 88.3)]

# Four-phone row (11.0-43.0 in the video): panel, label, clip, [start, end] seconds in the clip, captions.
ROW_S = 32.0
PW, PH, PX0, PY = 450, 800, 15, 110


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=f) <= width:
            line = trial
        else:
            out.append(line)
            line = word
    return out + ([line] if line else [])


def run(cmd: list) -> None:
    subprocess.run([str(c) for c in cmd], check=True)


def ff(*args) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args])


def enc() -> list:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def clip(name: str) -> Path | None:
    p = RAW / f"{name}.mp4"
    return p if p.exists() else None


def placeholder(path: Path, w: int, h: int, secs: float, text: str) -> Path:
    img = Image.new("RGB", (w, h), (40, 40, 46))
    d = ImageDraw.Draw(img)
    d.text((w // 2, h // 2), text, font=font(BOLD, 30), fill=GREY, anchor="mm")
    png = path.with_suffix(".png")
    img.save(png)
    ff("-loop", "1", "-i", png, "-t", f"{secs}", "-vf", f"fps={FPS}", *enc(), path)
    return path


def piece(name: str, a: float, b: float, secs: float, out: Path, label: str) -> Path:
    """Clip ``name`` from a to b seconds, sped to last ``secs``, scaled to the phone panel."""
    src = clip(name)
    if src is None:
        return placeholder(out, PW, PH, secs, label)
    speed = (b - a) / secs
    ff("-ss", f"{a}", "-t", f"{b - a}", "-i", src,
       "-vf", f"setpts=PTS/{speed:.4f},fps={FPS},scale={PW}:{PH},setsar=1", "-t", f"{secs}", "-an", *enc(), out)
    return out


def scroll(png: Path, secs: float, out: Path, w: int = PW, h: int = PH, top: float = 0.0,
           end: float = 1.0, column: tuple[int, int] | None = None) -> Path:
    """Scroll a tall screenshot from ``top`` to ``end`` (fractions of the scrollable height) in a
    w x h window; ``column`` (x, width) crops to the page's content column first."""
    pre = f"crop={column[1]}:ih:{column[0]}:0," if column else ""
    ff("-loop", "1", "-i", png, "-t", f"{secs}",
       "-vf", f"{pre}scale={w}:-2,crop={w}:{h}:0:'(ih-{h})*({top}+({end}-{top})*min(t/{secs},1))',fps={FPS},setsar=1",
       *enc(), out)
    return out


def concat(parts: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)
    return out


# --- overlays ---------------------------------------------------------------------------------------

def row_overlay(labels: list[tuple[str, bool]], captions: list[str], path: Path) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fl, fc = font(BOLD, 30), font(BOLD, 30)
    for i, ((label, on), cap) in enumerate(zip(labels, captions)):
        x = PX0 + i * 480
        d.rounded_rectangle((x, 30, x + PW, 90), 14, fill=(GREEN if on else (60, 60, 68)))
        d.text((x + PW // 2, 60), label, font=fl, fill=((0, 0, 0) if on else WHITE), anchor="mm")
        y = PY + PH + 18
        for line in wrap(d, cap, fc, PW - 10)[:4]:
            d.text((x + PW // 2, y), line, font=fc, fill=WHITE, anchor="ma")
            y += 38
    img.save(path)
    return path


def caption_overlay(text: str, path: Path, sub: str = "") -> Path:
    """A bottom caption bar for full-screen sections."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f, fs = font(BOLD, 46), font(REG, 34)
    tw = max(d.textlength(text, font=f), d.textlength(sub, font=fs) if sub else 0)
    h = 140 if sub else 84
    top = H - h - 50
    d.rounded_rectangle((W / 2 - tw / 2 - 40, top, W / 2 + tw / 2 + 40, H - 50), 22, fill=(0, 0, 0, 215))
    d.text((W / 2, top + 46), text, font=f, fill=WHITE, anchor="mm")
    if sub:
        d.text((W / 2, top + 104), sub, font=fs, fill=GREEN, anchor="mm")
    img.save(path)
    return path


def with_overlays(base: Path, overlays: list[tuple[Path, float, float]], out: Path) -> Path:
    args, chain, last = ["-i", base], [], "0:v"
    for i, (png, a, b) in enumerate(overlays, 1):
        args += ["-i", png]
        tag = f"o{i}"
        chain.append(f"[{last}][{i}:v]overlay=0:0:enable='between(t,{a},{b})'[{tag}]")
        last = tag
    ff(*args, "-filter_complex", ";".join(chain), "-map", f"[{last}]", *enc(), out)
    return out


def still(png: Path, secs: float, out: Path) -> Path:
    ff("-loop", "1", "-i", png, "-t", f"{secs}",
       "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:0:0,fps={FPS},setsar=1",
       *enc(), out)
    return out


# --- sections ---------------------------------------------------------------------------------------

def intro() -> Path:                                   # 0-11
    a = still(CARDS / "title.png", 4.0, TMP / "intro-a.mp4")
    b = still(SCREENS / "community-plugins.png", 7.0, TMP / "intro-b.mp4")
    bb = with_overlays(b, [(caption_overlay("Community plugins, inside the Chert console", TMP / "cap-intro.png",
                                            "anyone can build a skill · every Chert agent can use it"), 0, 7)],
                       TMP / "intro-b2.mp4")
    return concat([a, bb], TMP / "s1.mp4")


def call_ended(secs: float, out: Path) -> Path:
    """The no-skill phone after the person gives up: the call is over."""
    img = Image.new("RGB", (PW, PH), (20, 20, 24))
    d = ImageDraw.Draw(img)
    cx, cy = PW // 2, 300
    d.ellipse((cx - 70, cy - 70, cx + 70, cy + 70), fill=(220, 38, 38))
    d.rounded_rectangle((cx - 44, cy - 12, cx + 44, cy + 12), 12, fill=WHITE)      # handset, face down
    d.rounded_rectangle((cx - 50, cy - 4, cx - 26, cy + 26), 8, fill=WHITE)
    d.rounded_rectangle((cx + 26, cy - 4, cx + 50, cy + 26), 8, fill=WHITE)
    d.text((cx, 440), "Call ended", font=font(BOLD, 48), fill=WHITE, anchor="mm")
    d.text((cx, 500), "It couldn\u2019t help", font=font(REG, 32), fill=GREY, anchor="mm")
    png = out.with_suffix(".png")
    img.save(png)
    ff("-loop", "1", "-i", png, "-t", f"{secs}", "-vf", f"fps={FPS},setsar=1", *enc(), out)
    return out


def row() -> Path:                                     # 11-43
    give_up = 14.0                                     # the no-skill phones end the call here
    p1 = concat([piece("01-tutor-off", 40.0, 70.0, give_up, TMP / "p1a.mp4", "Tutor · out of the box"),
                 call_ended(ROW_S - give_up, TMP / "p1b.mp4")], TMP / "p1.mp4")
    p2 = piece("02-tutor-on", 38.0, 100.0, ROW_S, TMP / "p2.mp4", "Tutor · with skill")
    p3 = concat([piece("03-research-off", 30.0, 48.0, give_up, TMP / "p3a.mp4", "Research · out of the box"),
                 call_ended(ROW_S - give_up, TMP / "p3b.mp4")], TMP / "p3.mp4")
    r1 = piece("04a-research-on", 30.0, 43.0, 11.0, TMP / "p4a.mp4", "Research · asks")
    col = (570, 777)                                   # the report's content column in the screenshot
    r2a = scroll(SCREENS / "research-report.png", 3.0, TMP / "p4b1.mp4", top=0.0, end=0.02, column=col)
    r2b = scroll(SCREENS / "research-report.png", 6.0, TMP / "p4b2.mp4", top=0.80, end=1.0, column=col)
    r3 = piece("04c-research-callback", 25.0, 104.0, ROW_S - 20.0, TMP / "p4c.mp4", "Research · calls back")
    p4 = concat([r1, r2a, r2b, r3], TMP / "p4.mp4")
    base = TMP / "row-base.mp4"
    ff("-f", "lavfi", "-i", f"color=c=0x0b0b0d:s={W}x{H}:d={ROW_S}:r={FPS}",
       "-i", p1, "-i", p2, "-i", p3, "-i", p4,
       "-filter_complex",
       ";".join([f"[0:v][1:v]overlay={PX0}:{PY}[a]", f"[a][2:v]overlay={PX0 + 480}:{PY}[b]",
                 f"[b][3:v]overlay={PX0 + 960}:{PY}[c]", f"[c][4:v]overlay={PX0 + 1440}:{PY}:shortest=1[v]"]),
       "-map", "[v]", "-t", f"{ROW_S}", *enc(), base)
    labels = [("TUTOR \u00b7 NO SKILL", False), ("TUTOR \u00b7 WITH SKILL", True),
              ("RESEARCH \u00b7 NO SKILL", False), ("RESEARCH \u00b7 WITH SKILL", True)]
    panels = [
        [(0, 6, "Asks: teach me what a derivative is"),
         (6, give_up, "\u201cI can\u2019t write or display equations on this call.\u201d"),
         (give_up, ROW_S, "Nothing more it can do: you hang up")],
        [(0, 11, "Handwrites each step on your screen (2x)"),
         (11, 20, "Checks in, then draws the graph when you ask"),
         (20, ROW_S, "Step 3: for x\u00b2, the derivative is 2x")],
        [(0, 6, "Asks it to research Adderall and dopamine"),
         (6, give_up, "\u201cI don\u2019t have the ability to look things up online.\u201d"),
         (give_up, ROW_S, "Nothing more it can do: you hang up")],
        [(0, 11, "Starts the research, then hangs up by itself"),
         (11, 20, "5 min later: a report citing 30 published studies"),
         (20, ROW_S, "Then calls you back to walk you through it")],
    ]
    cuts = sorted({t for pan in panels for (x, y, _) in pan for t in (x, y)})
    ovs = []
    for i, (x, y) in enumerate(zip(cuts, cuts[1:])):
        caps = [next(c for (ca, cb, c) in pan if ca <= x < cb) for pan in panels]
        ovs.append((row_overlay(labels, caps, TMP / f"row-{i}.png"), x, y))
    return with_overlays(base, ovs, TMP / "s2.mp4")


def scansafe() -> Path:                                # 43-55
    secs = 12.0
    src = clip("05-scansafe")
    phone = TMP / "s3-phone.mp4"
    if src is None:
        placeholder(phone, 608, 1080, secs, "ScanSafe clip (recording)")
    else:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(src)], capture_output=True, text=True).stdout)
        a, b = 30.0, min(dur, 62.0)                # live sandbox view -> checklist -> "Don't pay this"
        ff("-ss", f"{a}", "-t", f"{b - a}", "-i", src,
           "-vf", f"setpts=PTS/{(b - a) / secs:.4f},fps={FPS},scale=608:1080,setsar=1",
           "-t", f"{secs}", "-an", *enc(), phone)
    base = TMP / "s3-base.mp4"
    ff("-f", "lavfi", "-i", f"color=c=0x0b0b0d:s={W}x{H}:d={secs}:r={FPS}", "-i", phone,
       "-filter_complex", f"[0:v][1:v]overlay={(W - 608) // 2}:0:shortest=1[v]", "-map", "[v]", *enc(), base)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((300, 160), "SECURITY · SCANSAFE", font=font(BOLD, 34), fill=GREEN, anchor="mm")
    for i, line in enumerate(["Hold up a QR code", "on a FaceTime call"]):
        d.text((300, 300 + i * 64), line, font=font(BOLD, 52), fill=WHITE, anchor="mm")
    for i, line in enumerate(["It opens the link in a", "throwaway, locked-down", "browser on a Vultr VM"]):
        d.text((W - 300, 300 + i * 60), line, font=font(BOLD, 46), fill=WHITE, anchor="mm")
    d.text((W - 300, 560), "The scam never touches your phone", font=font(REG, 32), fill=GREEN, anchor="mm")
    side = TMP / "s3-side.png"
    img.save(side)
    return with_overlays(base, [(side, 0, secs)], TMP / "s3.mp4")


def open_source() -> Path:                             # 63-82
    a = still(SCREENS / "github-verified.png", 6.0, TMP / "s4-a.mp4")
    a2 = with_overlays(a, [(caption_overlay("A skill is a short recipe in a public GitHub repo", TMP / "cap-s4a.png",
                                            "instructions + a list of allowed tools · send a pull request"), 0, 6)],
                       TMP / "s4-a2.mp4")
    b = still(SCREENS / "community-plugins.png", 5.0, TMP / "s4-b.mp4")
    b2 = with_overlays(b, [(caption_overlay("It shows up on the Community plugins page", TMP / "cap-s4b.png",
                                            "searchable with Typesense"), 0, 5)], TMP / "s4-b2.mp4")
    c = still(CARDS / "hood-typesense.png", 3.0, TMP / "s4-c.mp4")
    e = still(SCREENS / "github-verified.png", 5.0, TMP / "s4-e.mp4")
    e2 = with_overlays(e, [(caption_overlay("Verified by SHA-256 fingerprint", TMP / "cap-s4e.png",
                                            "edit it and it’s unverified · unverified skills can’t touch money, research or your computer"),
                            0, 5)], TMP / "s4-e2.mp4")
    return concat([a2, b2, c, e2], TMP / "s4.mp4")


MONO = "/System/Library/Fonts/Menlo.ttc"
FLOW = ["FaceTime call \u00b7 Chert", "Agent on Vultr \u00b7 Gemini Live", "Research skill \u00b7 verified on GitHub",
        "Gemini + Google + OpenAlex studies", "Tiger Data \u00b7 every step, every report",
        "Typesense \u00b7 search past reports", "Text + FaceTime call back"]


def tiger() -> Path:                                   # 74-88: how the Research skill works, from Tiger
    import datetime
    import json
    job = json.loads((RAW / "tiger-job.json").read_text())
    steps = [p for p in job["progress"] if "call back" not in p["note"].lower()]
    keep, searched = [], 0
    for p in steps:                                    # every round, a couple of searches each, the report
        n = p["note"]
        if n.startswith("Searched:"):
            searched += 1
            if searched % 5 != 1:
                continue
        elif n.startswith("Searched"):
            continue
        keep.append(p)
    secs, fps = 14.0, 15
    reveal = 10.5                                      # all lines are in by then
    fr = TMP / "tiger"
    fr.mkdir(exist_ok=True)
    f_small, f_title, f_mono, f_monob = font(BOLD, 28), font(BOLD, 58), ImageFont.truetype(MONO, 25), \
        ImageFont.truetype(MONO, 25, index=1)
    f_flow, f_cap = font(BOLD, 28), font(REG, 30)
    first_search = next(i for i, p in enumerate(keep) if p["note"].startswith("Searched"))
    for k in range(int(secs * fps)):
        t = k / fps
        shown = min(len(keep), int(t / reveal * len(keep)) + 1)
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.text((60, 52), "UNDER THE HOOD \u00b7 HOW THE RESEARCH SKILL WORKS", font=f_small, fill=GREEN)
        d.text((60, 92), "Every step is written to Tiger Data, live", font=f_title, fill=WHITE)
        x0, y0, x1, y1 = 60, 190, 1200, 990
        d.rounded_rectangle((x0, y0, x1, y1), 18, fill=(17, 17, 19), outline=(39, 39, 42), width=2)
        d.text((x0 + 24, y0 + 18), f"tiger data \u00b7 research_jobs \u00b7 job {job['job_id']}", font=f_monob,
               fill=GREEN)
        d.text((x0 + 24, y0 + 58), "> SELECT at, note FROM research_jobs, jsonb_array_elements(progress)",
               font=f_mono, fill=GREY)
        y = y0 + 110
        for p in keep[:shown]:
            at = datetime.datetime.fromtimestamp(p["at"], datetime.timezone.utc).strftime("%H:%M:%S")
            note = p["note"] if len(p["note"]) <= 60 else p["note"][:58] + "\u2026"
            color = GREEN if p["note"].startswith(("Report ready", "That covers", "Writing the report")) else WHITE
            d.text((x0 + 24, y), at, font=f_mono, fill=GREY)
            d.text((x0 + 170, y), note, font=f_mono, fill=color)
            y += 40
        lit = 3 + (1 if shown > first_search else 0) + (1 if shown >= 1 else 0)
        if shown == len(keep):
            lit = len(FLOW)
        bx0, bx1, by, bh, gap = 1260, 1860, 190, 92, 22
        for i, name in enumerate(FLOW):
            on = i < lit if i != 4 else shown >= 1
            if i == 3:
                on = shown > first_search
            top = by + i * (bh + gap)
            d.rounded_rectangle((bx0, top, bx1, top + bh), 16, fill=((10, 60, 28) if on else (24, 24, 28)),
                                outline=(GREEN if on else (60, 60, 68)), width=3)
            d.text(((bx0 + bx1) // 2, top + bh // 2), name, font=f_flow, fill=(WHITE if on else GREY), anchor="mm")
            if i < len(FLOW) - 1:
                d.line(((bx0 + bx1) // 2, top + bh, (bx0 + bx1) // 2, top + bh + gap), fill=(60, 60, 68), width=3)
        d.text((W // 2, 1040), "Real log of the Adderall research above \u00b7 4 rounds \u00b7 20 searches \u00b7 "
                               "216 sources \u00b7 report in 5 minutes (sped up)", font=f_cap, fill=GREY, anchor="mm")
        img.save(fr / f"f{k:04d}.png")
    out = TMP / "s5a.mp4"
    ff("-framerate", str(fps), "-i", fr / "f%04d.png", "-vf", f"fps={FPS},setsar=1", *enc(), out)
    return out


def hood() -> Path:                                    # 88-102.1, then the end card
    order = [("hood-gemini", 3.5), ("hood-vultr", 2.0), ("hood-coder", 2.0), ("hood-solana", 4.0),
             ("solana-tx", 2.6)]
    parts = []
    for name, secs in order:
        png = CARDS / f"{name}.png" if (CARDS / f"{name}.png").exists() else SCREENS / f"{name}.png"
        parts.append(still(png, secs, TMP / f"s5-{name}.mp4"))
    parts.append(still(CARDS / "end.png", 6.0, TMP / "s5-end.mp4"))
    return concat(parts, TMP / "s5.mp4")


def main() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    video = concat([intro(), row(), scansafe(), open_source(), tiger(), hood()], TMP / "video.mp4")
    inputs, chains, labels = ["-i", video], [], []
    for i, (a, b, at) in enumerate(VO_PARTS):
        inputs += ["-i", VO]
        ms = int(at * 1000)
        chains.append(f"[{i + 1}:a]atrim={a}:{b},asetpts=PTS-STARTPTS,adelay={ms}|{ms}[v{i}]")
        labels.append(f"[v{i}]")
    chains.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0[a]")
    OUT.mkdir(exist_ok=True)
    out = OUT / "toolstone-demo.mp4"
    ff(*inputs, "-filter_complex", ";".join(chains), "-map", "0:v", "-map", "[a]", "-c:v", "copy",
       "-c:a", "aac", "-b:a", "192k", out)
    print(out)


if __name__ == "__main__":
    main()
