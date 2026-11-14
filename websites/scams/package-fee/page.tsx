import type { Metadata } from "next";
import CardFields, { field, label } from "../../components/CardFields";
import FictionalFooter from "../../components/FictionalFooter";

export const metadata: Metadata = { title: "Swiftlark Parcel - Your Package Is On Hold", robots: { index: false } };

export default function PackageFeeScam() {
  const color = "#c2410c";
  return (
    <div style={{ minHeight: "100dvh", background: "#fafafa", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <div style={{ background: color, color: "#fff", padding: "14px 18px", fontWeight: 800, fontSize: 20 }}>
        Swiftlark Parcel
      </div>
      <div style={{ background: "#d40000", color: "#fff", padding: "8px 18px", fontWeight: 700, fontSize: 14 }}>
        ⚠ Your package will be returned to sender in 24 hours if the fee is not paid.
      </div>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "18px" }}>
        <h1 style={{ fontSize: 26, margin: "8px 0" }}>Your package is on hold</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>
          We tried to deliver your package but the address was incomplete. Pay the
          <strong> $1.99 redelivery fee</strong> and confirm your address to schedule a new delivery.
        </p>
        <div style={{ border: "1px solid #ddd", background: "#fff", borderRadius: 10, padding: 14, marginBottom: 14, fontSize: 15 }}>
          <div>Tracking no. SL 7720 4419 0063</div>
          <div style={{ marginTop: 4 }}>Status: <strong style={{ color: "#b3261e" }}>On hold, fee unpaid</strong></div>
          <div style={{ marginTop: 4 }}>Redelivery fee: <strong>$1.99</strong></div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #ddd", borderRadius: 10, padding: "2px 16px 16px", marginBottom: 14 }}>
          <label style={label}>Full name<input style={field} placeholder="Full name" /></label>
          <label style={label}>Street address<input style={field} placeholder="123 Main St" /></label>
          <label style={label}>Phone number<input style={field} type="tel" placeholder="(555) 555-0100" /></label>
        </div>
        <CardFields color={color} button="Pay $1.99 and redeliver" />
        <p style={{ fontSize: 12, color: "#666", marginTop: 14 }}>Swiftlark Parcel delivery services · Secure payment</p>
      </main>
      <FictionalFooter />
    </div>
  );
}
