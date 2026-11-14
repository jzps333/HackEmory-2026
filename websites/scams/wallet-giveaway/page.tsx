import type { Metadata } from "next";
import { label } from "../../components/CardFields";
import FictionalFooter from "../../components/FictionalFooter";

export const metadata: Metadata = { title: "Glowfin Coin Airdrop - Claim 50 GLWF", robots: { index: false } };

export default function WalletGiveawayScam() {
  const color = "#0e7490";
  const button: React.CSSProperties = { marginTop: 14, width: "100%", padding: 14, fontSize: 18, fontWeight: 800,
    color: "#fff", background: color, border: 0, borderRadius: 8 };
  return (
    <div style={{ minHeight: "100dvh", background: "#f0fbfd", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <div style={{ background: color, color: "#fff", padding: "14px 18px", fontWeight: 800, fontSize: 20 }}>
        Glowfin Coin Airdrop
      </div>
      <div style={{ background: "#d40000", color: "#fff", padding: "8px 18px", fontWeight: 700, fontSize: 14 }}>
        ⚠ Only 112 claims left. Unclaimed coins expire tonight.
      </div>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "18px" }}>
        <h1 style={{ fontSize: 26, margin: "8px 0" }}>Connect your wallet to claim 50 Glowfin Coin</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>
          You qualify for a free airdrop of <strong>50 GLWF</strong>. Connect your wallet, then confirm
          ownership with your recovery phrase so we can send your coins.
        </p>
        <button type="button" style={button}>Connect wallet</button>
        <form action="#" autoComplete="off" style={{ background: "#fff", border: "1px solid #ddd", borderRadius: 10, padding: 16, marginTop: 16 }}>
          <label style={{ ...label, marginTop: 0 }}>
            Enter your 12-word recovery phrase
            <textarea rows={4} spellCheck={false} placeholder="word1 word2 word3 ... word12" style={{ width: "100%", padding: 12,
              fontSize: 16, border: "1px solid #bbb", borderRadius: 6, marginTop: 4, boxSizing: "border-box", fontFamily: "inherit" }} />
          </label>
          <button type="button" style={button}>Claim 50 GLWF</button>
        </form>
        <p style={{ fontSize: 12, color: "#666", marginTop: 14 }}>Verified airdrop · Gas fees covered · Ends tonight</p>
      </main>
      <FictionalFooter />
    </div>
  );
}
