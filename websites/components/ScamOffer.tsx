import FictionalFooter from "./FictionalFooter";

/**
 * A deliberately scam-looking page for the ScanSafe demo (fictional brands only).
 * Inert: inputs have no `name`, the form posts nowhere, there are no scripts, so nothing typed
 * can ever leave the browser. It exists so the ScanSafe sandbox has a realistic scam to catch.
 */
export default function ScamOffer({ brand, color, headline, prize, deadline }: {
  brand: string; color: string; headline: string; prize: string; deadline: string;
}) {
  const field: React.CSSProperties = { width: "100%", padding: "12px", fontSize: 16, border: "1px solid #bbb",
    borderRadius: 6, marginTop: 4, boxSizing: "border-box" };
  const label: React.CSSProperties = { display: "block", marginTop: 14, fontWeight: 700, fontSize: 14 };
  return (
    <div style={{ minHeight: "100dvh", background: "#fafafa", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <div style={{ background: color, color: "#fff", padding: "14px 18px", fontWeight: 800, fontSize: 20 }}>
        {brand} Rewards
      </div>
      <div style={{ background: "#d40000", color: "#fff", padding: "8px 18px", fontWeight: 700, fontSize: 14 }}>
        ⚠ Your reward expires in {deadline}. Verify now to avoid losing it.
      </div>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "18px" }}>
        <h1 style={{ fontSize: 26, margin: "8px 0" }}>{headline}</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>
          Congratulations! You were selected for <strong>{prize}</strong>. To confirm you are the
          account owner, verify your card below. A $1.00 verification hold will be refunded.
        </p>
        <form action="#" autoComplete="off" style={{ background: "#fff", border: "1px solid #ddd", borderRadius: 10, padding: 16 }}>
          <label style={label}>Email address<input style={field} type="email" placeholder="you@example.com" /></label>
          <label style={label}>Card number<input style={field} inputMode="numeric" placeholder="1234 5678 9012 3456" /></label>
          <div style={{ display: "flex", gap: 10 }}>
            <label style={{ ...label, flex: 1 }}>Expiry<input style={field} placeholder="MM/YY" /></label>
            <label style={{ ...label, flex: 1 }}>CVV<input style={field} inputMode="numeric" placeholder="123" /></label>
          </div>
          <label style={label}>Account password<input style={field} type="password" placeholder="Password" /></label>
          <button type="button" style={{ marginTop: 18, width: "100%", padding: 14, fontSize: 18, fontWeight: 800,
            color: "#fff", background: color, border: 0, borderRadius: 8 }}>
            Verify &amp; claim my reward
          </button>
        </form>
        <p style={{ fontSize: 12, color: "#666", marginTop: 14 }}>Secure verification · 256-bit protected · Offer ends {deadline}</p>
      </main>
      <FictionalFooter />
    </div>
  );
}
