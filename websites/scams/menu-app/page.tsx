import type { Metadata } from "next";
import FictionalFooter from "../../components/FictionalFooter";

export const metadata: Metadata = { title: "Lumen Bistro - Download Our App To See The Menu", robots: { index: false } };

// The "app" is a harmless placeholder text file (app/public/demo/lumen-menu.apk). The ScanSafe
// sandbox never clicks download links, so the page also starts the download on its own after a
// second (meta refresh, no script), which is what a real scam kit does; the sandbox records it.
const APK = "/demo/lumen-menu.apk";

export default function MenuAppScam() {
  const color = "#1e3a5f";
  return (
    <div style={{ minHeight: "100dvh", background: "#f7f5f0", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <meta httpEquiv="refresh" content={`1;url=${APK}`} />
      <div style={{ background: color, color: "#fff", padding: "14px 18px", fontWeight: 800, fontSize: 20 }}>
        Lumen Bistro
      </div>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "18px", textAlign: "center" }}>
        <h1 style={{ fontSize: 26, margin: "8px 0" }}>Download our app to see the menu</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>
          Our menu is only available in the Lumen Bistro app. Your download starts automatically.
          If it doesn&apos;t, tap the button below, then open the file and allow installs from unknown sources.
        </p>
        <a href={APK} download style={{ display: "block", marginTop: 18, padding: 14, fontSize: 18, fontWeight: 800,
          color: "#fff", background: color, borderRadius: 8, textDecoration: "none" }}>
          Download the menu app (.apk)
        </a>
        <p style={{ fontSize: 12, color: "#666", marginTop: 14 }}>Android only · 4.2 MB · Required to order</p>
      </main>
      <FictionalFooter />
    </div>
  );
}
