"use client";

import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

export default function ShareQr() {
  const [url, setUrl] = useState("https://scansafe.nyc/cities");

  useEffect(() => {
    setUrl(`${window.location.origin}/cities`);
  }, []);

  return (
    <section className="city-share" aria-labelledby="share-heading">
      <div>
        <p className="city-eyebrow">Take the city tour</p>
        <h2 id="share-heading">Share this page</h2>
        <p>Scan the code to open the city density guide on your phone.</p>
        <a href={url}>{url}</a>
      </div>
      <div className="city-qr">
        <QRCodeSVG value={url} size={168} level="M" title="QR code linking to this city density page" />
      </div>
    </section>
  );
}
