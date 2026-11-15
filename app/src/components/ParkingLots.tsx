import type { ParkingLot } from "@/lib/appStorage";
import { PARKING_LOTS } from "@/services/appServices";

function formatRate(rate: number) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(rate);
}

export function ParkingLots({
  preferredLot,
  onSelect,
}: {
  preferredLot: ParkingLot | null;
  onSelect: (lot: ParkingLot) => void;
}) {
  return (
    <section className="screen-content">
      <div className="screen-heading">
        <span className="eyebrow">PARKING</span>
        <h1>Find a nearby garage.</h1>
        <p>Choose a lot to see your parking options.</p>
      </div>
      {preferredLot && (
        <p className="context-note">From your QR scan. Check the lot details before continuing.</p>
      )}
      <div className="lot-map-preview" aria-label="Sample map preview">
        <span className="map-road road-one" />
        <span className="map-road road-two" />
        <span className="map-road road-three" />
        <span className="lot-map-pin">P</span>
        <span className="map-distance">Sample map · nearby lots</span>
      </div>
      <div className="lot-list">
        {PARKING_LOTS.map((lot) => (
          <button
            type="button"
            className={`lot-option${preferredLot?.id === lot.id ? " lot-preferred" : ""}`}
            key={lot.id}
            onClick={() => onSelect(lot)}
          >
            <span className="lot-symbol" aria-hidden="true">P</span>
            <span className="lot-copy">
              <strong>{lot.name}</strong>
              <small>{lot.address}</small>
              <small>{formatRate(lot.rate)} per hour</small>
            </span>
            <span className="row-arrow" aria-hidden="true">›</span>
          </button>
        ))}
      </div>
      <p className="fine-print">Lot names and prices are sample data for this demo.</p>
    </section>
  );
}
