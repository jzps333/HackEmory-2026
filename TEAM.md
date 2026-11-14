# Team plan

Submit on Devpost by **7:00 AM Sunday** (hard deadline 8:00 AM EST).

## Roles

| Person | Owns | Prizes it wins |
|---|---|---|
| **1. Sandbox** | Sandbox Vultr server, `sandbox/` (Docker + Playwright), screenshots, redirect chain, `api/scan.py` verdict | Security track, Vultr, Gemini |
| **2. Chert** | `chert/` FaceTime agent (reads QR from camera, calls `/scan`, speaks verdict), iMessage follow-up with buttons | Chert ($400 + interviews) |
| **3. Data** | `data/` Typesense collection + geosearch + "flagged nearby", Tiger Data hypertable + continuous aggregate dashboard, Leaflet map | Typesense, Tiger Data |
| **4. App + payments** | `app/` Next.js PWA (camera scanner, results screen, map page), Solana Pay parsing + devnet payment, accessibility polish | Solana, Coder for Good |

Everyone: code in **Cursor**, keep the **Entire CLI** running, push small commits often
(Grok Bot reviews every push).

## The shared contract

Everything passes around one JSON shape. See `shared/scan_result.example.json` and the mocks in
`shared/mock_safe.json` / `shared/mock_malicious.json`. The Pydantic version is `api/schema.py`.

- Person 1 **produces** it (`POST /scan`).
- Person 2 **speaks and sends** it.
- Person 3 **stores** it (Typesense + Tiger Data).
- Person 4 **displays** it.

Change the shape only after telling the whole team.

## Checkpoints

| Time | Goal |
|---|---|
| **Midnight** | End to end works, even if ugly: scan → verdict → message → pin |
| **3 AM** | Feature freeze. Bugs and polish only |
| **5 AM** | Record the 2-minute demo video while everything works |
| **7 AM** | Devpost submitted, every side challenge opted in |

## Devpost checklist

- [ ] Main track: **Security**
- [ ] Opt in: Chert, Coder for Good, Typesense, MLH Gemini, Vultr, Entire, A-Team (SpaceXSI raffle), Tiger Data, Solana, GoDaddy, DEV
- [ ] Writeup names every tool, including all Entire features used and Cursor + Grok Bot
- [ ] Screenshots: Entire session + Trails score, Grok Bot review, scam map, dashboard
- [ ] Link the GitHub repo and the demo video
- [ ] README credits every framework (event rule)

## Accounts (keys go in your own `.env`, never in chat or git)

Jev (OpenRouter key), Gemini, Vultr, Chert, LiveKit, Typesense, Tiger Data, Solana devnet wallet.
