import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sample Websites | ScanSafe",
  description: "A collection of four fictional sample websites.",
};

const sites = [
  { href: "/websites/cafe", number: "01", name: "Morrow Coffee", type: "Neighborhood coffee shop", mood: "Warm, slow mornings", className: "sample-card-cafe" },
  { href: "/websites/trails", number: "02", name: "Trail Notes", type: "Outdoor field guide", mood: "Find your next path", className: "sample-card-trails" },
  { href: "/websites/orbit", number: "03", name: "Orbit Post", type: "Space culture journal", mood: "Dispatches from above", className: "sample-card-orbit" },
  { href: "/websites/arcade", number: "04", name: "Pixel Palace", type: "Retro arcade club", mood: "Insert coin, feel joy", className: "sample-card-arcade" },
];

export default function SampleWebsitesPage() {
  return (
    <div className="demo-page sample-index">
      <header className="sample-index-heading">
        <p className="sample-kicker">A small collection / issue 01</p>
        <h1>Four little corners<br />of the internet.</h1>
        <p>Pick a door. Every one leads somewhere different.</p>
      </header>
      <div className="sample-index-grid">
        {sites.map((site) => (
          <a className={`sample-card ${site.className}`} href={site.href} key={site.href}>
            <span className="sample-card-number">{site.number} / 04</span>
            <span className="sample-card-art" aria-hidden="true">{site.number}</span>
            <span className="sample-card-copy">
              <span className="sample-card-type">{site.type}</span>
              <strong>{site.name}</strong>
              <span>{site.mood}</span>
            </span>
            <span className="sample-card-arrow" aria-hidden="true">↗</span>
          </a>
        ))}
      </div>
      <p className="sample-index-note">All four are fictional demo sites, made for exploring ideas.</p>
    </div>
  );
}
