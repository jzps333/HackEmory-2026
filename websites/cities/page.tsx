import type { Metadata } from "next";
import ShareQr from "./ShareQr";

export const metadata: Metadata = {
  title: "World's Densest Cities | ScanSafe",
  description: "Explore a sample ranking of some of the world's most densely populated cities.",
};

const cities = [
  { name: "Manila", country: "Philippines", density: "43,000", rank: "01", color: "coral" },
  { name: "Pateros", country: "Philippines", density: "37,000", rank: "02", color: "gold" },
  { name: "Mandaluyong", country: "Philippines", density: "34,000", rank: "03", color: "blue" },
  { name: "Dhaka", country: "Bangladesh", density: "29,000", rank: "04", color: "green" },
  { name: "Caloocan", country: "Philippines", density: "27,000", rank: "05", color: "purple" },
  { name: "Kolkata", country: "India", density: "24,000", rank: "06", color: "gold" },
  { name: "Karachi", country: "Pakistan", density: "24,000", rank: "07", color: "coral" },
  { name: "Mumbai", country: "India", density: "20,000", rank: "08", color: "blue" },
];

export default function CitiesPage() {
  return (
    <div className="city-page">
      <section className="city-hero">
        <div className="city-hero-copy">
          <p className="city-eyebrow">A little closer, a lot more alive</p>
          <h1>The world,<br />up close.</h1>
          <p className="city-intro">
            Meet some of the planet&apos;s most densely populated cities, where millions of
            everyday stories unfold side by side.
          </p>
          <a className="city-cta" href="#city-list">Explore the cities <span aria-hidden="true">↓</span></a>
        </div>
        <div className="city-hero-art" aria-hidden="true">
          <span className="city-orbit orbit-one" />
          <span className="city-orbit orbit-two" />
          <span className="city-orbit orbit-three" />
          <span className="city-art-label">38° 34&apos; N<br />121° 00&apos; E</span>
          <span className="city-art-center">CITY<br />LIFE</span>
        </div>
        <div className="city-hero-foot">
          <span>URBAN ATLAS / 01</span>
          <span>8 CITIES · 3 CONTINENTS</span>
        </div>
      </section>

      <section className="city-section" id="city-list" aria-labelledby="city-list-heading">
        <div className="city-section-heading">
          <div>
            <p className="city-eyebrow">The city index</p>
            <h2 id="city-list-heading">Life, packed in.</h2>
          </div>
          <p>Approximate residents per square kilometer</p>
        </div>

        <ol className="city-grid">
          {cities.map((city) => (
            <li className={`city-card city-${city.color}`} key={city.name}>
              <span className="city-rank">{city.rank} / CITY</span>
              <h3>{city.name}</h3>
              <p className="city-country">{city.country}</p>
              <div className="city-density">
                <strong>{city.density}</strong>
                <span>people / km²</span>
              </div>
              <div className="city-meter" aria-hidden="true">
                <span style={{ width: `${(Number(city.density.replace(",", "")) / 43000) * 100}%` }} />
              </div>
            </li>
          ))}
        </ol>
        <p className="city-footnote">
          Sample estimates for illustration, not an official global ranking. Population density
          changes with the year measured and the boundaries used to define a city.
        </p>
      </section>

      <ShareQr />

      <footer className="city-footer">
        <span>THE HUMAN SIDE OF THE NUMBERS</span>
        <span>SCANSAFE · URBAN ATLAS</span>
      </footer>
    </div>
  );
}
