"""Make printable QR codes for the ScanSafe demo pages (all brands are made up).

Writes one ~1000px PNG per page (error correction H, 4-module quiet zone plus padding),
and a one-page printable sheet (sheet.html + sheet.png) next to this file.

    python3 -m pip install qrcode pillow
    python3 demo-qr/make_qr.py [--base https://scansafe-demo-sites.vercel.app]
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
SIZE = 1000

# (file stem, fictional business name, what it is, path, expected verdict)
# expected: "scam" = ScanSafe should say malicious or suspicious; "safe" = safe.
# The two "Peachtree Parking Co." fixtures (/fixtures/meter, /fixtures/fake) are left off the sheet
# on purpose: the name is too close to a real Atlanta company (Peachtree Parking Solutions).
# The pages are still deployed; only their QR codes are dropped.
PAGES = [
    ("sample-sites-index", "Sample Websites", "Index of the four sample sites", "/websites", "safe"),
    ("morrow-coffee", "Morrow Coffee", "Cafe + fake \"free pastry\" rewards lure", "/websites/cafe", "scam"),
    ("morrow-coffee-rewards-SCAM", "Morrow Coffee Rewards", "\"Free year of coffee\": card + password", "/websites/cafe/rewards", "scam"),
    ("pixel-palace", "Pixel Palace", "Arcade + fake \"rare skin\" profile lure", "/websites/arcade", "scam"),
    ("pixel-palace-prize-SCAM", "Pixel Palace Prize", "\"500 free tokens\": card + password", "/websites/arcade/prize", "scam"),
    ("trail-notes", "Trail Notes", "Hiking field guide", "/websites/trails", "safe"),
    ("orbit-post", "Orbit Post", "Space journal", "/websites/orbit", "safe"),
    ("urban-atlas-cities", "Urban Atlas", "World's densest cities", "/cities", "safe"),
    ("magnolia-diner", "Magnolia Diner", "Table menu", "/fixtures/safe/index.html", "safe"),
    ("safe-library-wifi", "Fernhollow Library Wi-Fi", "Free Wi-Fi, asks for nothing", "/websites/safe/library-wifi", "safe"),
    ("scam-wifi-login", "Bramblewick Cafe Wi-Fi", "Wi-Fi login asks for email password", "/websites/scams/wifi-login", "scam"),
    ("scam-hidden-ai-note", "Wrenfield Supply Co.", "Checkout + hidden note to AI scanners", "/websites/scams/hidden-ai-note", "scam"),
    ("scam-unpaid-toll", "Kestrel Tollway", "Unpaid toll $4.99 or $50 late fee", "/websites/scams/unpaid-toll", "scam"),
    ("scam-redirect-chain", "Redirect chain", "2 hops, then lands on the toll scam", "/r/a", "scam"),
    ("scam-package-fee", "Swiftlark Parcel", "Package on hold: $1.99 redelivery fee", "/websites/scams/package-fee", "scam"),
    ("scam-menu-app", "Lumen Bistro", "\"Download our app\": starts .apk download", "/websites/scams/menu-app", "scam"),
    ("scam-robot-check", "Zephyrine Parking", "Fake \"verify you are human\" gate + card", "/websites/scams/robot-check", "scam"),
    ("scam-wallet-giveaway", "Glowfin Coin", "Airdrop asks for 12-word recovery phrase", "/websites/scams/wallet-giveaway", "scam"),
]


def make_qr(url: str) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    modules = qr.modules_count + 2 * qr.border
    qr.box_size = max(1, SIZE // modules)              # whole pixels per module: crisp edges
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    canvas = Image.new("RGB", (SIZE, SIZE), "white")   # pad to exactly SIZE (extra quiet zone)
    canvas.paste(img, ((SIZE - img.width) // 2, (SIZE - img.height) // 2))
    return canvas


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for path in ["/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(d: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont, width: int, lines: int = 2) -> list[str]:
    out, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=f) <= width or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = word
    out.append(cur)
    return out[:lines]


def sheet_png(rows: list[dict]) -> None:
    # US Letter at 300 dpi, 4 columns x 5 rows (fits all 18 codes, each ~1.4 in wide)
    W, H, margin, cols, rows_n, head = 2550, 3300, 90, 4, 5, 150
    cell_w = (W - 2 * margin) // cols
    cell_h = (H - 2 * margin - head) // rows_n
    qr_px = min(cell_w - 40, cell_h - 178)
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    d.text((margin, margin - 30), "ScanSafe demo QR codes \u2014 every business is fictional", font=font(58, True), fill="black")
    d.text((margin, margin + 45), "Expected verdict under each code (SCAM = malicious or suspicious). "
           "HackEmory demo only; do not post in public.", font=font(32), fill="#444")
    f_name, f_what, f_exp, f_path = font(36, True), font(27), font(32, True), font(23)
    for i, r in enumerate(rows):
        cx = margin + (i % cols) * cell_w
        cy = margin + head + (i // cols) * cell_h
        qr = Image.open(OUT / r["png"]).resize((qr_px, qr_px), Image.NEAREST)
        sheet.paste(qr, (cx + (cell_w - qr_px) // 2, cy))
        tx, ty = cx + 24, cy + qr_px + 2
        d.text((tx, ty), r["name"], font=f_name, fill="black")
        for j, line in enumerate(wrap(d, r["what"], f_what, cell_w - 48)):
            d.text((tx, ty + 44 + j * 31), line, font=f_what, fill="#444")
        color = "#b3261e" if r["expected"] == "scam" else "#1b6e3a"
        d.text((tx, ty + 110), f"Expected: {r['expected'].upper()}", font=f_exp, fill=color)
        d.text((tx, ty + 148), r["path"], font=f_path, fill="#666")
    sheet.save(OUT / "sheet.png", dpi=(300, 300))


def sheet_html(rows: list[dict], base: str) -> None:
    cards = "\n".join(
        f"""  <figure class="card {r['expected']}">
    <img src="{r['png']}" alt="QR code for {html.escape(r['name'])}">
    <figcaption><strong>{html.escape(r['name'])}</strong><span>{html.escape(r['what'])}</span>
    <b>Expected: {r['expected'].upper()}</b><code>{html.escape(r['path'])}</code></figcaption>
  </figure>""" for r in rows)
    (OUT / "sheet.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ScanSafe demo QR sheet</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  @page {{ size: letter; margin: 0.4in; }}
  body {{ font-family: system-ui, -apple-system, Arial, sans-serif; margin: 0.4in; color: #111; background: #fff; }}
  h1 {{ font-size: 18px; margin: 0 0 2px; }}
  p.sub {{ font-size: 11px; color: #444; margin: 0 0 10px; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px 14px; }}
  .card {{ margin: 0; break-inside: avoid; border: 1px solid #ddd; border-radius: 6px; padding: 6px; }}
  .card img {{ width: 100%; max-width: 2.1in; display: block; margin: 0 auto; image-rendering: pixelated; }}
  figcaption {{ display: flex; flex-direction: column; gap: 1px; font-size: 11px; }}
  figcaption strong {{ font-size: 13px; }}
  figcaption span {{ color: #444; }}
  figcaption code {{ font-size: 9px; color: #666; word-break: break-all; }}
  .scam b {{ color: #b3261e; }} .safe b {{ color: #1b6e3a; }}
</style></head><body>
<h1>ScanSafe demo QR codes — every business is fictional</h1>
<p class="sub">Base URL: {html.escape(base)} · Expected verdict under each code (SCAM = malicious or suspicious) · HackEmory demo only, do not post in public.</p>
<div class="grid">
{cards}
</div>
</body></html>
""")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://scansafe-demo-sites.vercel.app")
    base = ap.parse_args().base.rstrip("/")
    rows = []
    for stem, name, what, path, expected in PAGES:
        url = base + path
        png = f"{stem}.png"
        make_qr(url).save(OUT / png)
        rows.append({"png": png, "name": name, "what": what, "path": path, "url": url, "expected": expected})
        print(f"{png:32s} {expected:5s} {url}")
    sheet_html(rows, base)
    sheet_png(rows)
    print(f"sheet.html + sheet.png -> {OUT}")


if __name__ == "__main__":
    main()
