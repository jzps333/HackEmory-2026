# Web app (Person 4)

Next.js PWA, deployed on Vercel at `scansafe.nyc` (backup: `scansafe.vercel.app`).
The camera only works over HTTPS.

- **Scan page:** camera QR scanner (`html5-qrcode`) → `POST /scan` → results screen.
- **Results:** big verdict, `explanation`, Jev score, screenshots, buttons:
  Continue / Pay (devnet) / Nevermind / Report scam (pre-fills an FTC report the user submits).
- **Map page:** Leaflet + OpenStreetMap + markercluster, pins from Typesense.
- **Accessibility (Coder for Good):** large text, high contrast, big buttons, labels on every
  control for VoiceOver, plain words ("fake website", not "phishing"), read-aloud option.
- **Solana Pay:** `api/scan.py` already parses `solana:` QR codes and checks the wallet against
  `KNOWN_MERCHANTS`. Put your devnet demo wallets there. Devnet only; user approves every payment.

Build against `shared/mock_safe.json` and `shared/mock_malicious.json` until the sandbox is live.
