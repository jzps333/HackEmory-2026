import type { ParkingSession } from "@/lib/appStorage";

export function Dashboard({
  firstName,
  latestSession,
  onScan,
  onParking,
  onViewAll,
}: {
  firstName: string;
  latestSession: ParkingSession | null;
  onScan: () => void;
  onParking: () => void;
  onViewAll: () => void;
}) {
  return (
    <section className="screen-content dashboard-screen">
      <div className="dashboard-greeting">
        <div className="avatar-mark">{firstName.slice(0, 1).toUpperCase()}</div>
        <div>
          <span className="eyebrow">GOOD TO SEE YOU</span>
          <h1>Hi, {firstName}.</h1>
        </div>
        <span className="notification-mark" aria-hidden="true">♧</span>
      </div>
      <button className="hero-action scan-hero" onClick={onScan} type="button">
        <span className="hero-eyebrow">SCAN A QR CODE</span>
        <span className="hero-title">Check a code before you sign in.</span>
        <span className="hero-subtitle">See where a QR code leads before you open it.</span>
        <span className="hero-cta">Open scanner <span aria-hidden="true">⌕</span></span>
      </button>
      <button className="action-row parking-action" onClick={onParking} type="button">
        <span className="action-icon" aria-hidden="true">P</span>
        <span className="action-copy">
          <strong>Parking</strong>
          <small>Choose a lot, vehicle, and time for your demo session.</small>
          <em>3 sample garages</em>
        </span>
        <span className="row-arrow" aria-hidden="true">›</span>
      </button>
      <div className="recent-heading">
        <h2>Recent</h2>
        <button className="recent-see-all" type="button" onClick={onViewAll}>See all</button>
      </div>
      {latestSession ? (
        <section className="recent-session">
          <span className="recent-icon" aria-hidden="true">P</span>
          <span className="recent-copy">
            <strong>{latestSession.lot.name}</strong>
            <small>{latestSession.vehicle.plate} · ends {new Date(latestSession.endsAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</small>
          </span>
        </section>
      ) : (
        <p className="empty-recent">Your recent parking sessions will show up here.</p>
      )}
    </section>
  );
}
