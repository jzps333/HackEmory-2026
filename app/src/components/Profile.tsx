import type { AppData } from "@/lib/appStorage";

export function Profile({ data }: { data: AppData }) {
  const { user, vehicles, sessions } = data;
  return (
    <section className="screen-content">
      <div className="screen-heading">
        <span className="eyebrow">YOUR ACCOUNT</span>
        <h1>Profile</h1>
        <p>Your information is stored only in this browser.</p>
      </div>
      <section className="profile-section">
        <h2>Contact</h2>
        <dl className="profile-details">
          <div><dt>Name</dt><dd>{user.firstName} {user.lastName}</dd></div>
          <div><dt>Email</dt><dd>{user.email}</dd></div>
          <div><dt>Phone</dt><dd>{user.phone}</dd></div>
          <div><dt>Location</dt><dd>{data.location ? "Allowed on this device" : "Not shared"}</dd></div>
        </dl>
      </section>
      <section className="profile-section">
        <h2>Vehicles <span>{vehicles.length}</span></h2>
        {vehicles.length ? (
          <ul className="profile-list">
            {vehicles.map((vehicle) => (
              <li key={vehicle.id}>
                <strong>{vehicle.nickname || vehicle.plate}</strong>
                <span>{vehicle.nickname ? vehicle.plate : vehicle.type || "Vehicle"}</span>
              </li>
            ))}
          </ul>
        ) : <p className="empty-note">Vehicles you add during parking will appear here.</p>}
      </section>
      <section className="profile-section">
        <h2>Parking sessions <span>{sessions.length}</span></h2>
        {sessions.length ? (
          <ul className="profile-list">
            {[...sessions].reverse().map((session) => (
              <li key={session.id}>
                <strong>{session.lot.name}</strong>
                <span>{session.vehicle.plate} · {new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(session.price)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="empty-note">Confirmed parking sessions will show up here.</p>}
      </section>
      <section className="privacy-section">
        <h2>Private by default</h2>
        <ul>
          <li>✓ Your details stay on this device.</li>
          <li>✓ Scanned links never open automatically.</li>
          <li>✓ No messages or payments are sent.</li>
        </ul>
      </section>
    </section>
  );
}
