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
VO_PARTS = [(0.0, 10.5, 0.3), (10.5, 28.8, 11.3), (28.8, 38.2, 43.3), (38.2, 56.2, 63.3), (56.2, 76.6, 82.3)]

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


def row() -> Path:                                     # 11-43
    p1 = piece("01-tutor-off", 36.0, 80.0, ROW_S, TMP / "p1.mp4", "Tutor · out of the box")
    p2 = piece("02-tutor-on", 38.0, 100.0, ROW_S, TMP / "p2.mp4", "Tutor · with skill")
    p3 = piece("03-research-off", 30.0, 50.0, ROW_S, TMP / "p3.mp4", "Research · out of the box")
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
    labels = [("TUTOR · NO SKILL", False), ("TUTOR · WITH SKILL", True),
              ("RESEARCH · NO SKILL", False), ("RESEARCH · WITH SKILL", True)]
    phases = [
        (0, 11, ["Asks: teach me what a derivative is", "Handwrites each step on your screen (2x)",
                 "Asks it to research Adderall and dopamine", "Starts the research, then hangs up by itself"]),
        (11, 20, ["“I can’t write or display equations on this call.”", "Checks in, then draws the graph when you ask",
                  "“I don’t have the ability to look things up online.”",
                  "4 min later: a report citing published studies"]),
        (20, ROW_S, ["Just talks", "Step 3: for x², the derivative is 2x", "Can’t research",
                     "Then calls you back to walk you through it"]),
    ]
    ovs = [(row_overlay(labels, caps, TMP / f"row-{i}.png"), a, b) for i, (a, b, caps) in enumerate(phases)]
    return with_overlays(base, ovs, TMP / "s2.mp4")


def scansafe() -> Path:                                # 43-63
    secs = 20.0
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


def hood() -> Path:                                    # 82-100.3, then the end card
    order = [("hood-tiger", 3.9), ("hood-gemini", 3.5), ("hood-vultr", 2.0), ("hood-coder", 2.0),
             ("hood-solana", 4.0), ("solana-tx", 2.6)]
    parts = []
    for name, secs in order:
        png = CARDS / f"{name}.png" if (CARDS / f"{name}.png").exists() else SCREENS / f"{name}.png"
        parts.append(still(png, secs, TMP / f"s5-{name}.mp4"))
    parts.append(still(CARDS / "end.png", 5.7, TMP / "s5-end.mp4"))
    return concat(parts, TMP / "s5.mp4")


def main() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    video = concat([intro(), row(), scansafe(), open_source(), hood()], TMP / "video.mp4")
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
