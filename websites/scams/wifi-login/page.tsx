import type { Metadata } from "next";
import { field, label } from "../../components/CardFields";
import FictionalFooter from "../../components/FictionalFooter";

export const metadata: Metadata = { title: "Bramblewick Café Free Wi-Fi - Sign In", robots: { index: false } };

export default function WifiLoginScam() {
  const color = "#7c2d12";
  return (
    <div style={{ minHeight: "100dvh", background: "#fbf7f2", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <div style={{ background: color, color: "#fff", padding: "14px 18px", fontWeight: 800, fontSize: 20 }}>
        Bramblewick Café · Free Wi-Fi
      </div>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "18px" }}>
        <h1 style={{ fontSize: 26, margin: "8px 0" }}>Get online</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>
          Sign in with your email and password to get online. Use the same password as your email
          account so we can verify it is really you.
        </p>
        <form action="#" autoComplete="off" style={{ background: "#fff", border: "1px solid #ddd", borderRadius: 10, padding: 16 }}>
          <label style={label}>Email address<input style={field} type="email" placeholder="you@example.com" /></label>
          <label style={label}>Email password<input style={field} type="password" placeholder="Password" /></label>
          <button type="button" style={{ marginTop: 18, width: "100%", padding: 14, fontSize: 18, fontWeight: 800,
            color: "#fff", background: color, border: 0, borderRadius: 8 }}>
            Sign in and connect
          </button>
        </form>
        <p style={{ fontSize: 12, color: "#666", marginTop: 14 }}>Free Wi-Fi for Bramblewick Café guests · Session expires in 15 minutes</p>
      </main>
      <FictionalFooter />
    </div>
  );
}
