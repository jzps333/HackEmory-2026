# ScanSafe

ScanSafe is a mobile-first QR safety and parking demo built with Next.js, React, and TypeScript.

## What works in this demo

- Three-step onboarding for name, email, and phone, followed by optional wallet information and a location choice.
- Home screen with QR safety and parking actions plus Home, Scan, Parking, and Profile navigation.
- QR camera scanning in browsers that provide `BarcodeDetector`, with manual link entry as a fallback.
- Local mock QR results for safe, suspicious, and malicious examples. Links are checked in the browser and are never opened. Demo examples are available in the scanner.
- Parking QR parsing, local vehicle and license plate storage, duration and price estimate, six-digit simulated verification, and a local confirmation.
- Profile, vehicles, and parking session data saved in browser local storage.

This project does not contact a backend, send SMS, process a payment, connect Phantom, or perform a live threat-intelligence scan. The verification demo code is `123456`; no message is sent. Example QR results are demonstrations only and are not security guarantees.

## Run locally

```bash
cd app
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Camera and location access require browser permission and a secure context; `localhost` is supported for local development and deployed environments must use HTTPS. If camera QR detection is unavailable, paste a link or choose a demo link instead.

Run `npm run typecheck` and `npm run build` to validate the app.

## App structure

Screen components are in `src/components/`, with flow state coordinated by `ScanSafeApp.tsx`. Local persistence, the storage migration, QR demo checks, sample parking lots, pricing, and session creation live in `src/services/appServices.ts`.

The service module is the integration seam for future server-backed QR checks, parking data, and verification. No backend, SMS, wallet, or payment service is configured. Existing `scansafe-app-v1` data is migrated when it can be read.
