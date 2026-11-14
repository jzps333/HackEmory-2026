/**
 * Card-payment fields for the deliberately scammy ScanSafe demo pages (fictional brands only).
 * Inert like ScamOffer: no `name` on any input, the button is type="button", nothing is sent.
 */
export const field: React.CSSProperties = { width: "100%", padding: "12px", fontSize: 16, border: "1px solid #bbb",
  borderRadius: 6, marginTop: 4, boxSizing: "border-box", background: "#fff", color: "#111" };
export const label: React.CSSProperties = { display: "block", marginTop: 14, fontWeight: 700, fontSize: 14 };

export default function CardFields({ color, button, withEmail = false }: {
  color: string; button: string; withEmail?: boolean;
}) {
  return (
    <form action="#" autoComplete="off" style={{ background: "#fff", border: "1px solid #ddd", borderRadius: 10, padding: 16 }}>
      {withEmail && <label style={label}>Email address<input style={field} type="email" placeholder="you@example.com" /></label>}
      <label style={label}>Name on card<input style={field} placeholder="Full name" /></label>
      <label style={label}>Card number<input style={field} inputMode="numeric" placeholder="1234 5678 9012 3456" /></label>
      <div style={{ display: "flex", gap: 10 }}>
        <label style={{ ...label, flex: 1 }}>Expiry<input style={field} placeholder="MM/YY" /></label>
        <label style={{ ...label, flex: 1 }}>CVV<input style={field} inputMode="numeric" placeholder="123" /></label>
      </div>
      <label style={label}>Billing ZIP code<input style={field} inputMode="numeric" placeholder="30030" /></label>
      <button type="button" style={{ marginTop: 18, width: "100%", padding: 14, fontSize: 18, fontWeight: 800,
        color: "#fff", background: color, border: 0, borderRadius: 8 }}>
        {button}
      </button>
    </form>
  );
}
