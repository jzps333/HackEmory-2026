import type { ParkingSession } from "@/lib/appStorage";

function formatDate(value: number) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function ParkingConfirmation({
  session,
  onDone,
}: {
  session: ParkingSession;
  onDone: () => void;
}) {
  return (
    <section className="screen-content confirmation-screen">
      <div className="success-mark" aria-hidden="true">✓</div>
      <span className="eyebrow">ALL SET</span>
      <h1>You’re parked.</h1>
      <p className="result-description">Your demo parking session is saved on this device.</p>
      <dl className="session-details">
        <div><dt>Location</dt><dd>{session.lot.name}</dd></div>
        <div><dt>Address</dt><dd>{session.lot.address}</dd></div>
        <div><dt>Vehicle</dt><dd>{session.vehicle.nickname || session.vehicle.type || "Vehicle"}</dd></div>
        <div><dt>License plate</dt><dd>{session.vehicle.plate}</dd></div>
        <div><dt>Started</dt><dd>{formatDate(session.startedAt)}</dd></div>
        <div><dt>Ends</dt><dd>{formatDate(session.endsAt)}</dd></div>
        <div className="session-total"><dt>Estimated price</dt><dd>{new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(session.price)}</dd></div>
      </dl>
      <button className="primary-button full-button" type="button" onClick={onDone}>Done</button>
      <p className="fine-print">This is a sample confirmation—not a real parking reservation or payment.</p>
    </section>
  );
}
