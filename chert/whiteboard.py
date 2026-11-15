"""Tutor's whiteboard: lesson notes written step by step on the agent's FaceTime video.

chert/status_video.py shows a Whiteboard in its "whiteboard" state; the Tutor plugin's tools in
chert/agent_integration.py fill it (whiteboard_title, write_step, write_note, clear_whiteboard).
Portrait 720x1280 like every other screen: a warm graph-paper notebook page with a title, then
numbered steps. The newest step (or side note) writes itself over 1.5-2 s with a pencil at the
tip; earlier steps stay above it, and when the page is full the oldest scroll off the top (at most
VISIBLE_STEPS stay, under an "… N earlier steps" line). The step being explained is highlighted.
Side notes are yellow sticky notes under their step.

Every word on it is the model's, so it is cleaned first (clean(): no control characters, no angle
brackets, clipped) and only ever drawn as text. ASCII math the model may still send ("x^2",
"sqrt(x)", "<=", "->", "\\pi") becomes the Unicode it means. The font is DejaVu Sans (good Unicode
math coverage: x², √, ∫, π, ≤, →), with fallbacks.

Cheap on a 2-vCPU box: the page is drawn once per change. While something is being written each
frame is a copy of that page with the new block's ink pasted through a moving mask; once written,
key() stops changing and StatusVideo serves the cached frame.
No LiveKit imports here (unit-testable).
"""
from __future__ import annotations

import itertools
import math
import os
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageFont

W, H = 720, 1280
TITLE_CHARS, STEP_CHARS, NOTE_CHARS = 60, 140, 160
MAX_STEPS = 40                # kept per page (step numbers keep counting past it)
NOTES_PER_STEP = 2            # the newest are kept
VISIBLE_STEPS = 6             # at most this many steps on the page; older ones scroll off the top
WRITE_MIN_S, WRITE_MAX_S, WRITE_CHAR_S = 1.5, 2.0, 0.014
KEY_HZ = 20                   # key() changes this often while writing (the video runs at 10 fps)

# DejaVu Sans on the Ubuntu servers; WHITEBOARD_FONT_DIR to point elsewhere; Arial Unicode on a Mac.
FONT_DIRS = tuple(d for d in (os.getenv("WHITEBOARD_FONT_DIR"), "/usr/share/fonts/truetype/dejavu/") if d)
FALLBACK_FONTS = ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf")

PAPER, GRID, RULE = (251, 248, 240), (229, 233, 240), (191, 212, 246)
MARGIN = (239, 160, 160)
INK, INK_DONE, DIM = (17, 24, 39), (71, 85, 105), (140, 152, 170)
ACCENT, CURRENT = (37, 99, 235), (221, 234, 254)
STICKY, STICKY_FOLD, STICKY_SHADOW = (254, 240, 138), (234, 206, 84), (224, 218, 200)
STICKY_INK, STICKY_LABEL = (55, 45, 15), (161, 98, 7)
WHITE = (255, 255, 255)

MARGIN_X = 92                 # the red margin line; step numbers sit left of it
NUM_X = 46
TEXT_X, TEXT_R = 120, W - 34  # step text column
NOTE_X0, NOTE_X1 = TEXT_X - 6, W - 28
NOTE_TEXT_X = NOTE_X0 + 18
NOTE_TEXT_W = NOTE_X1 - 18 - NOTE_TEXT_X
NOTE_LABEL = "Note:"
BOTTOM = H - 96               # steps never go below this (the hint sits under it)
STEP_GAP, NOTE_GAP, MORE_H = 18, 10, 46
EDGE = 22                     # soft edge of the ink being written, in px


@dataclass(frozen=True)
class _Style:
    size: int
    line: int
    pad_t: int
    pad_b: int
    lines: int


CUR = _Style(36, 48, 12, 14, 6)          # the step being explained
DONE = _Style(30, 40, 6, 6, 3)           # steps above it (2 lines when the page is full)
NOTE_CUR = _Style(28, 36, 14, 16, 5)
NOTE_DONE = _Style(26, 34, 10, 12, 2)


@lru_cache(maxsize=32)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in [os.path.join(d, name) for d in FONT_DIRS] + list(FALLBACK_FONTS):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


# --- text --------------------------------------------------------------------------------------

_SUP = str.maketrans("0123456789+-=()nix", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣ")
_SUP_OK = frozenset("0123456789+-=()nix")
_SUP_GROUP = re.compile(r"\^[({]([^(){}]{1,12})[)}]")          # x^(n-1), x^{2}
_SUP_ONE = re.compile(r"\^(-?[0-9]{1,4}|[nix](?![A-Za-z]))")   # x^2, x^-1, x^n
_TEX_SPAN = re.compile(r"\$([^$]{1,80})\$")                     # $x^2$ (but not "$5 or $10")
_FRAC = re.compile(r"\\frac\s*\{([^{}]{1,40})\}\s*\{([^{}]{1,40})\}")
_CMD = re.compile(r"\\([A-Za-z]+)")
_LATEX = {"pi": "π", "theta": "θ", "alpha": "α", "beta": "β", "lambda": "λ", "mu": "μ",
          "sigma": "σ", "delta": "δ", "Delta": "Δ", "infty": "∞", "int": "∫", "sum": "∑",
          "sqrt": "√", "cdot": "·", "times": "×", "div": "÷", "le": "≤", "leq": "≤", "ge": "≥",
          "geq": "≥", "ne": "≠", "neq": "≠", "to": "→", "rightarrow": "→", "Rightarrow": "⇒",
          "approx": "≈", "pm": "±", "partial": "∂", "left": "", "right": ""}
_DIGRAPHS = (("<=>", "⇔"), ("<->", "↔"), ("+/-", "±"), ("<=", "≤"), (">=", "≥"), ("!=", "≠"),
             ("=>", "⇒"), ("->", "→"), ("+-", "±"), ("~=", "≈"))


def _sup(m: re.Match) -> str:
    s = m.group(1).replace(" ", "")
    return s.translate(_SUP) if s and set(s) <= _SUP_OK else m.group(0)


def clean(text, n: int) -> str:
    """Model text for the board: one line, no control or format characters, no angle brackets
    (‹ ›, as everywhere else in chert/plugins.py), ASCII math turned into Unicode, at most ``n``
    characters."""
    if not isinstance(text, str):
        return ""
    t = unicodedata.normalize("NFC", text)
    t = "".join(" " if ch.isspace() else ch for ch in t
                if ch.isspace() or not unicodedata.category(ch).startswith("C"))
    t = _TEX_SPAN.sub(lambda m: m.group(1) if re.search(r"[\\^_{}]", m.group(1)) else m.group(0), t)
    t = _FRAC.sub(r"(\1)/(\2)", t)
    t = _CMD.sub(lambda m: _LATEX.get(m.group(1), m.group(1)), t)
    t = _SUP_ONE.sub(_sup, _SUP_GROUP.sub(_sup, t))
    t = re.sub(r"\bsqrt\s*", "√", t, flags=re.IGNORECASE)
    t = re.sub(r"√\{([^{}]{1,40})\}", r"√(\1)", t)
    for a, b in _DIGRAPHS:
        t = t.replace(a, b)
    t = t.replace("**", "").replace("`", "").replace("*", "·")
    t = " ".join(t.replace("<", "‹").replace(">", "›").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _fit(text: str, fnt, max_w: float) -> str:
    if fnt.getlength(text) <= max_w:
        return text
    while text and fnt.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(text: str, fnt, width: float, max_lines: int, first_width: Optional[float] = None) -> list[str]:
    """Word-wrap into at most ``max_lines`` lines (the last gets an ellipsis if it overflows).
    A word wider than a line (a long formula) is broken between characters. ``first_width``: a
    narrower first line (the sticky note's "Note:" label sits in front of it)."""
    out: list[str] = []
    tokens = text.split()
    cur = ""

    def limit() -> float:
        return first_width if first_width is not None and not out else width
    while tokens:
        word = tokens.pop(0)
        trial = f"{cur} {word}" if cur else word
        if fnt.getlength(trial) <= limit():
            cur = trial
        elif cur:
            out.append(cur)
            cur = ""
            tokens.insert(0, word)
        else:
            k = len(word)
            while k > 1 and fnt.getlength(word[:k]) > limit():
                k -= 1
            out.append(word[:k])
            tokens.insert(0, word[k:])
    if cur:
        out.append(cur)
    if len(out) > max_lines:
        rest = " ".join(out[max_lines - 1:])
        out = out[: max_lines - 1]
        out.append(_fit(rest, fnt, limit()))
    return out


# --- the page ----------------------------------------------------------------------------------

_versions = itertools.count(1)       # unique across boards, so a new board never reuses a frame


@dataclass(frozen=True)
class Step:
    n: int
    text: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Page:
    """One immutable snapshot: tools swap in a new one, the render thread reads one."""
    title: str = ""
    steps: tuple[Step, ...] = ()
    writing: Optional[tuple[int, int]] = None   # (step n, note index or -1): what writes itself
    started: float = 0.0
    write_s: float = 0.0
    version: int = 0


@dataclass
class _Block:
    kind: str                 # "step" | "note"
    n: int                    # step number
    lines: list[str]
    style: _Style
    current: bool = False
    indent: int = 0           # first line starts this far right (the note label)
    writing: bool = False
    y: int = 0

    @property
    def h(self) -> int:
        return self.style.pad_t + len(self.lines) * self.style.line + self.style.pad_b

    @property
    def x(self) -> int:
        return NOTE_TEXT_X if self.kind == "note" else TEXT_X


def _write_s(text: str) -> float:
    return min(WRITE_MAX_S, max(WRITE_MIN_S, len(text) * WRITE_CHAR_S))


class Whiteboard:
    def __init__(self, title: str = "") -> None:
        self.page = Page(title=clean(title, TITLE_CHARS), version=next(_versions))
        self._cache: Optional[tuple] = None   # (version, page without the ink, page done, ink)

    # --- changes (the agent's tools) -------------------------------------------------------------

    @property
    def title(self) -> str:
        return self.page.title

    @property
    def steps(self) -> tuple[Step, ...]:
        return self.page.steps

    def set_title(self, title: str) -> None:
        """A fresh page with this title (no steps)."""
        self.page = Page(title=clean(title, TITLE_CHARS), version=next(_versions))

    def clear(self) -> None:
        """Back to an empty page; the title stays."""
        self.set_title(self.page.title)

    def add_step(self, text: str, now: Optional[float] = None) -> Optional[int]:
        """Append a numbered step and start writing it. Its number, or None for empty text."""
        t = clean(text, STEP_CHARS)
        if not t:
            return None
        p = self.page
        n = p.steps[-1].n + 1 if p.steps else 1
        self.page = replace(p, steps=(p.steps + (Step(n, t),))[-MAX_STEPS:], writing=(n, -1),
                            started=time.monotonic() if now is None else now,
                            write_s=_write_s(t), version=next(_versions))
        return n

    def add_note(self, text: str, now: Optional[float] = None) -> Optional[int]:
        """A side note on the current (newest) step; it writes itself too. The step's number, or
        None when there's no step yet or the text is empty."""
        t = clean(text, NOTE_CHARS)
        p = self.page
        if not t or not p.steps:
            return None
        last = p.steps[-1]
        notes = (last.notes + (t,))[-NOTES_PER_STEP:]
        self.page = replace(p, steps=p.steps[:-1] + (replace(last, notes=notes),),
                            writing=(last.n, len(notes) - 1),
                            started=time.monotonic() if now is None else now,
                            write_s=_write_s(t), version=next(_versions))
        return last.n

    # --- drawing -------------------------------------------------------------------------------

    def _progress(self, p: Page, now: float) -> float:
        """0..1 while something is being written, -1 when the page is still."""
        if p.writing is None or p.write_s <= 0:
            return -1.0
        t = now - p.started
        return t / p.write_s if 0 <= t < p.write_s else -1.0

    def writing(self, now: float) -> bool:
        return self._progress(self.page, now) >= 0

    def key(self, now: float) -> tuple:
        """Same key, same picture: changes KEY_HZ times a second while writing, else only when
        the page changes."""
        p = self.page
        prog = self._progress(p, now)
        return (p.version, int((now - p.started) * KEY_HZ) if prog >= 0 else -1)

    def frame(self, now: float) -> Image.Image:
        """The page as an RGB image (a fresh copy: the caller may draw on it)."""
        p = self.page                                # read once: a tool may swap it meanwhile
        c = self._cache
        if c is None or c[0] != p.version:
            c = (p.version, *_build(p))
            self._cache = c
        _, still, done, ink = c
        prog = self._progress(p, now)
        if prog < 0 or ink is None:
            return done.copy()
        img = still.copy()
        _paste_ink(img, ink, prog)
        return img


def _header(d: ImageDraw.ImageDraw, p: Page) -> int:
    """Label, step count, title and its underline. Returns where the notes start."""
    lab = font(24, True)
    x = 40
    for ch in "TUTOR":                               # a little letter spacing
        d.text((x, 38), ch, font=lab, fill=ACCENT)
        x += int(lab.getlength(ch)) + 4
    if p.steps:
        d.text((W - 40, 38), f"Step {p.steps[-1].n}", font=lab, fill=DIM, anchor="ra")
    ft = font(50, True)
    lines = wrap(p.title or "Notes", ft, W - 80, 2)
    y = 84
    for line in lines:
        d.text((40, y), line, font=ft, fill=INK)
        y += 62
    width = max(ft.getlength(line) for line in lines)
    d.rounded_rectangle((40, y + 4, 40 + int(min(width, W - 80)), y + 11), 4, fill=ACCENT)
    return y + 40


def _paper(img: Image.Image, top: int) -> None:
    d = ImageDraw.Draw(img)
    for y in range(top, H, 24):
        d.line((0, y, W, y), fill=GRID, width=1)
    for x in range(MARGIN_X % 24, W, 24):
        d.line((x, top, x, H), fill=GRID, width=1)
    d.line((0, top, W, top), fill=RULE, width=3)
    d.line((MARGIN_X, top, MARGIN_X, H), fill=MARGIN, width=3)


def _blocks(step: Step, current: bool, writing: Optional[tuple[int, int]], done_lines: int) -> list[_Block]:
    st = CUR if current else replace(DONE, lines=done_lines)
    out = [_Block("step", step.n, wrap(step.text, font(st.size), TEXT_R - TEXT_X, st.lines), st,
                  current, 0, writing == (step.n, -1))]
    ns = NOTE_CUR if current else NOTE_DONE
    indent = int(font(ns.size - 2, True).getlength(NOTE_LABEL)) + 10
    for i, note in enumerate(step.notes):
        lines = wrap(note, font(ns.size), NOTE_TEXT_W, ns.lines, first_width=NOTE_TEXT_W - indent)
        out.append(_Block("note", step.n, lines, ns, current, indent, writing == (step.n, i)))
    return out


def _group_h(group: list[_Block]) -> int:
    return sum(b.h + (NOTE_GAP if b.kind == "note" else 0) for b in group)


def layout(p: Page, top: int) -> tuple[list[_Block], int]:
    """The blocks that fit between ``top`` and BOTTOM, placed (newest last), and how many earlier
    steps scrolled off the top."""
    steps = p.steps
    shown = list(steps[-VISIBLE_STEPS:])
    while True:
        hidden = len(steps) - len(shown)
        for done_lines in (DONE.lines, 2):          # earlier steps get 3 lines while there's room
            groups = [_blocks(s, s.n == steps[-1].n, p.writing, done_lines) for s in shown]
            need = (sum(_group_h(g) for g in groups) + STEP_GAP * max(0, len(groups) - 1)
                    + (MORE_H if hidden else 0))
            if need <= BOTTOM - top:
                break
        if need <= BOTTOM - top or len(shown) <= 1:
            break
        shown.pop(0)
    y, out = top, []
    if hidden:
        y += MORE_H
    for g in groups:
        for b in g:
            if b.kind == "note":
                y += NOTE_GAP
            b.y = y
            y += b.h
            out.append(b)
        y += STEP_GAP
    return out, hidden


def _line_y(b: _Block, i: int) -> int:
    """Vertical middle of line ``i`` of a block."""
    return b.y + b.style.pad_t + i * b.style.line + b.style.line // 2


def _draw_block(img: Image.Image, d: ImageDraw.ImageDraw, b: _Block) -> None:
    """The block's chrome (band, number, sticky note) and, unless it is being written, its text."""
    st = b.style
    if b.kind == "step":
        cy = _line_y(b, 0)
        if b.current:
            d.rounded_rectangle((MARGIN_X + 10, b.y, W - 18, b.y + b.h), 18, fill=CURRENT)
            d.ellipse((NUM_X - 24, cy - 24, NUM_X + 24, cy + 24), fill=ACCENT)
            d.text((NUM_X, cy), str(b.n), font=font(26 if b.n < 100 else 18, True), fill=WHITE, anchor="mm")
        else:
            d.ellipse((NUM_X - 20, cy - 20, NUM_X + 20, cy + 20), outline=DIM, width=3, fill=PAPER)
            d.text((NUM_X, cy), str(b.n), font=font(22 if b.n < 100 else 16, True), fill=INK_DONE, anchor="mm")
        color = INK if b.current else INK_DONE
    else:
        x0, y0, x1, y1 = NOTE_X0, b.y, NOTE_X1, b.y + b.h
        fold = 24 if b.current else 18
        d.rectangle((x0 + 5, y0 + 6, x1 + 5, y1 + 6), fill=STICKY_SHADOW)
        d.polygon([(x0, y0), (x1, y0), (x1, y1 - fold), (x1 - fold, y1), (x0, y1)], fill=STICKY)
        d.polygon([(x1, y1 - fold), (x1 - fold, y1 - fold), (x1 - fold, y1)], fill=STICKY_FOLD)
        d.text((NOTE_TEXT_X, _line_y(b, 0)), NOTE_LABEL, font=font(st.size - 2, True),
               fill=STICKY_LABEL, anchor="lm")
        color = STICKY_INK
    if not b.writing:
        f = font(st.size)
        for i, line in enumerate(b.lines):
            d.text((b.x + (b.indent if i == 0 else 0), _line_y(b, i)), line, font=f, fill=color, anchor="lm")


def _ink(b: _Block) -> tuple:
    """The text of the block being written, as a coverage mask over its own box:
    (mask, (x, y) on the page, color, [(x, top, width) per line], line height)."""
    st, f = b.style, font(b.style.size)
    x1 = NOTE_X1 if b.kind == "note" else W - 18
    mask = Image.new("L", (x1 - b.x, b.h), 0)
    d = ImageDraw.Draw(mask)
    lines = []
    for i, line in enumerate(b.lines):
        lx, mid = (b.indent if i == 0 else 0), st.pad_t + i * st.line + st.line // 2
        d.text((lx, mid), line, font=f, fill=255, anchor="lm")
        lines.append((lx, mid - st.line // 2, f.getlength(line)))
    color = STICKY_INK if b.kind == "note" else INK
    return mask, (b.x, b.y), color, lines, st.line


@lru_cache(maxsize=8)
def _edge(h: int) -> Image.Image:
    """EDGE px of fade (opaque -> clear), for the tip of the ink being written."""
    return Image.frombytes("L", (EDGE, 1), bytes(int(255 * (1 - i / EDGE)) for i in range(EDGE))).resize((EDGE, h))


def _pencil(d: ImageDraw.ImageDraw, tx: float, ty: float) -> None:
    """A small pencil whose tip is at (tx, ty), leaning to the right: low, so it covers the
    unwritten rest of the line rather than the line above."""
    a = math.radians(30)
    ux, uy = math.cos(a), -math.sin(a)
    nx, ny = -uy * 7, ux * 7                         # half the pencil's width, across it

    def at(k: float, side: float = 0.0) -> tuple[float, float]:
        return (tx + ux * k + nx * side, ty + uy * k + ny * side)
    d.polygon([at(0), at(16, 1), at(16, -1)], fill=(245, 214, 170), outline=(150, 110, 60))
    d.polygon([at(0), at(6, 0.38), at(6, -0.38)], fill=INK)
    d.polygon([at(16, 1), at(66, 1), at(66, -1), at(16, -1)], fill=(250, 196, 30), outline=(176, 120, 10))
    d.polygon([at(66, 1), at(71, 1), at(71, -1), at(66, -1)], fill=(170, 172, 180))
    d.polygon([at(71, 1), at(81, 1), at(81, -1), at(71, -1)], fill=(244, 128, 140), outline=(190, 80, 95))


def _paste_ink(img: Image.Image, ink: tuple, progress: float) -> None:
    """Paste the part of the ink written by ``progress`` (0..1), with a soft edge and the pencil."""
    mask, (ox, oy), color, lines, line_h = ink
    wipe = Image.new("L", mask.size, 0)
    d = ImageDraw.Draw(wipe)
    total = sum(w for _, _, w in lines) or 1.0
    r, start, head = progress * total, 0.0, None
    for lx, top, w in lines:
        if r <= start:
            break
        end = lx + min(w, r - start)
        if r - start >= w:
            d.rectangle((0, top, mask.width, top + line_h), fill=255)
        else:
            if int(end) - EDGE > 0:
                d.rectangle((0, top, int(end) - EDGE, top + line_h), fill=255)
            wipe.paste(_edge(line_h), (int(end) - EDGE, top))
            head = (ox + end, oy + top + line_h * 0.72)
        start += w
    img.paste(color, (ox, oy, ox + mask.width, oy + mask.height), ImageChops.multiply(mask, wipe))
    if head is not None:
        _pencil(ImageDraw.Draw(img), *head)


def _build(p: Page) -> tuple[Image.Image, Image.Image, Optional[tuple]]:
    """(page without the ink being written, finished page, that ink or None)."""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    top = _header(d, p)
    _paper(img, top)
    blocks, hidden = layout(p, top + 22)
    ink = None
    if hidden:
        d.text((TEXT_X, top + 22 + MORE_H // 2 - 4),
               f"… {hidden} earlier step{'s' if hidden != 1 else ''}", font=font(26), fill=DIM, anchor="lm")
    for b in blocks:
        _draw_block(img, d, b)
        if b.writing:
            ink = _ink(b)
    if not p.steps:
        mid = (top + BOTTOM) // 2
        _pencil(d, W // 2 - 40, mid - 20)
        d.text((W // 2, mid + 50), "Notes appear here, step by step", font=font(30), fill=DIM, anchor="mm")
    hint = "Stuck? Just say “why?”"
    fh = font(26)
    hw = fh.getlength(hint)
    d.rounded_rectangle((W // 2 - hw / 2 - 22, H - 70, W // 2 + hw / 2 + 22, H - 26), 22, fill=PAPER, outline=GRID, width=2)
    d.text((W // 2, H - 48), hint, font=fh, fill=DIM, anchor="mm")
    done = img
    if ink is not None:
        done = img.copy()
        mask, (ox, oy), color, _, _ = ink
        done.paste(color, (ox, oy, ox + mask.width, oy + mask.height), mask)
    return img, done, ink
