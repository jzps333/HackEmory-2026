# ScanSafe onboarding web app

This Next.js app implements the three-screen onboarding flow:

1. Collect a name, email address, and phone number.
2. Request the device's real location with the browser Geolocation API.
3. Offer the optional Solana wallet setup screen. Wallet connectivity is intentionally not implemented.

## Run locally

```bash
cd app
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Browser geolocation requires a secure context; `localhost` is supported for local development, while deployed environments must use HTTPS. Location permission is requested only after the user selects **Use my location**.

## Backend integration

Form data and coordinates are held in the onboarding flow's client-side state while the user moves between steps. No data is sent to or stored by the backend yet. The `OnboardingCompletionHandler` type in `src/lib/onboarding.ts` defines the callback seam for a future backend integration; pass a handler to `OnboardingFlow` to submit the completed `OnboardingData`.

The app does not connect a Solana wallet and does not call Gemini or any other AI service.

Run `npm run typecheck` and `npm run build` to validate the frontend.
