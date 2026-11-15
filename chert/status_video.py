"""The agent's own FaceTime video: what ScanSafe is doing, step by step.

Portrait 720x1280 so it fills the caller's iPhone screen (the page picture from the sandbox is
phone-shaped too). Drawn with Pillow so any page title renders, not just ASCII.

Screens:
  idle     - "Hold the QR code up"
  checking - a checklist that moves while the sandbox works. Each step only gets its tick
             once the real result is back; while waiting, the step we're most likely on spins.
             Once the sandbox streams its browser screen (set_live_frame), the checklist gives
             way to that LIVE picture under a compact header (step + the site it's on now).
  replay   - right after the result: the same checklist again with the real findings
             (where the link went, the page title, what the AI checks found), one step a beat.
  verdict  - the result banner over the full page picture.
Parking meter calls (chert/meter_pay.py) add:
  checking - with meter info set (begin_meter_view), the live header names the meter, hours and
             total instead of the scan step.
  meter    - "3 hours" banner (total, meter) over the picture of the meter page.
  paid     - green "Paid" banner with a tick: "Paid · 2 hours · 0.02 SOL", over the meter page
             picture when it shows the same hours, else a big tick card.
Voice-confirmed payment (chert/voice_pay.py): while a payment waits for the caller's "yes, pay",
an amber card along the bottom of whatever screen is up says so, with the amount, hours and plate
(set_consent). It goes away on confirm, cancel, expiry, stop or paid.
Linked Dogwood account: the live picture is the official Dogwood app being operated in the
sandbox, and the line under the header says the step ("Now: Typing your plate GA 4821K")
instead of the site (note_step). Paid shows over the app's receipt picture.
Community plugins (chert/plugins.py) add:
  card     - the plugin that is on (big title) and its latest line, e.g. "Squat coach" /
             "Knees out over your toes" (set_card). Text only, clipped, never run.
Helper app jobs (chert/runner.py: form filler, Vercel) reuse the live view (begin_live): the
caller's OWN computer streams its browser, the header says "Your computer · Form filler", the
line under it the helper's latest progress note, and the LIVE tag "on your computer". Before
the first frame a waiting screen; end_live puts a tick where the spinner was.
"""
from __future__ import annotations

import asyncio
import base64
import io
import math
import time
from typing import Optional
from urllib.parse import urlparse

import numpy as np
from livekit import rtc
from PIL import Image, ImageDraw, ImageFont

from chert import whiteboard

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"

# (label while running, label when done) and roughly when the sandbox reaches that step
STEPS = [
    ("Reading the code", "Read the code", 0.0),
    ("Opening in a safe sandbox", "Opened in a safe sandbox", 0.5),
    ("Following where it leads", "Followed where it leads", 3.0),
    ("Looking at the page", "Looked at the page", 6.0),
    ("AI safety check", "AI safety check", 9.0),
]
REPLAY_STEP_S = 1.1          # how long each finding stays as "newest" during the replay

COLORS = {"idle": (30, 58, 95), "checking": (32, 40, 56), "safe": (22, 128, 61),
          "suspicious": (180, 110, 10), "malicious": (185, 28, 28), "error": (90, 90, 90),
          "meter": (30, 58, 95), "paid": (22, 128, 61), "card": (30, 58, 95)}
LABELS = {"idle": "Ask me anything", "checking": "Checking...", "safe": "Looks safe",
          "suspicious": "Be careful", "malicious": "Don't pay this", "error": "Try again",
          "meter": "Parking meter", "paid": "Paid"}
VERDICTS = ("safe", "suspicious", "malicious")
TEXT_W = 720 - 130 - 36       # room for step text right of the icons
LIVE_TOP = 250                # live-screen layout: header above, sandbox browser picture below
LIVE_RED = (220, 38, 38)
CARD_TITLE_CHARS, CARD_BODY_CHARS = 40, 120
WHITE, DIM, GREEN, RED, AMBER = (255, 255, 255), (165, 175, 190), (74, 222, 128), (248, 113, 113), (251, 191, 36)


def hours_text(n: int) -> str:
    return f"{n} hour" if n == 1 else f"{n} hours"


def sol_text(amount: float) -> str:
    s = f"{float(amount):.9f}".rstrip("0").rstrip(".")
    return s or "0"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_DIR + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
    except OSError:
        return ImageFont.load_default(size)


def _fonts() -> dict:
    return {k: _font(*v) for k, v in {
        "brand": (84, True), "big": (64, True), "label": (40, True), "step": (34, True),
        "detail": (29, False), "small": (28, False), "tag_b": (24, True), "tag": (24, False)}.items()}


def _host(url: Optional[str]) -> str:
    try:
        return (urlparse(url or "").hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def findings(result: dict) -> list[tuple[str, str]]:
    """One (detail, tone) per step, from the real scan result. tone: ok / warn / bad."""
    chain = [h for h in (result.get("redirect_chain") or []) if h]
    hosts: list[str] = []
    for h in [result.get("url")] + chain + [result.get("final_url")]:
        hh = _host(h)
        if hh and (not hosts or hosts[-1] != hh):
            hosts.append(hh)
    first = hosts[0] if hosts else _host(result.get("url")) or "a link"
    hops = len(hosts) - 1
    if hops <= 0:
        follow = (f"Stays on {first}", "ok")
    else:
        follow = (" → ".join(hosts[-3:]) if hops < 3 else f"{hops} jumps → {hosts[-1]}",
                  "warn" if hops >= 2 else "ok")
    title = _clip(result.get("page_title") or "", 34)
    page = (f"“{title}”" if title else "No title", "ok")
    c = result.get("checks") or {}
    bad = []
    if (c.get("asks_payment_p") or 0) >= 0.5:
        bad.append("asks for card")
    if (c.get("asks_password_p") or 0) >= 0.5:
        bad.append("asks for password")
    imp = c.get("impersonates")
    if imp and imp not in ("none", "unknown") and (c.get("impersonates_p") or 0) >= 0.5:
        bad.append("pretends to be a real business")
    if (c.get("prompt_injection_p") or 0) >= 0.5:
        bad.append("hidden tricks")
    # Match the verdict: on a "safe" result the signals didn't add up to a scam (a donation
    # banner on Wikipedia "asks for payment"), so showing them in red contradicts the verdict.
    if result.get("verdict") == "safe" or not bad:
        ai = ("No warning signs", "ok")
    else:
        ai = (", ".join(bad).capitalize(), "bad" if result.get("verdict") == "malicious" else "warn")
    return [(first, "ok"), ("Never touched your phone", "ok"), follow, page, ai]


def _fit(text: str, font, max_w: int) -> str:
    """Cut text (with an ellipsis) so it fits in max_w pixels."""
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(text: str, font, max_w: int, lines: int = 2) -> list[str]:
    """Word-wrap into at most ``lines`` lines; the last one gets an ellipsis if it overflows."""
    words, out, cur = text.split(" "), [], ""
    for i, w in enumerate(words):
        trial = (cur + " " + w).strip()
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = w
            if len(out) == lines - 1:
                cur = " ".join([cur] + words[i + 1:])   # by position: repeated words are fine
                break
    out.append(cur)
    return [_fit(l, font, max_w) for l in out[:lines]]


class StatusVideo:
    """Publishes the agent's camera track (Chert needs one, from the agent's own participant)."""

    W, H, FPS = 720, 1280, 10
    BANNER = 200
    COLORS, LABELS = COLORS, LABELS
    # Parking meter calls only (class defaults, so a bare StatusVideo still works):
    meter: Optional[dict] = None          # {"label", "hours", "amount"} while following a meter
    meter_label = ""                      # "Meter 42 · Dogwood Lot & Meter Co."
    meter_shot: Optional[Image.Image] = None
    meter_shot_hours: Optional[int] = None
    live_step = ""                        # Dogwood app: what the sandbox is doing ("Tapping Install")
    consent: Optional[str] = None         # "Say “yes, pay” to confirm · 0.03 SOL · 3 h · GA 4821K"
    card: Optional[tuple[str, str]] = None   # (title, body) of a plugin card
    plain = False                         # baseline ("Chert out of the box"): no ScanSafe idle screen
    live_title = ""                       # helper app: "Your computer · Form filler" (begin_live)
    live_tag = ""                         # helper app: LIVE tag text instead of "on our computer"
    live_done = False                     # helper app: job over, a tick instead of the spinner
    board: Optional[whiteboard.Whiteboard] = None   # Tutor: the lesson's notes page

    def __init__(self) -> None:
        self.state = "idle"
        self.shot: Optional[Image.Image] = None        # full-size page picture, fitted to the frame
        self.thumb: Optional[Image.Image] = None
        self.code = ""             # the code being checked (so a stale scan can't paint over it)
        self.code_host = ""
        self.result: Optional[dict] = None
        self.check_started = 0.0
        self.replay_started = 0.0
        self.live: Optional[tuple[Image.Image, Image.Image]] = None   # (picture, rounded mask)
        self.live_seq = 0          # bumps on every new live frame, so it gets drawn
        self.live_host = ""        # where the sandbox browser is now (from note_nav)
        self.source = rtc.VideoSource(self.W, self.H)
        self._task: Optional[asyncio.Task] = None
        self._f = _fonts()

    # --- state changes (called by the call logic) ----------------------------------------------

    def begin_check(self, code: str) -> None:
        self.state, self.result, self.shot, self.thumb = "checking", None, None, None
        self.live, self.live_host, self.code = None, "", code
        self.live_step = ""
        self.live_title, self.live_tag, self.live_done = "", "", False   # begin_live sets them again
        self.meter = None          # an ordinary check; begin_meter_view sets it again
        self.code_host = _host(code) or _clip(code, 28)
        self.check_started = time.monotonic()

    def set_live_frame(self, jpeg: bytes) -> bool:
        """A new picture of the sandbox browser's screen (JPEG bytes). Called from the scan's own
        thread, so the decode and resize happen there, never in the render loop. Only the latest
        frame is kept. Like the page picture, it is only a picture: nothing runs on the phone."""
        if self.state != "checking":
            return False                             # result is in (or stopped): ignore stragglers
        area_w, area_h = self.W - 40, self.H - LIVE_TOP - 20
        try:
            img = Image.open(io.BytesIO(jpeg))
            scale = min(area_w / img.width, area_h / img.height)
            size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img.draft("RGB", size)       # big JPEGs decode at a reduced scale (still >= size): cheap
            img = img.convert("RGB").resize(size, Image.BILINEAR)
        except Exception:
            return False
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), 26, fill=255)
        if self.state != "checking":
            return False
        self.live = (img, mask)                      # one assignment: the render loop sees old or new
        self.live_seq += 1
        return True

    def note_nav(self, url: str) -> None:
        """The sandbox browser went to ``url``: show its host in the live header."""
        self.live_host = _host(url) or _clip(url, 40)

    def note_step(self, text: str) -> None:
        """Operator mode: what the sandbox is doing now, shown instead of the host. ``text`` comes
        from the sandbox's fixed step names, never from the page."""
        self.live_step = _clip(text, 60)

    def begin_live(self, key: str, title: str, tag: str = " · on your computer") -> None:
        """Helper app job (chert/runner.py): the live view of the caller's own computer under
        ``title`` ("Your computer · Form filler"). ``key`` names the job, so frames of an older
        job can't land on this view (video.code)."""
        self.begin_check(key)
        self.live_title, self.live_tag = _clip(title, 60), " ".join((tag or "").split(" "))[:40]
        self.live_step = "Waiting for your computer"

    def end_live(self, step: str) -> None:
        """The job is over: keep its last picture, a tick instead of the spinner, ``step`` below."""
        if self.state == "checking" and self.live_title:
            self.live_done = True
            self.note_step(step)

    def set_result(self, result: dict) -> None:
        verdict = result.get("verdict")
        self.result = result
        shots = result.get("screenshots") or []
        self.show_screenshot(shots[0] if shots else None)
        self.state = verdict if verdict in VERDICTS else "error"
        self.replay_started = time.monotonic()
        self.live = None                             # after the state flips: no checklist flash

    def show_page(self) -> None:
        """Skip straight to the verdict screen with the page picture (caller asked to see it)."""
        self.replay_started = 0.0

    def reset(self) -> None:
        self.state, self.shot, self.thumb, self.result = "idle", None, None, None
        self.live, self.live_host, self.code = None, "", ""
        self.live_step = ""
        self.live_title, self.live_tag, self.live_done = "", "", False
        self.meter, self.meter_shot, self.meter_shot_hours = None, None, None
        self.consent = None
        self.card = None
        self.board = None

    def set_card(self, title: str, body: str) -> None:
        """A community plugin's card: its name big, then one short line (a coaching cue, what
        it does). Both are plugin or model text, so they are clipped and drawn as text only."""
        self.card = (_clip(title, CARD_TITLE_CHARS), _clip(body, CARD_BODY_CHARS))
        self.state = "card"
        self.live = None

    # --- Tutor's whiteboard (chert/whiteboard.py cleans and clips all of its text) -------------

    def _show_board(self) -> None:
        self.state = "whiteboard"
        self.live = None

    def board_title(self, title: str) -> str:
        """A fresh page with ``title`` on it (no steps). Returns the title as shown."""
        self.board = whiteboard.Whiteboard(title)
        self._show_board()
        return self.board.title

    def board_step(self, text: str) -> Optional[int]:
        """Append a numbered step; it writes itself. Its number, or None for empty text."""
        if self.board is None:
            self.board = whiteboard.Whiteboard()
        n = self.board.add_step(text)
        if n is not None:
            self._show_board()
        return n

    def board_note(self, text: str) -> Optional[int]:
        """A sticky note on the newest step. That step's number, or None when there's no step."""
        n = self.board.add_note(text) if self.board is not None else None
        if n is not None:
            self._show_board()
        return n

    def board_clear(self) -> None:
        """Wipe the steps; the title stays."""
        if self.board is None:
            self.board = whiteboard.Whiteboard()
        else:
            self.board.clear()
        self._show_board()

    def set_consent(self, text: Optional[str]) -> None:
        """Show (or with None, clear) the "say yes, pay" card. ``text`` is built by us from the
        server's intent (amount, hours, plate), never from a page."""
        self.consent = _clip(text, 120) if text else None

    # --- parking meter calls -------------------------------------------------------------------

    def begin_meter_view(self, url: str, hours: int, amount: float) -> None:
        """Live view of the meter page for ``hours``: the checking screen, with the hours and
        total in the header instead of the scan step."""
        self.begin_check(url)
        self.meter = {"label": self.meter_label, "hours": int(hours), "amount": float(amount)}

    def set_meter_view(self, result: dict, hours: int, amount: float) -> None:
        """The meter page's picture (from the scan result) under an hours/total banner. The
        page's verdict is not shown: the payment itself was checked against our merchant list."""
        shots = result.get("screenshots") or []
        self.show_screenshot(shots[0] if shots else None)
        self.result = None
        self.meter = {**(self.meter or {}), "hours": int(hours), "amount": float(amount)}
        self.meter_shot, self.meter_shot_hours = self.shot, int(hours)
        self.state = "meter"
        self.live = None

    def set_paid(self, hours: int, amount: float) -> None:
        """The app's payment went through: green Paid banner."""
        self.consent = None
        self.meter = {**(self.meter or {}), "hours": int(hours), "amount": float(amount)}
        if self.meter_shot is not None and self.meter_shot_hours == int(hours):
            self.shot = self.meter_shot              # the run's own last picture (the receipt)
        elif self.live is not None:
            self.shot = self.live[0]                 # run still going: its latest live frame, not a blank card
        else:
            self.shot = None
        self.result = None
        self.state = "paid"
        self.live = None

    def show_screenshot(self, data_uri: Optional[str]) -> bool:
        """Decode the sandbox's picture of the page (a data: URI JPEG). It is only a picture:
        nothing on it can be tapped and the page never runs on the caller's phone."""
        self.shot = self.thumb = None
        if not data_uri or "base64," not in data_uri:
            return False
        try:
            img = Image.open(io.BytesIO(base64.b64decode(data_uri.split("base64,", 1)[1]))).convert("RGB")
        except Exception:
            return False
        area_w, area_h = self.W - 40, self.H - self.BANNER - 40
        scale = min(area_w / img.width, area_h / img.height)
        self.shot = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                               Image.LANCZOS)
        t = 300 / img.height
        self.thumb = img.resize((max(1, int(img.width * t)), 300), Image.LANCZOS)
        return True

    # --- drawing -------------------------------------------------------------------------------

    def _replaying(self, now: float) -> int:
        """How many findings are revealed (0..5), or -1 once the replay is over."""
        if not self.result or not self.replay_started:
            return -1
        n = int((now - self.replay_started) / REPLAY_STEP_S) + 1
        return n if n <= len(STEPS) + 1 else -1      # +1: hold the full list one more beat

    def _spinner(self, d: ImageDraw.ImageDraw, cx: int, cy: int, now: float) -> None:
        a = (now * 360 * 1.2) % 360
        d.arc((cx - 18, cy - 18, cx + 18, cy + 18), a, a + 270, fill=AMBER, width=6)

    def _tick(self, d: ImageDraw.ImageDraw, cx: int, cy: int, tone: str) -> None:
        col = {"ok": GREEN, "warn": AMBER, "bad": RED}[tone]
        d.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=col)
        if tone == "bad":
            d.line((cx - 9, cy - 9, cx + 9, cy + 9), fill=WHITE, width=5)
            d.line((cx - 9, cy + 9, cx + 9, cy - 9), fill=WHITE, width=5)
        else:
            d.line((cx - 10, cy, cx - 3, cy + 8, cx + 11, cy - 8), fill=WHITE, width=5, joint="curve")

    def _checklist(self, img: Image.Image, now: float, revealed: Optional[int]) -> None:
        """revealed=None: still waiting for the result. Else: show that many real findings."""
        d = ImageDraw.Draw(img)
        f = self._f
        d.text((48, 70), "ScanSafe", font=f["brand"], fill=WHITE)
        sub = "Checking your code" if revealed is None else "Here's what I found"
        d.text((50, 180), sub, font=f["label"], fill=DIM)
        elapsed = now - self.check_started
        found = findings(self.result) if revealed is not None and self.result else []
        y = 300
        for i, (running, done, t_at) in enumerate(STEPS):
            cx, cy = 80, y + 22
            if revealed is not None:
                if i < revealed:
                    detail, tone = found[i]
                    self._tick(d, cx, cy, tone)
                    d.text((130, y), _fit(done, f["step"], TEXT_W), font=f["step"], fill=WHITE)
                    for k, line in enumerate(_wrap(detail, f["detail"], TEXT_W)):
                        d.text((130, y + 46 + 36 * k), line, font=f["detail"],
                               fill={"ok": DIM, "warn": AMBER, "bad": RED}[tone])
                else:
                    d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=DIM, width=4)
                    d.text((130, y), _fit(done, f["step"], TEXT_W), font=f["step"], fill=DIM)
            else:
                current = max(j for j, s in enumerate(STEPS) if elapsed >= s[2])
                if i == 0:                          # we really have read the code
                    self._tick(d, cx, cy, "ok")
                    d.text((130, y), done, font=f["step"], fill=WHITE)
                    d.text((130, y + 46), _fit(self.code_host, f["detail"], TEXT_W), font=f["detail"], fill=DIM)
                elif i <= current:                  # started, not confirmed done: spin
                    self._spinner(d, cx, cy, now)
                    d.text((130, y), _fit(running + "…", f["step"], TEXT_W), font=f["step"], fill=WHITE)
                else:
                    d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=DIM, width=4)
                    d.text((130, y), _fit(running, f["step"], TEXT_W), font=f["step"], fill=DIM)
            y += 160
        if revealed is None:
            for k, line in enumerate(_wrap("The link opens on our computer, not on your phone.",
                                           f["small"], self.W - 100)):
                d.text((50, self.H - 150 + 40 * k), line, font=f["small"], fill=DIM)

    def _live(self, img: Image.Image, now: float, live: tuple[Image.Image, Image.Image]) -> None:
        """Checking, with the sandbox browser streaming: compact header + the live picture."""
        d = ImageDraw.Draw(img)
        f = self._f
        d.text((40, 22), "ScanSafe", font=f["label"], fill=WHITE)
        elapsed = now - self.check_started
        # a frame means the sandbox is already open, so never show "Reading the code" here
        current = max(1, max(j for j, s in enumerate(STEPS) if elapsed >= s[2]))
        if self.live_done:
            self._tick(d, 60, 106, "ok")
        else:
            self._spinner(d, 60, 106, now)
        meter = self.meter
        head = (f"{hours_text(meter['hours'])} · {sol_text(meter['amount'])} SOL" if meter
                else self.live_title or STEPS[current][0] + "…")
        d.text((96, 86), _fit(head, f["step"], self.W - 136), font=f["step"], fill=WHITE)
        step = self.live_step
        where = step or self.live_host or self.code_host
        lead = "Now: " if step else "Now on: "
        d.text((40, 142), lead, font=f["detail"], fill=DIM)
        x = 40 + int(f["detail"].getlength(lead))
        d.text((x, 142), _fit(where, f["detail"], self.W - 40 - x), font=f["detail"], fill=WHITE)
        # the LIVE tag, centered between header and picture
        tag_b, tag_r = "LIVE", self.live_tag or " · on our computer, not your phone"
        fb, fr = f["tag_b"], f["tag"]
        tw = 22 + int(fb.getlength(tag_b) + fr.getlength(tag_r))
        w = tw + 40
        x0, y0 = (self.W - w) // 2, 196
        d.rounded_rectangle((x0, y0, x0 + w, y0 + 40), 20, fill=LIVE_RED)
        d.ellipse((x0 + 20, y0 + 14, x0 + 32, y0 + 26), fill=WHITE)
        d.text((x0 + 42, y0 + 8), tag_b, font=fb, fill=WHITE)
        d.text((x0 + 42 + int(fb.getlength(tag_b)), y0 + 8), tag_r, font=fr, fill=WHITE)
        pic, mask = live
        px, py = (self.W - pic.width) // 2, LIVE_TOP
        d.rounded_rectangle((px - 6, py - 6, px + pic.width + 5, py + pic.height + 5), 32, fill=LIVE_RED)
        img.paste(pic, (px, py), mask)

    def _live_wait(self, img: Image.Image, now: float) -> None:
        """Helper app job before its first frame: the header, a big spinner and the latest note."""
        d = ImageDraw.Draw(img)
        f = self._f
        d.text((48, 70), "ScanSafe", font=f["label"], fill=DIM)
        for k, line in enumerate(_wrap(self.live_title, f["big"], self.W - 96)):
            d.text((48, 180 + 80 * k), line, font=f["big"], fill=WHITE)
        cy = 700
        if self.live_done:
            self._tick(d, self.W // 2, cy, "ok")
        else:
            a = (now * 360 * 1.2) % 360
            d.arc((self.W // 2 - 70, cy - 70, self.W // 2 + 70, cy + 70), a, a + 270, fill=AMBER, width=14)
        for k, line in enumerate(_wrap(self.live_step or "Working…", f["label"], self.W - 120)):
            d.text((60, cy + 150 + 56 * k), line, font=f["label"], fill=WHITE)

    def _verdict(self, img: Image.Image) -> None:
        d = ImageDraw.Draw(img)
        col = COLORS[self.state]
        d.rectangle((0, 0, self.W, self.BANNER), fill=col)
        d.text((40, 52), LABELS[self.state], font=self._f["big"], fill=WHITE)
        d.text((44, 138), "Picture of the website · just a picture", font=self._f["small"], fill=WHITE)
        if self.shot is not None:
            x = (self.W - self.shot.width) // 2
            y = self.BANNER + 20
            img.paste(self.shot, (x, y))
            d.rectangle((x - 6, y - 6, x + self.shot.width + 5, y + self.shot.height + 5), outline=col, width=8)

    def _meter_banner(self, img: Image.Image, paid: bool) -> None:
        d = ImageDraw.Draw(img)
        f = self._f
        m = self.meter or {"hours": 1, "amount": 0.0, "label": ""}
        d.rectangle((0, 0, self.W, self.BANNER), fill=COLORS["paid" if paid else "meter"])
        if paid:
            cx, cy = 80, 64
            d.ellipse((cx - 38, cy - 38, cx + 38, cy + 38), fill=WHITE)
            d.line((cx - 19, cy, cx - 5, cy + 15, cx + 21, cy - 14), fill=COLORS["paid"], width=9,
                   joint="curve")
            d.text((140, 28), "Paid", font=f["big"], fill=WHITE)
            line = f"{hours_text(m['hours'])} · {sol_text(m['amount'])} SOL"
            d.text((42, 112), _fit(line, f["label"], self.W - 80), font=f["label"], fill=WHITE)
        else:
            d.text((40, 36), hours_text(m["hours"]), font=f["big"], fill=WHITE)
            line = f"Total {sol_text(m['amount'])} test SOL · tap Pay in the app"
            d.text((44, 124), _fit(line, f["small"], self.W - 80), font=f["small"], fill=WHITE)
        if m.get("label"):
            d.text((44, 164), _fit(m["label"], f["tag"], self.W - 80), font=f["tag"], fill=WHITE)

    def _meter_screen(self, img: Image.Image, now: float) -> None:
        """meter / paid: banner, then the meter page picture (or a big card without one)."""
        paid = self.state == "paid"
        self._meter_banner(img, paid)
        d = ImageDraw.Draw(img)
        f = self._f
        col = COLORS["paid" if paid else "meter"]
        if self.shot is not None:
            x, y = (self.W - self.shot.width) // 2, self.BANNER + 20
            img.paste(self.shot, (x, y))
            d.rectangle((x - 6, y - 6, x + self.shot.width + 5, y + self.shot.height + 5), outline=col, width=8)
            return
        cy = 640
        if paid:
            d.ellipse((self.W // 2 - 130, cy - 130, self.W // 2 + 130, cy + 130), fill=col)
            cx = self.W // 2
            d.line((cx - 62, cy, cx - 16, cy + 48, cx + 68, cy - 46), fill=WHITE, width=26, joint="curve")
            sub = "Your receipt is in the app"
        else:
            self._spinner(d, self.W // 2, cy, now)
            sub = "Opening the meter…"
        d.text((60, cy + 190), _fit(sub, f["label"], self.W - 120), font=f["label"], fill=WHITE)

    def _consent_card(self, img: Image.Image, text: str) -> None:
        """Amber card along the bottom: what saying "yes, pay" will pay."""
        d = ImageDraw.Draw(img)
        f = self._f
        head, _, rest = text.partition(" \u00b7 ")
        x0, y0, x1, y1 = 20, self.H - 190, self.W - 20, self.H - 24
        d.rounded_rectangle((x0, y0, x1, y1), 28, fill=AMBER, outline=(120, 70, 0), width=4)
        d.text((x0 + 32, y0 + 28), _fit(head, f["label"], x1 - x0 - 64), font=f["label"], fill=(40, 26, 0))
        if rest:
            d.text((x0 + 32, y0 + 96), _fit(rest, f["step"], x1 - x0 - 64), font=f["step"], fill=(40, 26, 0))

    def _card(self, img: Image.Image, card: tuple[str, str]) -> None:
        """Plugin card: a small header, the title big, the body wrapped on a lighter panel."""
        d = ImageDraw.Draw(img)
        f = self._f
        title, body = card
        d.text((48, 70), "Toolstone", font=f["label"], fill=DIM)
        d.text((48, 124), "Community skill", font=f["small"], fill=DIM)
        y = 300
        for line in _wrap(title, f["big"], self.W - 96):
            d.text((48, y), line, font=f["big"], fill=WHITE)
            y += 80
        y += 40
        lines = _wrap(body, f["label"], self.W - 160, lines=6) if body else []
        if lines:
            d.rounded_rectangle((32, y, self.W - 32, y + 64 + 56 * len(lines)), 32, fill=(46, 82, 128))
            for k, line in enumerate(lines):
                d.text((80, y + 32 + 56 * k), line, font=f["label"], fill=WHITE)

    def _idle(self, img: Image.Image, now: float) -> None:
        d = ImageDraw.Draw(img)
        if self.plain and self.state == "idle":
            # Baseline: a plain assistant screen, no ScanSafe name and no QR prompt. It breathes,
            # so the picture keeps changing.
            d.text((64, 420), "Assistant", font=_font(96, True), fill=WHITE)
            r = 90 + int(12 * math.sin((int(now * 4) % 24) / 24 * 2 * math.pi))
            cx, cy = self.W // 2, 860
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=WHITE, width=10)
            return
        d.text((60, 420), "Toolstone", font=_font(110, True), fill=WHITE)
        label = LABELS.get(self.state, "")
        d.text((64, 580), label, font=self._f["label"], fill=WHITE)
        if self.state == "idle":
            d.text((64, 650), "or hold up a QR code to check it", font=self._f["detail"], fill=DIM)
            # a simple QR-frame graphic that breathes, so the picture keeps changing
            s = 150 + int(10 * math.sin((int(now * 4) % 24) / 24 * 2 * math.pi))
            cx, cy = self.W // 2, 920
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                x0, y0 = cx + sx * s, cy + sy * s
                d.line((x0, y0, x0 - sx * 60, y0), fill=WHITE, width=10)
                d.line((x0, y0, x0, y0 - sy * 60), fill=WHITE, width=10)

    def _frame_key(self, now: float):
        """Frames that look the same share a key, so we draw them once. Only the spinner and the
        replay change over time; the verdict screen is fully static."""
        if self.state == "checking":
            m = self.meter or {}
            return ("checking", int((now - self.check_started) * 8), id(self.result),
                    self.live_seq if self.live is not None else None, self.live_host,
                    m.get("hours"), m.get("amount"), self.live_step, self.live_title, self.live_done)
        if self.state in VERDICTS:
            n = self._replaying(now)
            return ("verdict", self.state, n, id(self.result), id(self.shot))
        if self.state in ("meter", "paid"):
            m = self.meter or {}
            spin = int(now * 8) if self.shot is None and self.state == "meter" else 0
            return (self.state, m.get("hours"), m.get("amount"), m.get("label"), id(self.shot), spin)
        if self.state == "card":
            return ("card", self.card)
        if self.state == "whiteboard":
            board = self.board
            return ("whiteboard", id(board), board.key(now) if board is not None else None)
        return ("idle", self.state, int(now * 4) % 24, self.plain)

    def _draw(self) -> bytes:
        now = time.monotonic()
        key = (self._frame_key(now), self.consent)
        if key == getattr(self, "_last_key", None):
            return self._last_frame
        frame = self._render(now)
        self._last_key, self._last_frame = key, frame
        return frame

    def _render(self, now: float) -> bytes:
        img = Image.new("RGB", (self.W, self.H), COLORS["checking"] if self.state != "idle" else COLORS["idle"])
        if self.state == "checking":
            live = self.live                         # read once: the scan thread may swap it
            if live is not None:
                self._live(img, now, live)
            elif self.meter is not None:
                self._meter_screen(img, now)         # "Opening the meter…" until frames arrive
            elif self.live_title:
                self._live_wait(img, now)            # helper app: waiting for its first frame
            else:
                self._checklist(img, now, None)
        elif self.state in VERDICTS:
            n = self._replaying(now)
            if n >= 0:
                self._checklist(img, now, min(n, len(STEPS)))
            else:
                self._verdict(img)
        elif self.state in ("meter", "paid"):
            self._meter_screen(img, now)
        elif self.state == "card" and (card := self.card) is not None:   # read once
            img = Image.new("RGB", (self.W, self.H), COLORS["card"])
            self._card(img, card)
        elif self.state == "whiteboard" and (board := self.board) is not None:   # read once
            img = board.frame(now)                   # a fresh copy: the consent card may go on it
        else:
            img = Image.new("RGB", (self.W, self.H), COLORS.get(self.state, COLORS["idle"]))
            self._idle(img, now)
        consent = self.consent                       # read once: the call may clear it meanwhile
        if consent:
            self._consent_card(img, consent)
        return np.asarray(img.convert("RGBA")).tobytes()

    # --- publishing ----------------------------------------------------------------------------

    async def publish(self, room: rtc.Room) -> None:
        track = rtc.LocalVideoTrack.create_video_track("scansafe-video", self.source)
        opts = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA,
            simulcast=False,                         # one sharp layer; FaceTime is the only viewer
            video_encoding=rtc.VideoEncoding(max_bitrate=3_000_000, max_framerate=self.FPS),
            degradation_preference=rtc.DegradationPreference.MAINTAIN_RESOLUTION,
        )
        await room.local_participant.publish_track(track, opts)
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            data = await asyncio.to_thread(self._draw)   # keep drawing off the audio loop
            self.source.capture_frame(rtc.VideoFrame(self.W, self.H, rtc.VideoBufferType.RGBA, data))
            await asyncio.sleep(1 / self.FPS)

    def close(self) -> None:
        if self._task:
            self._task.cancel()
