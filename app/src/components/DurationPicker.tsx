"use client";

import { useState } from "react";
import type { ParkingLot, Vehicle } from "@/lib/appStorage";
import { calculateParkingPrice } from "@/services/appServices";

const choices = [
  { minutes: 30, label: "30 min" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
  { minutes: 180, label: "3 hours" },
];

export function DurationPicker({
  lot,
  vehicle,
  onContinue,
}: {
  lot: ParkingLot;
  vehicle: Vehicle;
  onContinue: (minutes: number) => void;
}) {
  const [custom, setCustom] = useState(false);
  const [minutes, setMinutes] = useState(60);
  const [customHours, setCustomHours] = useState("4");
  const [error, setError] = useState("");
  const duration = custom ? Number(customHours) * 60 : minutes;
  const price = calculateParkingPrice(lot, duration);
  const startsAt = new Date();
  const endsAt = new Date(startsAt.getTime() + duration * 60_000);
  const time = (date: Date) => date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <section className="screen-content">
      <div className="screen-heading">
        <span className="eyebrow">{lot.name.toUpperCase()}</span>
        <h1>How long are you staying?</h1>
      </div>
      <div className="duration-options">
        {choices.map((choice) => (
          <button
            className={`duration-choice${!custom && minutes === choice.minutes ? " selected" : ""}`}
            type="button"
            key={choice.minutes}
            aria-pressed={!custom && minutes === choice.minutes}
            onClick={() => {
              setMinutes(choice.minutes);
              setCustom(false);
              setError("");
            }}
          >
            {choice.label}
          </button>
        ))}
      </div>
      <button
        className={`duration-choice custom-choice${custom ? " selected" : ""}`}
        type="button"
        aria-pressed={custom}
        onClick={() => setCustom(true)}
      >
        Choose another time
      </button>
      {custom && (
        <label className="field custom-duration">
          <span>Hours (1 to 12)</span>
          <input
            inputMode="numeric"
            type="number"
            min="1"
            max="12"
            step="0.5"
            value={customHours}
            onChange={(event) => {
              setCustomHours(event.target.value);
              setError("");
            }}
          />
        </label>
      )}
      <dl className="duration-summary">
        <div><dt>Vehicle</dt><dd>{vehicle.nickname || vehicle.type || "Vehicle"}</dd></div>
        <div><dt>Plate</dt><dd>{vehicle.plate}</dd></div>
        <div><dt>Starts</dt><dd>{time(startsAt)}</dd></div>
        <div><dt>Ends</dt><dd>{time(endsAt)}</dd></div>
      </dl>
      <div className="price-summary">
        <span>Estimated total</span>
        <strong>{new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(price)}</strong>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button
        className="primary-button full-button"
        type="button"
        onClick={() => {
          if (!Number.isFinite(duration) || duration < 30 || duration > 720) {
            setError("Choose a time between 30 minutes and 12 hours.");
            return;
          }
          onContinue(duration);
        }}
      >
        Continue
      </button>
      <p className="fine-print">Price is an estimate based on sample rates. No payment is taken.</p>
    </section>
  );
}
