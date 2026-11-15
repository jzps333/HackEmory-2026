"""Tutor's whiteboard: lesson notes written step by step on the agent's FaceTime video.

chert/status_video.py shows a Whiteboard in its "whiteboard" state; the Tutor plugin's tools in
chert/agent_integration.py fill it (whiteboard_title, write_step, write_note, draw_graph,
clear_whiteboard).
Portrait 720x1280 like every other screen: a warm graph-paper notebook page with a title, then
numbered steps, all handwritten. The newest step (or side note, or graph) writes itself in about a
second with a pencil at the tip; earlier steps stay above it, and when the page is full the oldest scroll off the
top (at most VISIBLE_STEPS stay, under an "… N earlier steps" line). The step being explained has a
highlighter stroke under it. Side notes are yellow sticky notes under their step, in red ink. A
step can have a small graph under it (draw_graph: y = f(x) parsed by a tiny safe parser, never
eval; axes, the curve, an optional dot with its tangent and slope).

The hand is Caveat (chert/fonts/Caveat.ttf, SIL Open Font License: chert/fonts/OFL-Caveat.txt), a
variable font (weight 400-700) in blue-black ink. Each character sits a pixel or two off the
baseline and each word is a few percent bigger or smaller, deterministically (from the step number
and the character's index), so a redraw never jitters. Caveat has no √ ∫ π → ⁿ …: any character it
lacks is drawn in DejaVu Sans (good Unicode math coverage) instead, scaled to the hand's x-height
on the same baseline, and superscripts/subscripts (x², xⁿ⁻¹, x₀) are Caveat's own digits and
letters, smaller and raised/lowered. The "TUTOR · Step N" header and the hint stay in DejaVu Sans.

Every word on it is the model's, so it is cleaned first (clean(): no control characters, no angle
brackets, clipped) and only ever drawn as text. ASCII math the model may still send ("x^2",
"sqrt(x)", "<=", "->", "\\pi") becomes the Unicode it means.

Cheap on a 2-vCPU box: the page is drawn once per change (glyph checks and measurements are
cached). While something is being written each frame is a copy of that page with the new block's
ink pasted through a moving mask; once written, key() stops changing and StatusVideo serves the
cached frame. No LiveKit imports here (unit-testable).
"""
from __future__ import annotations

import itertools
import math
import os
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import NamedTuple, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 720, 1280
TITLE_CHARS, STEP_CHARS, NOTE_CHARS = 60, 140, 160
MAX_STEPS = 40                # kept per page (step numbers keep counting past it)
NOTES_PER_STEP = 2            # the newest are kept
VISIBLE_STEPS = 6             # at most this many steps on the page; older ones scroll off the top
WRITE_MIN_S, WRITE_MAX_S, WRITE_CHAR_S = 0.9, 1.2, 0.008
KEY_HZ = 20                   # key() changes this often while writing (the video runs at 10 fps)

# DejaVu Sans on the Ubuntu servers; WHITEBOARD_FONT_DIR to point elsewhere; Arial Unicode on a Mac.
FONT_DIRS = tuple(d for d in (os.getenv("WHITEBOARD_FONT_DIR"), "/usr/share/fonts/truetype/dejavu/") if d)
FALLBACK_FONTS = ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf")
HAND_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Caveat.ttf")
HAND_WT, HAND_BOLD = 500, 700  # Caveat's weight axis (400-700): steps and notes, title and labels

PAPER, GRID, RULE = (251, 248, 240), (229, 233, 240), (191, 212, 246)
MARGIN = (239, 160, 160)
INK, INK_DONE, DIM = (29, 42, 90), (74, 86, 128), (140, 152, 170)   # blue-black (#1d2a5a), faded
ACCENT = (37, 99, 235)
HIGHLIGHT = (201, 224, 255)    # the highlighter under the current step (multiplied over the paper)
STICKY, STICKY_FOLD, STICKY_SHADOW = (254, 240, 138), (234, 206, 84), (224, 218, 200)
NOTE_INK, NOTE_LABEL_INK = (150, 38, 26), (156, 86, 8)              # dark red, brown
WHITE = (255, 255, 255)

MARGIN_X = 82                 # the red margin line; step numbers sit left of it
NUM_X = 41
TEXT_X, TEXT_R = 108, W - 26  # step text column
NOTE_X0, NOTE_X1 = TEXT_X - 6, W - 28
NOTE_TEXT_X = NOTE_X0 + 18
NOTE_TEXT_W = NOTE_X1 - 22 - NOTE_TEXT_X
NOTE_LABEL = "Note:"
BOTTOM = H - 96               # steps never go below this (the hint sits under it)
STEP_GAP, NOTE_GAP, MORE_H = 16, 10, 46
EDGE = 22                     # soft edge of the ink being written, in px
INK_PAD = 14                  # room around a line's ink for the wobble, descenders and overhangs
GRAPH_H, GRAPH_H_DONE, GRAPH_MIN_H = 350, 230, 110

TITLE_SIZE, TITLE_LINE = 82, 76
BASELINE_K = 0.27             # a line's baseline sits this many sizes below its middle
WOBBLE_PX = 1.7               # most a character leaves the baseline (at size ~46)
WORD_SIZE_K = 0.03            # each word is up to this much bigger or smaller
SCRIPT_K, SUP_RAISE, SUB_DROP = 0.64, 0.33, 0.12   # x², x₀ in the hand: size, raise, drop
MATH_BOOST = 1.18             # DejaVu fallback: the hand's x-height, a little bigger (√ ∫ read)
SLANT = 0.17                  # DejaVu fallback glyphs lean like the hand


@dataclass(frozen=True)
class _Style:
    size: int                 # Caveat px
    line: int
    pad_t: int
    pad_b: int
    lines: int


CUR = _Style(56, 60, 10, 12, 6)          # the step being explained
DONE = _Style(46, 48, 4, 4, 3)           # steps above it (2 lines when the page is full)
NOTE_CUR = _Style(46, 48, 12, 14, 5)
NOTE_DONE = _Style(40, 42, 8, 10, 2)


@lru_cache(maxsize=128)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """DejaVu Sans (the header, the hint, and every character the hand lacks)."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in [os.path.join(d, name) for d in FONT_DIRS] + list(FALLBACK_FONTS):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


@lru_cache(maxsize=96)
def hand_font(size: int, weight: int = HAND_WT) -> ImageFont.FreeTypeFont:
    """Caveat at this size and weight (DejaVu Sans if the file is missing)."""
    try:
        f = ImageFont.truetype(HAND_FONT, size)
    except OSError:
        return font(size, weight >= 600)
    try:
        f.set_variation_by_axes([weight])
    except Exception:                                # FreeType without variable fonts
        try:
            f.set_variation_by_name("Bold" if weight >= 600 else "Regular")
        except Exception:
            pass                                     # the default instance (Regular)
    return f


# --- glyph checks (no fontTools on the server) -------------------------------------------------

_NOT_A_CHAR = "\uffff"        # a Unicode noncharacter: every font draws its .notdef box for it


@lru_cache(maxsize=64)
def _notdef(f: ImageFont.FreeTypeFont) -> tuple:
    m = f.getmask(_NOT_A_CHAR)
    return m.size, bytes(m)


@lru_cache(maxsize=8192)
def font_has(f: ImageFont.FreeTypeFont, ch: str) -> bool:
    """Does ``f`` have a glyph for ``ch``? A missing one renders exactly as the .notdef box."""
    if ch.isspace():
        return True
    m = f.getmask(ch)
    return (m.size, bytes(m)) != _notdef(f)


def has_hand_glyph(ch: str) -> bool:
    """Is ``ch`` in Caveat? (Checked once per character at a fixed size.)"""
    return font_has(hand_font(40, 400), ch)


# --- the hand: lines of glyphs -------------------------------------------------------------------

_SUPS = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣᐟ", "0123456789+−=()nix/"))
_SUBS = dict(zip("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₓₙᵢ", "0123456789+−=()xni"))


def _u(*k: int) -> float:
    """Deterministic noise in [0, 1) from integers: the same on every redraw, in every process."""
    h = 2166136261
    for v in k:
        h = ((h ^ (v & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & 0xFFFFFFFF
    h ^= h >> 12
    h = (h * 0x297A2D39) & 0xFFFFFFFF
    h ^= h >> 15
    return h / 4294967296.0


class _Spec(NamedTuple):      # one character, measured, before it's placed on a line
    drawn: str                # the character drawn (x² draws a small raised "2")
    font: ImageFont.FreeTypeFont
    dy: float                 # off the baseline (superscripts, subscripts)
    adv: float
    slant: bool
    src: int                  # its index in the text (seeds the wobble)
    ch: str                   # the character in the text


class Line(NamedTuple):
    glyphs: tuple             # (x, dy, char, font, slant) per glyph: x from the line's start, dy
                              # off its baseline, slant for a fallback (DejaVu) glyph
    w: float                  # width (the advance of its glyphs)
    text: str


@lru_cache(maxsize=1)
def _math_k() -> float:
    """DejaVu size per hand size so their x-heights roughly match."""
    h = hand_font(100).getbbox("x", anchor="ls")
    m = font(100).getbbox("x", anchor="ls")
    return min(1.0, max(0.6, (h[3] - h[1]) / max(1, m[3] - m[1]) * MATH_BOOST))


@lru_cache(maxsize=16384)
def _glyph(ch: str, size: int, weight: int, fallback: bool = True) -> tuple:
    """(char drawn, font, dy, advance, slant) for one character of the hand at this size."""
    if fallback and ch in _SUPS and has_hand_glyph(_SUPS[ch]):
        f = hand_font(max(8, round(size * SCRIPT_K)), weight)
        drawn, dy = _SUPS[ch], -round(size * SUP_RAISE)
    elif fallback and ch in _SUBS and has_hand_glyph(_SUBS[ch]):
        f = hand_font(max(8, round(size * SCRIPT_K)), weight)
        drawn, dy = _SUBS[ch], round(size * SUB_DROP)
    elif not fallback or has_hand_glyph(ch):
        f, drawn, dy = hand_font(size, weight), ch, 0
    else:
        f = font(max(8, round(size * _math_k())))
        return ch, f, 0, f.getlength(ch) + size * 0.04, True
    return drawn, f, dy, f.getlength(drawn), False


def _word_size(size: int, seed: int, wi: int) -> int:
    return size + round((2 * _u(seed, wi, 7) - 1) * size * WORD_SIZE_K)


def _wobble(seed: int, i: int, size: int) -> tuple[float, float]:
    """(dx, dy) of character ``i``: a slow wave along the line plus a little noise, at most
    WOBBLE_PX (scaled with the size) off the baseline."""
    amp = WOBBLE_PX * min(1.6, max(0.7, size / 46))
    wave = math.sin(i * 0.55 + _u(seed, 1) * 6.283) * 0.65 + (2 * _u(seed, i, 2) - 1) * 0.45
    return (2 * _u(seed, i, 3) - 1) * 0.6, max(-1.0, min(1.0, wave)) * amp


@lru_cache(maxsize=512)
def hand_lines(text: str, size: int, weight: int, width: float, max_lines: int, seed: int = 0,
               first_width: Optional[float] = None, fallback: bool = True) -> tuple[Line, ...]:
    """Word-wrap ``text`` in the hand into at most ``max_lines`` lines of ``width`` px (the last
    gets an ellipsis if it overflows). A word wider than a line (a long formula) is broken between
    characters. ``first_width``: a narrower first line (the sticky note's "Note:" label sits in
    front of it). ``fallback=False`` draws every character in Caveat (tests: the .notdef boxes)."""
    words: list[list[_Spec]] = []
    i = 0
    for wi, word in enumerate(text.split(" ")):
        ws = _word_size(size, seed, wi)
        spec = []
        for ch in word:
            spec.append(_Spec(*_glyph(ch, ws, weight, fallback), i, ch))
            i += 1
        i += 1                                       # the space
        if spec:
            words.append(spec)
    sp = _Spec(" ", hand_font(size, weight), 0, hand_font(size, weight).getlength(" "), False, -1, " ")
    rows: list[list[_Spec]] = []

    def limit() -> float:
        return first_width if first_width is not None and not rows else width
    cur: list[_Spec] = []
    cur_w = 0.0
    queue = deque(words)
    while queue:
        word = queue.popleft()
        add = (sp.adv if cur else 0.0) + sum(g.adv for g in word)
        if cur_w + add <= limit():
            cur += ([sp] if cur else []) + word
            cur_w += add
        elif cur:
            rows.append(cur)
            cur, cur_w = [], 0.0
            queue.appendleft(word)
        else:                                        # wider than a line: break between characters
            take, acc = [], 0.0
            for g in word:
                if take and acc + g.adv > limit():
                    break
                take.append(g)
                acc += g.adv
            rows.append(take)
            if len(take) < len(word):
                queue.appendleft(word[len(take):])
    if cur:
        rows.append(cur)
    if len(rows) > max_lines:
        rest = rows[max_lines - 1:]
        rows = rows[: max_lines - 1]
        flat = [g for k, r in enumerate(rest) for g in ([sp] if k else []) + r]
        ell = _Spec(*_glyph("…", size, weight, fallback), 100_000, "…")
        lim, out, acc = limit(), [], 0.0
        for g in flat:
            if acc + g.adv + ell.adv > lim:
                break
            out.append(g)
            acc += g.adv
        while out and out[-1].ch == " ":
            out.pop()
        rows.append(out + [ell])
    lines = []
    for row in rows:
        x, glyphs = 0.0, []
        for g in row:
            if g.ch != " ":
                dx, dy = _wobble(seed, g.src, size)
                glyphs.append((x + dx, g.dy + dy, g.drawn, g.font, g.slant))
            x += g.adv
        lines.append(Line(tuple(glyphs), x, "".join(g.ch for g in row)))
    return tuple(lines)


@lru_cache(maxsize=2048)
def _slanted(f: ImageFont.FreeTypeFont, ch: str) -> tuple[Image.Image, int, int]:
    """A fallback glyph leaning like the hand: its mask, and where the mask's top-left corner goes
    from the pen position on the baseline."""
    x0, y0, x1, y1 = f.getbbox(ch, anchor="ls")
    pad = int((y1 - y0) * SLANT) + 2
    m = Image.new("L", (x1 - x0 + 2 * pad, y1 - y0 + 2), 0)
    by = 1 - y0                                      # the baseline's row in the mask
    ImageDraw.Draw(m).text((pad - x0, by), ch, font=f, fill=255, anchor="ls")
    m = m.transform(m.size, Image.Transform.AFFINE, (1, SLANT, -SLANT * by, 0, 1, 0),
                    resample=Image.Resampling.BICUBIC)
    return m, x0 - pad, -by


def draw_line(img: Image.Image, line: Line, x: float, baseline: float, fill) -> None:
    """One line of the hand with its left end at ``x`` on ``baseline``."""
    d = ImageDraw.Draw(img)
    for gx, gdy, ch, f, slant in line.glyphs:
        if slant:
            m, ox, oy = _slanted(f, ch)
            px, py = round(x + gx + ox), round(baseline + gdy + oy)
            img.paste(fill, (px, py, px + m.width, py + m.height), m)
        else:
            d.text((x + gx, baseline + gdy), ch, font=f, fill=fill, anchor="ls")


def render_line(text: str, size: int = CUR.size, fallback: bool = True, seed: int = 0) -> Image.Image:
    """``text`` in the hand on one line, as a coverage mask (tests and previews)."""
    (line,) = hand_lines(text, size, HAND_WT, 10_000, 1, seed, None, fallback) or (Line((), 0, ""),)
    img = Image.new("L", (int(line.w) + 2 * INK_PAD, size * 2), 0)
    draw_line(img, line, INK_PAD, round(size * 1.3), 255)
    return img


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


# --- graphs: y = f(x), parsed safely (never eval) ---------------------------------------------

class GraphError(ValueError):
    """The expression or range can't be drawn; the message says what to change (it never echoes
    the expression back)."""


ALLOWED = "x, numbers, + - * / ^, parentheses, sin cos tan exp log sqrt abs, pi and e"
EXPR_CHARS, MAX_TOKENS, MAX_DEPTH, SAMPLES = 120, 200, 24, 200
_FUNCS = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "exp": math.exp, "log": math.log,
          "ln": math.log, "sqrt": math.sqrt, "abs": abs}
_CONSTS = {"pi": math.pi, "e": math.e}
_SUPER = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾", "0123456789+-()"))
_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|([A-Za-z]+)|([-+*/^()√]))")


def _normalise(expr: str) -> str:
    """Unicode math the model may send (x², √x, π, ·, ×, −, ÷) as plain ASCII operators."""
    t = unicodedata.normalize("NFC", expr).strip()
    t = re.sub(r"^\s*(?:y|f\s*\(\s*x\s*\))\s*=", "", t)          # "y = ..." / "f(x) = ..."
    t = re.sub("[" + "".join(_SUPER) + "]+", lambda m: "^(" + "".join(_SUPER[c] for c in m.group(0)) + ")", t)
    for a, b in (("π", "pi"), ("·", "*"), ("×", "*"), ("−", "-"), ("÷", "/"), ("**", "^"), ("–", "-")):
        t = t.replace(a, b)
    return t


def _tokens(expr: str) -> list[tuple[str, object]]:
    if not isinstance(expr, str) or not expr.strip():
        raise GraphError("give an expression in x, like x^2 - 3*x + 2")
    t = _normalise(expr)
    if len(t) > EXPR_CHARS:
        raise GraphError(f"keep the expression under {EXPR_CHARS} characters")
    out, i = [], 0
    while i < len(t):
        if t[i].isspace():
            i += 1
            continue
        m = _TOKEN.match(t, i)
        if not m:
            raise GraphError(f"it has a character I can't use: only {ALLOWED}")
        num, name, op = m.groups()
        if num is not None:
            out.append(("num", float(num)))
        elif name is not None:
            low = name.lower()
            if low in _FUNCS:
                out.append(("fn", low))
            elif low in _CONSTS:
                out.append(("num", _CONSTS[low]))
            elif low == "x":
                out.append(("x", None))
            elif re.fullmatch(r"x+", low):                     # "xx": x·x
                out += [("x", None), ("op", "*")] * (len(low) - 1) + [("x", None)]
            else:
                raise GraphError(f"it uses a name I don't know: only {ALLOWED}")
        else:
            out.append(("op", op))
        if len(out) > MAX_TOKENS:
            raise GraphError("the expression is too long")
        i = m.end()
    return out


class _Parser:
    """expr := term (+|- term)* ; term := unary ((*|/)? unary)* (a missing * is implied: 2x,
    3sin(x), x(x+1)) ; unary := (-|+) unary | power ; power := atom (^ unary)? ;
    atom := number | x | fn atom | fn ( expr ) | √ atom | ( expr ). Builds a small tuple tree."""

    def __init__(self, toks: list) -> None:
        self.t, self.i, self.depth = toks, 0, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.i != len(self.t):
            raise GraphError(f"I couldn't read all of it: use only {ALLOWED}, with balanced parentheses")
        return node

    def _deeper(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise GraphError("it's nested too deeply")

    def expr(self):
        self._deeper()
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = ("add" if op == "+" else "sub", node, self.term())
        self.depth -= 1
        return node

    def term(self):
        node = self.unary()
        while True:
            kind, val = self.peek()
            if (kind, val) in (("op", "*"), ("op", "/")):
                self.take()
                node = ("mul" if val == "*" else "div", node, self.unary())
            elif kind in ("num", "x", "fn") or (kind, val) in (("op", "("), ("op", "√")):
                node = ("mul", node, self.unary())             # implied: 2x, x(x+1)
            else:
                return node

    def unary(self):
        if self.peek() in (("op", "-"), ("op", "+")):
            op = self.take()[1]
            self._deeper()
            node = self.unary()
            self.depth -= 1
            return ("neg", node) if op == "-" else node
        return self.power()

    def power(self):
        node = self.atom()
        if self.peek() == ("op", "^"):
            self.take()
            self._deeper()
            node = ("pow", node, self.unary())
            self.depth -= 1
        return node

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", val)
        if kind == "x":
            return ("x",)
        if kind == "fn" or (kind, val) == ("op", "√"):
            name = "sqrt" if kind == "op" else val
            self._deeper()
            arg = self.atom()
            self.depth -= 1
            return ("call", name, arg)
        if (kind, val) == ("op", "("):
            node = self.expr()
            if self.take() != ("op", ")"):
                raise GraphError("a parenthesis isn't closed")
            return node
        if kind is None:
            raise GraphError("it ends too early: finish the expression")
        raise GraphError(f"I couldn't read it: use only {ALLOWED}")


def _compile(node):
    op = node[0]
    if op == "num":
        v = node[1]
        return lambda x: v
    if op == "x":
        return lambda x: x
    if op == "neg":
        a = _compile(node[1])
        return lambda x: -a(x)
    if op == "call":
        f, a = _FUNCS[node[1]], _compile(node[2])
        return lambda x: f(a(x))
    a, b = _compile(node[1]), _compile(node[2])
    return {"add": lambda x: a(x) + b(x), "sub": lambda x: a(x) - b(x),
            "mul": lambda x: a(x) * b(x), "div": lambda x: a(x) / b(x),
            "pow": lambda x: math.pow(a(x), b(x))}[op]


def parse_expr(expr: str):
    """y = f(x) from text, or GraphError with what to change. Only numbers, x, + - * / ^,
    parentheses, sin cos tan exp log sqrt abs, pi and e: a tokenizer and a recursive-descent
    parser build a tree of those, nothing is ever eval'd. The function returns nan where f is
    undefined (sqrt(-1), 1/0, overflow)."""
    fn = _compile(_Parser(_tokens(expr)).parse())

    def f(x: float) -> float:
        try:
            y = float(fn(x))
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return math.nan
        return y if math.isfinite(y) else math.nan
    return f


@dataclass(frozen=True)
class Graph:
    """A figure under a step: the samples of y = f(x), the visible y range, an optional marked
    point with its tangent's slope, and the caption."""
    label: str
    x0: float
    x1: float
    y0: float
    y1: float
    points: tuple[tuple[float, float], ...]      # (x, y); y is nan where f is undefined
    mark: Optional[tuple[float, float, float]] = None   # (x, y, slope); slope nan: no tangent


def _num(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise GraphError("x_min, x_max and mark_x must be numbers") from None
    if not math.isfinite(v) or abs(v) > 1e6:
        raise GraphError("keep x_min, x_max and mark_x between -1000000 and 1000000")
    return v


def graph(expression: str, x_min=-5.0, x_max=5.0, mark_x=None, label: str = "") -> Graph:
    """Sample y = expression over [x_min, x_max] (SAMPLES + 1 points) and pick a y range that
    shows it: the full range, unless an asymptote would flatten the picture, then the middle of
    the values. GraphError when it can't be drawn."""
    f = parse_expr(expression)
    x0, x1 = _num(x_min), _num(x_max)
    if x0 > x1:
        x0, x1 = x1, x0
    if x1 - x0 < 1e-6:
        raise GraphError("x_max has to be bigger than x_min")
    pts = tuple((x0 + (x1 - x0) * k / SAMPLES, f(x0 + (x1 - x0) * k / SAMPLES)) for k in range(SAMPLES + 1))
    ys = sorted(y for _, y in pts if math.isfinite(y) and abs(y) < 1e12)
    if len(ys) < 2:
        raise GraphError("it isn't defined anywhere from x_min to x_max: try another range")
    lo, hi = ys[0], ys[-1]
    qlo, qhi = ys[len(ys) // 10], ys[len(ys) * 9 // 10]
    if qhi - qlo > 0 and hi - lo > 6 * (qhi - qlo):            # an asymptote: keep the middle
        q = qhi - qlo
        lo, hi = max(lo, qlo - 1.5 * q), min(hi, qhi + 1.5 * q)
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi < lo:
        raise GraphError("its values are too large to draw: try a smaller range")
    span = hi - lo
    if span <= max(1e-9, abs(lo) * 1e-9):
        d = max(1.0, abs(lo) * 1e-3)
        lo, hi, span = lo - d, hi + d, 2 * d
    if 0 < lo < 0.3 * span:                                    # show the x-axis when it's near
        lo = 0.0
    elif -0.3 * span < hi < 0:
        hi = 0.0
    span = hi - lo
    lo, hi = lo - 0.08 * span, hi + 0.08 * span
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        raise GraphError("its values are too large to draw: try a smaller range")
    mark = None
    if mark_x is not None:
        a = _num(mark_x)
        fa = f(a)
        if not math.isnan(fa):
            h = (x1 - x0) * 1e-4
            slope = (f(a + h) - f(a - h)) / (2 * h)
            mark = (a, fa, slope if math.isfinite(slope) and abs(slope) < 1e6 else math.nan)
    cap = clean(label, TITLE_CHARS) or clean(f"y = {_normalise(expression)}", TITLE_CHARS)
    return Graph(cap, x0, x1, lo, hi, pts, mark)


# --- the page ----------------------------------------------------------------------------------

_versions = itertools.count(1)       # unique across boards, so a new board never reuses a frame


@dataclass(frozen=True)
class Step:
    n: int
    text: str
    notes: tuple[str, ...] = ()
    graph: Optional[Graph] = None


@dataclass(frozen=True)
class Page:
    """One immutable snapshot: tools swap in a new one, the render thread reads one."""
    title: str = ""
    steps: tuple[Step, ...] = ()
    writing: Optional[tuple[int, int]] = None   # (step n, note index, -1 the step, -2 its graph)
    started: float = 0.0
    write_s: float = 0.0
    version: int = 0


@dataclass
class _Block:
    kind: str                 # "step" | "note" | "graph"
    n: int                    # step number
    lines: tuple[Line, ...]
    style: _Style
    current: bool = False
    indent: int = 0           # first line starts this far right (the note label)
    writing: bool = False
    seed: int = 0
    y: int = 0
    graph: Optional[Graph] = None
    graph_h: int = 0

    @property
    def h(self) -> int:
        if self.kind == "graph":
            return self.graph_h
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

    def add_graph(self, g: Graph, now: Optional[float] = None) -> Optional[int]:
        """A graph under the current (newest) step (it replaces one already there); it draws
        itself. The step's number, or None when there's no step yet."""
        p = self.page
        if not p.steps:
            return None
        last = p.steps[-1]
        self.page = replace(p, steps=p.steps[:-1] + (replace(last, graph=g),), writing=(last.n, -2),
                            started=time.monotonic() if now is None else now,
                            write_s=WRITE_MAX_S, version=next(_versions))
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


# --- hand-drawn bits ---------------------------------------------------------------------------

def _wavy(d: ImageDraw.ImageDraw, x0: float, x1: float, y: float, color, width: int, seed: int) -> None:
    """A slightly wavy pen stroke from x0 to x1 (the title's underline)."""
    ph, tilt = _u(seed, 11) * 6.283, (2 * _u(seed, 12) - 1) * 3
    n = max(8, int((x1 - x0) / 10))
    pts = []
    for k in range(n + 1):
        t = k / n
        x = x0 + (x1 - x0) * t
        pts.append((x, y + math.sin(t * (x1 - x0) / 46 + ph) * 2.2 + tilt * (t - 0.5)))
    d.line(pts, fill=color, width=width, joint="curve")
    r = width / 2 - 0.5
    for px, py in (pts[0], pts[-1]):
        d.ellipse((px - r, py - r, px + r, py + r), fill=color)


def _ring(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color, width: int, seed: int) -> None:
    """A hand-drawn circle: a bit more than one turn, not quite round, the ends overlapping."""
    a0 = _u(seed, 21) * 6.283
    n = 44
    pts = []
    for k in range(n + 1):
        t = k / n
        a = a0 + t * 6.283 * 1.1
        rr = r * (1 + 0.045 * math.sin(2 * a + seed)) + 2.2 * t
        pts.append((cx + rr * math.cos(a) * 1.05, cy + rr * math.sin(a)))
    d.line(pts, fill=color, width=width, joint="curve")


def _number(d: ImageDraw.ImageDraw, n: int, cx: float, cy: float, size: int, color) -> None:
    """The step number in the hand, centred on (cx, cy)."""
    s = str(n)
    f = hand_font(size if n < 100 else size * 3 // 4, HAND_BOLD)
    x0, y0, x1, y1 = f.getbbox(s, anchor="ls")
    d.text((cx - (x0 + x1) / 2, cy - (y0 + y1) / 2), s, font=f, fill=color, anchor="ls")


def _highlight(b: _Block, i: int) -> tuple[Image.Image, tuple[int, int]]:
    """A soft highlighter stroke under line ``i`` of the current step (slanted ends, slightly
    uneven edges): its mask and where the mask goes on the page."""
    st, line = b.style, b.lines[i]
    x0 = b.x + (b.indent if i == 0 else 0) - 12
    base = _baseline(b, i)
    y0 = base - round(st.size * 0.56) - 4
    w = min(round(line.w) + 32, W - 12 - x0)
    h = round(st.size * 0.68) + 8
    top, bot = 4.0, h - 4.0
    n = max(2, w // 36)
    up = [(8 + (w - 12) * k / n, top + (2 * _u(b.seed, i, k, 31) - 1) * 1.5) for k in range(n + 1)]
    dn = [(w - 4 - (w - 12) * k / n, bot + (2 * _u(b.seed, i, k, 32) - 1) * 1.5) for k in range(n + 1)]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(up + dn, fill=225)
    return mask.filter(ImageFilter.GaussianBlur(1.2)), (x0, y0)


def _mark(img: Image.Image, mask: Image.Image, xy: tuple[int, int]) -> None:
    """Run the highlighter over the page through ``mask``: multiplied, so the grid shows through."""
    box = (xy[0], xy[1], xy[0] + mask.width, xy[1] + mask.height)
    region = img.crop(box)
    img.paste(ImageChops.multiply(region, Image.new("RGB", region.size, HIGHLIGHT)), box, mask)


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        v = round(v)
        return ("−" if v < 0 else "") + str(abs(v))
    return f"{v:.2g}".replace("-", "−")


def _nice(span: float, most: int) -> float:
    raw = span / most
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * p >= raw:
            return m * p
    return 10 * p


def _hand_text(img: Image.Image, text: str, size: int, x: float, base: float, fill, seed: int,
               center: bool = False, weight: int = HAND_WT) -> float:
    lines = hand_lines(text, size, weight, W, 1, seed)
    if not lines:
        return 0.0
    draw_line(img, lines[0], x - (lines[0].w / 2 if center else 0), base, fill)
    return lines[0].w


def _graph_layer(b: _Block) -> tuple:
    """The graph drawn in ink on a transparent layer the width of the text column: (RGB, mask,
    (x, y) on the page, the curve's height in the mask per column (None off the curve))."""
    g, h, cur = b.graph, b.graph_h, b.current
    w = TEXT_R - TEXT_X + 2 * INK_PAD
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cap = 40 if cur else 32
    _hand_text(layer, g.label, cap, INK_PAD, cap * 0.9, INK if cur else INK_DONE, b.seed + 5)
    px0, px1 = INK_PAD + 40, w - INK_PAD - 14
    py0, py1 = round(cap * 1.2), h - (34 if cur else 28)
    sx = (px1 - px0) / (g.x1 - g.x0)
    sy = (py1 - py0) / (g.y1 - g.y0)

    def X(x: float) -> float:
        return px0 + (x - g.x0) * sx

    def Y(y: float) -> float:
        return py1 - (min(max(y, g.y0 - 3 * (g.y1 - g.y0)), g.y1 + 3 * (g.y1 - g.y0)) - g.y0) * sy
    axis = (96, 106, 140, 255)
    ax_y = Y(0) if g.y0 <= 0 <= g.y1 else py1
    ax_x = X(0) if g.x0 <= 0 <= g.x1 else px0
    _wavy(d, px0 - 6, px1 + 6, ax_y, axis, 2, b.seed + 1)
    d.line(_vwavy(ax_x, py1 + 6, py0 - 6, b.seed + 2), fill=axis, width=2, joint="curve")
    d.line([(px1 - 4, ax_y - 6), (px1 + 7, ax_y), (px1 - 4, ax_y + 6)], fill=axis, width=2)
    d.line([(ax_x - 6, py0 + 4), (ax_x, py0 - 7), (ax_x + 6, py0 + 4)], fill=axis, width=2)
    tick = 26 if cur else 22
    step = _nice(g.x1 - g.x0, 8)
    k = math.ceil(g.x0 / step)
    while k * step <= g.x1 + 1e-9:
        v = k * step
        if abs(v) > 1e-9 or not (g.y0 <= 0 <= g.y1):
            d.line([(X(v), ax_y - 4), (X(v), ax_y + 4)], fill=axis, width=2)
            _hand_text(layer, _fmt(v), tick, X(v), min(ax_y + tick * 0.9 + 4, h - 4), axis, k + 40, center=True)
        k += 1
    step = _nice(g.y1 - g.y0, 4)
    k = math.ceil(g.y0 / step)
    while k * step <= g.y1 + 1e-9:
        v = k * step
        if abs(v) > 1e-9:
            d.line([(ax_x - 4, Y(v)), (ax_x + 4, Y(v))], fill=axis, width=2)
            lw = hand_lines(_fmt(v), tick, HAND_WT, W, 1, k + 60)
            if lw:
                _hand_text(layer, _fmt(v), tick, max(2, ax_x - 8 - lw[0].w), Y(v) + tick * 0.3, axis, k + 60)
        k += 1
    plot = Image.new("RGBA", layer.size, (0, 0, 0, 0))       # the curve, clipped to the plot area
    pd = ImageDraw.Draw(plot)
    ink = (*(INK if cur else INK_DONE), 255)
    span = g.y1 - g.y0
    pen: list = [None] * w
    run: list = []
    prev = None
    for x, y in g.points + ((math.nan, math.nan),):
        if math.isnan(y) or (prev is not None and abs(y - prev) > 1.2 * span):
            if len(run) > 1:
                pd.line(run, fill=ink, width=4 if cur else 3, joint="curve")
            run = []
        if not math.isnan(y):
            pt = (X(x), Y(y) + (2 * _u(b.seed, len(run), 51) - 1) * 0.5)
            run.append(pt)
            if py0 <= pt[1] <= py1:
                pen[max(0, min(w - 1, int(pt[0])))] = pt[1]
        prev = None if math.isnan(y) else y
    if g.mark is not None:
        a, fa, slope = g.mark
        red = (*NOTE_INK, 255)
        if not math.isnan(slope):
            dx = (g.x1 - g.x0) * 0.22
            pd.line([(X(a - dx), Y(fa - slope * dx)), (X(a + dx), Y(fa + slope * dx))], fill=red, width=3)
        r = 7 if cur else 5
        pd.ellipse((X(a) - r, Y(fa) - r, X(a) + r, Y(fa) + r), fill=(*ACCENT, 255))
    clip = Image.new("L", layer.size, 0)
    ImageDraw.Draw(clip).rectangle((px0 - 2, py0 - 2, px1 + 2, py1 + 2), fill=255)
    layer.paste(plot, (0, 0), ImageChops.multiply(plot.getchannel("A"), clip))
    if g.mark is not None and not math.isnan(g.mark[2]) and py0 <= Y(g.mark[1]) <= py1:
        a, fa, slope = g.mark                         # "slope 2" by the tangent's right end
        size = tick + 6
        txt = f"slope {_fmt(round(slope, 2))}"
        lw = hand_lines(txt, size, HAND_WT, W, 1, b.seed + 7)
        tw = lw[0].w if lw else 0
        dx = (g.x1 - g.x0) * 0.22
        ex, ey = X(a + dx), Y(fa + slope * dx)
        tx = min(max(ex + 8, px0 + 4), px1 - tw)
        ty = min(max(ey - 10, py0 + size), py1 - 8)
        if abs(ty - ax_y) < size * 0.8:              # not on the x-axis
            ty = ax_y - size * 0.9
        _hand_text(layer, txt, size, tx, ty, NOTE_INK, b.seed + 7)
    last = None                                               # the pencil holds its height off the curve
    for i in range(w):
        last = pen[i] if pen[i] is not None else last
        pen[i] = last
    return (layer.convert("RGB"), layer.getchannel("A"), (TEXT_X - INK_PAD, b.y), tuple(pen))


def _vwavy(x: float, y0: float, y1: float, seed: int) -> list:
    ph = _u(seed, 11) * 6.283
    n = max(8, int(abs(y1 - y0) / 10))
    return [(x + math.sin(k / n * abs(y1 - y0) / 46 + ph) * 1.6, y0 + (y1 - y0) * k / n) for k in range(n + 1)]


# --- layout ------------------------------------------------------------------------------------

def _seed(n: int, note: int = -1) -> int:
    return n * 8 + note + 2


def _note_indent(st: _Style) -> int:
    return int(hand_font(st.size, HAND_BOLD).getlength(NOTE_LABEL)) + 10


def _header(img: Image.Image, d: ImageDraw.ImageDraw, p: Page) -> int:
    """Label, step count, title and its wavy underline. Returns where the notes start."""
    lab = font(24, True)
    x = 40
    for ch in "TUTOR":                               # a little letter spacing
        d.text((x, 38), ch, font=lab, fill=ACCENT)
        x += int(lab.getlength(ch)) + 4
    if p.steps:
        d.text((W - 40, 38), f"Step {p.steps[-1].n}", font=lab, fill=DIM, anchor="ra")
    lines = hand_lines(p.title or "Notes", TITLE_SIZE, HAND_BOLD, W - 84, 2, 1)
    base = 76 + round(TITLE_SIZE * 0.72)
    for line in lines:
        draw_line(img, line, 40, base, INK)
        base += TITLE_LINE
    base -= TITLE_LINE
    width = max((line.w for line in lines), default=120)
    _wavy(d, 38, 44 + min(width, W - 84), base + 16, ACCENT, 5, len(p.title))
    return base + 42


def _paper(img: Image.Image, top: int) -> None:
    d = ImageDraw.Draw(img)
    for y in range(top, H, 24):
        d.line((0, y, W, y), fill=GRID, width=1)
    for x in range(MARGIN_X % 24, W, 24):
        d.line((x, top, x, H), fill=GRID, width=1)
    d.line((0, top, W, top), fill=RULE, width=3)
    d.line((MARGIN_X, top, MARGIN_X, H), fill=MARGIN, width=3)


def _blocks(step: Step, current: bool, writing: Optional[tuple[int, int]], done_lines: int,
            graph_h: Optional[int] = None) -> list[_Block]:
    st = CUR if current else replace(DONE, lines=done_lines)
    seed = _seed(step.n)
    out = [_Block("step", step.n, hand_lines(step.text, st.size, HAND_WT, TEXT_R - TEXT_X, st.lines, seed),
                  st, current, 0, writing == (step.n, -1), seed)]
    ns = NOTE_CUR if current else NOTE_DONE
    if step.graph is not None:
        out.append(_Block("graph", step.n, (), st, current, 0, writing == (step.n, -2), seed,
                          graph=step.graph, graph_h=graph_h or (GRAPH_H if current else GRAPH_H_DONE)))
        if current:
            ns = replace(ns, lines=3)                  # the graph takes the room
    indent = _note_indent(ns)
    for i, note in enumerate(step.notes):
        seed = _seed(step.n, i)
        lines = hand_lines(note, ns.size, HAND_WT, NOTE_TEXT_W, ns.lines, seed, NOTE_TEXT_W - indent)
        out.append(_Block("note", step.n, lines, ns, current, indent, writing == (step.n, i), seed))
    return out


def _group_h(group: list[_Block]) -> int:
    return sum(b.h + (NOTE_GAP if b.kind != "step" else 0) for b in group)


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
    if need > BOTTOM - top and steps and steps[-1].graph is not None:   # shrink the graph to fit
        gh = max(GRAPH_MIN_H, GRAPH_H - (need - (BOTTOM - top)))
        groups = [_blocks(s, s.n == steps[-1].n, p.writing, 2, gh if s.n == steps[-1].n else None)
                  for s in shown]
    y, out = top, []
    if hidden:
        y += MORE_H
    for g in groups:
        for b in g:
            if b.kind != "step":
                y += NOTE_GAP
            b.y = y
            y += b.h
            out.append(b)
        y += STEP_GAP
    return out, hidden


def _line_y(b: _Block, i: int) -> int:
    """Vertical middle of line ``i`` of a block."""
    return b.y + b.style.pad_t + i * b.style.line + b.style.line // 2


def _baseline(b: _Block, i: int) -> int:
    return _line_y(b, i) + round(b.style.size * BASELINE_K)


def _ink_color(b: _Block):
    if b.kind == "note":
        return NOTE_INK
    return INK if b.current else INK_DONE


def _draw_block(img: Image.Image, d: ImageDraw.ImageDraw, b: _Block) -> None:
    """The block's chrome (highlighter, number, sticky note) and, unless it is being written, its text."""
    st = b.style
    if b.kind == "graph":
        if not b.writing:
            rgb, mask, xy, _ = _graph_layer(b)
            img.paste(rgb, (*xy, xy[0] + mask.width, xy[1] + mask.height), mask)
        return
    if b.kind == "step":
        cy = _line_y(b, 0) + 1
        if b.current:
            if not b.writing:                        # else it runs along with the pencil
                for i in range(len(b.lines)):
                    _mark(img, *_highlight(b, i))
            _ring(d, NUM_X, cy, 23, ACCENT, 3, b.n)
            _number(d, b.n, NUM_X, cy, 38, ACCENT)
        else:
            _ring(d, NUM_X, cy, 19, DIM, 2, b.n)
            _number(d, b.n, NUM_X, cy, 32, INK_DONE)
    else:
        x0, y0, x1, y1 = NOTE_X0, b.y, NOTE_X1, b.y + b.h
        fold = 24 if b.current else 18
        d.rectangle((x0 + 5, y0 + 6, x1 + 5, y1 + 6), fill=STICKY_SHADOW)
        d.polygon([(x0, y0), (x1, y0), (x1, y1 - fold), (x1 - fold, y1), (x0, y1)], fill=STICKY)
        d.polygon([(x1, y1 - fold), (x1 - fold, y1 - fold), (x1 - fold, y1)], fill=STICKY_FOLD)
        d.text((NOTE_TEXT_X, _baseline(b, 0)), NOTE_LABEL, font=hand_font(st.size, HAND_BOLD),
               fill=NOTE_LABEL_INK, anchor="ls")
    if not b.writing:
        color = _ink_color(b)
        for i, line in enumerate(b.lines):
            draw_line(img, line, b.x + (b.indent if i == 0 else 0), _baseline(b, i), color)


def _ink(b: _Block) -> list:
    """What the block being written puts on the page, one piece per line (a graph is one piece):
    [(color or RGB image, coverage mask, (x, y) on the page, width, pencil height in the mask
    (one per column for a graph), highlighter (mask, (x, y)) or None)]."""
    if b.kind == "graph":
        rgb, mask, xy, pen = _graph_layer(b)
        return [(rgb, mask, xy, mask.width - 2 * INK_PAD, pen, None)]
    out = []
    for i, line in enumerate(b.lines):
        lx = b.x + (b.indent if i == 0 else 0)
        top = _line_y(b, i) - b.style.line // 2 - INK_PAD
        mask = Image.new("L", (math.ceil(line.w) + 2 * INK_PAD, b.style.line + 2 * INK_PAD), 0)
        base = _baseline(b, i) - top
        draw_line(mask, line, INK_PAD, base, 255)
        hl = _highlight(b, i) if b.kind == "step" and b.current else None
        out.append((_ink_color(b), mask, (lx - INK_PAD, top), line.w, base, hl))
    return out


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


def _wiped(mask: Image.Image, end: float) -> Image.Image:
    """``mask`` up to column ``end``, fading out over the last EDGE px."""
    wipe = Image.new("L", mask.size, 0)
    if int(end) - EDGE > 0:
        ImageDraw.Draw(wipe).rectangle((0, 0, int(end) - EDGE, mask.height), fill=255)
    wipe.paste(_edge(mask.height), (int(end) - EDGE, 0))
    return ImageChops.multiply(mask, wipe)


def _paste_ink(img: Image.Image, ink: tuple, progress: float) -> None:
    """Paste the part of the ink written by ``progress`` (0..1), with a soft edge and the pencil
    (and the highlighter, on the current step, right behind it)."""
    total = sum(piece[3] for piece in ink) or 1.0
    r, start, head = progress * total, 0.0, None
    for color, mask, (ox, oy), w, pen, hl in ink:
        if r <= start:
            break
        box = (ox, oy, ox + mask.width, oy + mask.height)
        if r - start >= w:
            if hl is not None:
                _mark(img, *hl)
            img.paste(color, box, mask)
        else:
            end = INK_PAD + (r - start)
            if hl is not None:
                hmask, (hx, hy) = hl
                _mark(img, _wiped(hmask, ox + end - hx), (hx, hy))
            img.paste(color, box, _wiped(mask, end))
            if isinstance(pen, tuple):                   # a graph: the pencil rides the curve
                py = pen[max(0, min(len(pen) - 1, int(end)))]
                head = (ox + end, oy + py) if py is not None else None
            else:
                head = (ox + end, oy + pen - 4)
        start += w
    if head is not None:
        _pencil(ImageDraw.Draw(img), *head)


def _build(p: Page) -> tuple[Image.Image, Image.Image, Optional[tuple]]:
    """(page without the ink being written, finished page, that ink or None)."""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    top = _header(img, d, p)
    _paper(img, top)
    blocks, hidden = layout(p, top + 22)
    ink = None
    if hidden:
        (line,) = hand_lines(f"… {hidden} earlier step{'s' if hidden != 1 else ''}", 36, HAND_WT, W, 1, 3)
        draw_line(img, line, TEXT_X, top + 22 + MORE_H // 2 + 6, DIM)
    for b in blocks:
        _draw_block(img, d, b)
        if b.writing:
            ink = _ink(b)
    if not p.steps:
        mid = (top + BOTTOM) // 2
        _pencil(d, W // 2 - 40, mid - 20)
        (line,) = hand_lines("Notes appear here, step by step", 44, HAND_WT, W, 1, 4)
        draw_line(img, line, (W - line.w) / 2, mid + 62, DIM)
    hint = "Stuck? Just say “why?”"
    fh = font(26)
    hw = fh.getlength(hint)
    d.rounded_rectangle((W // 2 - hw / 2 - 22, H - 70, W // 2 + hw / 2 + 22, H - 26), 22, fill=PAPER, outline=GRID, width=2)
    d.text((W // 2, H - 48), hint, font=fh, fill=DIM, anchor="mm")
    done = img
    if ink is not None:
        done = img.copy()
        _paste_ink(done, ink, 1.0)
    return img, done, ink
