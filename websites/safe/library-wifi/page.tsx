import type { Metadata } from "next";
import FictionalFooter from "../../components/FictionalFooter";

export const metadata: Metadata = { title: "Fernhollow Public Library Wi-Fi", robots: { index: false } };

// SAFE counterpart to the Wi-Fi login scam: free guest Wi-Fi that asks for nothing.
export default function LibraryWifi() {
  const color = "#1b6e3a";
  return (
    <div style={{ minHeight: "100dvh", background: "#f5faf6", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <div style={{ background: color, color: "#fff", padding: "14px 18px", fontWeight: 800, fontSize: 20 }}>
        Fernhollow Public Library
      </div>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "18px" }}>
        <h1 style={{ fontSize: 26, margin: "8px 0" }}>Free library Wi-Fi</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>
          Tap <strong>Connect</strong>, no password needed. Our guest Wi-Fi is free for everyone and
          never asks for your email, password, or card.
        </p>
        <ol style={{ fontSize: 16, lineHeight: 1.6, paddingLeft: 22 }}>
          <li>Open your phone&apos;s Wi-Fi settings.</li>
          <li>Choose the network <strong>Fernhollow-Library-Guest</strong>.</li>
          <li>Tap Connect. That&apos;s it.</li>
        </ol>
        <div style={{ border: "1px solid #cfe3d5", background: "#fff", borderRadius: 10, padding: 14, fontSize: 15, lineHeight: 1.5 }}>
          <strong>Hours</strong><br />
          Mon to Thu 9 AM to 8 PM · Fri and Sat 9 AM to 5 PM · Sun 1 PM to 5 PM<br />
          Need help? Ask at the front desk.
        </div>
      </main>
      <FictionalFooter />
    </div>
  );
}
