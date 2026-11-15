# Web app (Person 4)

ScanSafe's mobile-first web app (Next.js App Router + TypeScript, installable as a PWA).
Deploys on Vercel at `scansafe.nyc` (backup: `scansafe.vercel.app`). The camera only works over HTTPS
(or `localhost`).

## Run it

```bash
cd app
npm install
npm run dev            # http://localhost:3000
npm run build && npm start   # production build
```

With **no** `NEXT_PUBLIC_API_URL` the app runs in **demo mode** on the mocks in `src/mock/`
(copies of `shared/mock_*.json`): a pasted `solana:` link gives the safe payment result, anything
else gives the scam result. Map and stats fall back to sample Atlanta data. To use the real backend:

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local   # no trailing slash
```

That is the only setting. No keys or secrets belong in this folder.

## Deploy (Vercel)

1. Import the GitHub repo in Vercel. **Root Directory = `app`** (framework preset: Next.js).
2. Environment variable: `NEXT_PUBLIC_API_URL` = backend base URL (e.g. `https://api.scansafe.nyc`).
   It is baked in at build time, so redeploy after changing it.
3. Add the domain `scansafe.nyc` under Project → Domains.

## Pages

- `/` **Scan**: big "Scan a QR code" button (camera via `html5-qrcode`) or paste a link. Location
  sharing is an opt-in switch, off by default, rounded to ~100 m on the phone.
  Then the **results view**: verdict banner (icon + words, not just color), explanation in large
  text, "Read aloud" (speechSynthesis, rate 0.85), "94% likely a scam", screenshots, "Where this
  link really goes" (collapsed), and buttons: Open link (safe only), Pay test SOL (verified Solana
  Pay only, with a devnet confirm dialog), Nevermind, Report scam (confirm first, then a copyable
  FTC summary + link to reportfraud.ftc.gov that the user submits themselves).
- `/map`: Leaflet + OpenStreetMap, clustered red pins, popups, search box, plus a text list of the
  same pins for screen readers. Leaflet loads client-side only.
- `/dashboard`: totals, a 24-hour bar chart (plain divs + data table), most common scam types.

## Backend endpoints it calls

| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/scan` | `{url, lat?, lng?}` | `ScanResult` (`api/schema.py`) |
| POST | `/pay` | `{scan_id}` | `{tx_signature, explorer_url?}` |
| POST | `/report` | full `ScanResult` | any 2xx JSON (e.g. `{ok: true}`) |
| GET | `/pins` | `?lat=&lng=&radius_km=5` | `Pin[]`, `{pins: Pin[]}`, or raw Typesense `{hits:[{document}]}` |
| GET | `/search` | `?q=` | same as `/pins` |
| GET | `/stats/summary` | | `{total_scans, safe, suspicious, malicious, avg_scan_ms, top_scam_types:[{scam_type,count}]}` |
| GET | `/stats/hourly` | `?hours=24` | `[{hour, total, malicious}]` (`hour` = ISO string or unix seconds), or `{hourly: [...]}` |
| GET | `/screenshots/<name>` | | image, used when a screenshot is a plain file name (data: and http URLs are used as-is) |

`Pin` = `{id?, url, domain, scam_type, jev_score, explanation, location: [lat, lng], reported_at}`
(the Typesense `scam_pins` document). If `/pins`, `/search` or `/stats/*` fail, the page shows
sample data with a "Demo" badge instead of breaking.

## Accessibility (Coder for Good)

18px base font, high contrast, buttons at least 48px tall (most are 56px), labels on every control,
skip link, visible focus ring, native `<dialog>` for confirmations, live regions for progress and
results, `prefers-reduced-motion` respected, plain words ("fake website", never "phishing").

## Files

- `src/app/` pages, layout, `manifest.ts` (web manifest), `globals.css`
- `src/components/` Scanner, ResultView, ConfirmDialog, VerdictIcon, ScamMap, Nav
- `src/lib/` `api.ts` (all backend calls + demo fallbacks), `types.ts` (mirrors `api/schema.py`), `labels.ts`, `mockData.ts`
- `public/icons/` home-screen icons, `public/mock/` sample screenshots for demo mode
