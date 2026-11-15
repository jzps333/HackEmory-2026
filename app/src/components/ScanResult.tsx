import type { ScanResult as ScanResultData } from "@/services/appServices";

const headings = {
  safe: "Looks okay",
  suspicious: "Take a closer look",
  malicious: "Don’t open this link",
};

const descriptions = {
  safe: "Our quick demo check didn’t spot a warning sign. That isn’t a guarantee—only open it if you trust where it came from.",
  suspicious: "We noticed something that could be risky. It’s safest not to share personal or payment details.",
  malicious: "This address has a strong warning sign. Don’t open it or enter any personal details.",
};

export function ScanResult({
  result,
  onContinueParking,
  onScanAgain,
}: {
  result: ScanResultData;
  onContinueParking: () => void;
  onScanAgain: () => void;
}) {
  return (
    <section className="screen-content result-screen">
      <div className={`result-mark result-${result.risk}`} aria-hidden="true">
        {result.risk === "safe" ? "✓" : result.risk === "suspicious" ? "!" : "×"}
      </div>
      <span className="eyebrow">QR CHECK RESULT</span>
      <h1>{headings[result.risk]}</h1>
      <p className="result-description">{descriptions[result.risk]}</p>
      <div className="result-address">
        <span className="eyebrow">DESTINATION</span>
        <p>{result.hostname}</p>
        <small>{result.url}</small>
      </div>
      <ul className="reason-list">
        {result.reasons.map((reason) => <li key={reason}>{reason}</li>)}
      </ul>
      {result.parkingLot && result.risk !== "malicious" && (
        <button className="primary-button full-button" type="button" onClick={onContinueParking}>
          Continue to parking
        </button>
      )}
      <button className="secondary-button full-button" type="button" onClick={onScanAgain}>
        Scan another code
      </button>
      <p className="fine-print">This is a demo check, not a guarantee of safety. We never open links for you.</p>
    </section>
  );
}
