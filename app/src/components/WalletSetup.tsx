import { DeviceStatusBar } from "@/components/DeviceStatusBar";

export function WalletSetup({ onSkip }: { onSkip: () => void }) {
  return (
    <main className="app-shell setup-screen">
      <DeviceStatusBar />
      <header className="topbar">
        <span className="wordmark"><span className="brand-icon" aria-hidden="true">S</span>ScanSafe</span>
        <span className="topbar-note">Optional</span>
      </header>
      <section className="setup-content">
        <div className="setup-art wallet-art" aria-hidden="true">◈</div>
        <span className="eyebrow">OPTIONAL</span>
        <h1>Add Solana parking passes to your wallet.</h1>
        <p className="supporting-copy">
          Keep your parking details close. Wallet support will be available in a future version.
        </p>
        <div className="wallet-options" aria-label="Wallet options not available in this demo">
          <div className="wallet-option">
            <span className="wallet-option-icon" aria-hidden="true">♢</span>
            <span><strong>Connect Phantom</strong><small>Not available in this demo</small></span>
            <span aria-hidden="true">›</span>
          </div>
          <div className="wallet-option">
            <span className="wallet-option-icon wallet-link-icon" aria-hidden="true">↗</span>
            <span><strong>Use a wallet address</strong><small>Wallet details aren’t collected</small></span>
            <span aria-hidden="true">›</span>
          </div>
        </div>
        <p className="wallet-notice">No wallet is connected, and you can use the app without one.</p>
        <button className="primary-button full-button" type="button" onClick={onSkip}>Skip for now</button>
      </section>
    </main>
  );
}
