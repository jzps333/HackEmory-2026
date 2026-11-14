import type { Metadata } from "next";
import CardFields from "../../components/CardFields";
import FictionalFooter from "../../components/FictionalFooter";

export const metadata: Metadata = { title: "Kestrel Tollway - Unpaid Toll Notice", robots: { index: false } };

export default function UnpaidTollScam() {
  const color = "#0f3b6e";
  return (
    <div style={{ minHeight: "100dvh", background: "#f6f7f9", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <div style={{ background: color, color: "#fff", padding: "14px 18px", fontWeight: 800, fontSize: 20 }}>
        Kestrel Tollway · Toll Services
      </div>
      <div style={{ background: "#d40000", color: "#fff", padding: "8px 18px", fontWeight: 700, fontSize: 14 }}>
        ⚠ FINAL NOTICE: pay today to avoid a $50.00 late fee and suspension of your vehicle registration.
      </div>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "18px" }}>
        <h1 style={{ fontSize: 26, margin: "8px 0" }}>Unpaid toll: $4.99</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>
          Our records show an unpaid toll for your vehicle. Pay <strong>$4.99 today</strong> or a
          <strong> $50 late fee</strong> will be added and your case sent to collections.
        </p>
        <div style={{ border: "1px solid #ddd", background: "#fff", borderRadius: 10, padding: 14, marginBottom: 14, fontSize: 15 }}>
          <div>Notice no. KT-48213-07</div>
          <div style={{ marginTop: 4 }}>Amount due today: <strong>$4.99</strong></div>
          <div style={{ marginTop: 4, color: "#b3261e", fontWeight: 700 }}>Due: today, 11:59 PM</div>
        </div>
        <CardFields color={color} button="Pay $4.99 now" withEmail />
        <p style={{ fontSize: 12, color: "#666", marginTop: 14 }}>Secure payment · Avoid the $50 late fee</p>
      </main>
      <FictionalFooter />
    </div>
  );
}
