"use client";

import { useRef, useState } from "react";
import { DeviceStatusBar } from "@/components/DeviceStatusBar";
import { requestCurrentLocation } from "@/lib/geolocation";
import type { Coordinates } from "@/lib/onboarding";

export function LocationPermission({
  onComplete,
}: {
  onComplete: (location: Coordinates | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  async function requestLocation() {
    const currentRequest = ++requestId.current;
    setBusy(true);
    setError("");
    try {
      const location = await requestCurrentLocation();
      if (currentRequest === requestId.current) onComplete(location);
    } catch (reason) {
      if (currentRequest === requestId.current) {
        setError(reason instanceof Error ? reason.message : "We couldn’t access your location.");
      }
    } finally {
      if (currentRequest === requestId.current) setBusy(false);
    }
  }

  function continueWithoutLocation() {
    requestId.current += 1;
    onComplete(null);
  }

  return (
    <main className="app-shell setup-screen">
      <DeviceStatusBar />
      <header className="topbar">
        <span className="wordmark"><span className="brand-icon" aria-hidden="true">S</span>ScanSafe</span>
        <span className="topbar-note">One last choice</span>
      </header>
      <section className="setup-content">
        <div className="location-map-preview" aria-hidden="true">
          <span className="map-current-pin">⌖</span>
          <span className="map-distance">Map preview</span>
        </div>
        <span className="eyebrow">LOCATION</span>
        <h1>Allow location to find nearby parking.</h1>
        <p className="supporting-copy">
          We’ll use your location to show nearby garages and match the lot on a parking QR code.
        </p>
        <ul className="location-benefits">
          <li>See garages and walking distance nearby</li>
          <li>Start and stop a parking session accurately</li>
          <li>Location stays on this device in the demo</li>
        </ul>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button full-button" type="button" onClick={requestLocation} disabled={busy}>
          {busy ? "Checking location…" : "Allow location"}
        </button>
        <button className="secondary-button full-button location-skip" type="button" onClick={continueWithoutLocation}>
          Continue without location
        </button>
      </section>
    </main>
  );
}
