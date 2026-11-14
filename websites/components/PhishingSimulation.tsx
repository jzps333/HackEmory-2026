"use client";

import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

interface Props {
  path: string;
  scenario: string;
  theme: "cafe" | "arcade";
  offer: string;
  hook: string;
}

export default function PhishingSimulation({ path, scenario, theme, offer, hook }: Props) {
  const [url, setUrl] = useState(`https://scansafe.nyc${path}?demo=phishing&scenario=${scenario}`);

  useEffect(() => {
    const query = new URLSearchParams({ demo: "phishing", scenario });
    setUrl(`${window.location.origin}${path}?${query.toString()}`);
  }, [path, scenario]);

  return (
    <section className={`phishing-sim phishing-sim-${theme}`} aria-labelledby={`${scenario}-heading`}>
      <div className="phishing-sim-copy">
        <p className="phishing-sim-label"><span aria-hidden="true">!</span> Training simulation · not a real offer</p>
        <h2 id={`${scenario}-heading`}>{offer}</h2>
        <p>{hook}</p>
        <p className="phishing-sim-safety">
          This demo highlights urgency and account-verification language. There are no forms,
          credentials, payment requests, data collection, or off-site redirects.
        </p>
        <a href={url}>{url}</a>
      </div>
      <div className="phishing-sim-qr">
        <QRCodeSVG value={url} size={150} level="M" title={`Demo QR code for ${scenario} phishing-awareness simulation`} />
        <span>SCAN TO TEST</span>
      </div>
    </section>
  );
}
