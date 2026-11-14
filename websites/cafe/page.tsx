import type { Metadata } from "next";
import PhishingSimulation from "../components/PhishingSimulation";
import FictionalFooter from "../components/FictionalFooter";

export const metadata: Metadata = {
  title: "Morrow Coffee | Sample Website",
  description: "A fictional neighborhood coffee shop with a little room to linger.",
};

const menu = [
  { item: "Honey oat latte", note: "Espresso, oat milk, local wildflower honey", price: "$5.50" },
  { item: "Maple morning bun", note: "Crisp edges, soft middle, a little cinnamon", price: "$4.25" },
  { item: "The long way home", note: "Drip coffee, bottomless while you stay", price: "$3.75" },
];

export default function CafePage() {
  return (
    <div className="demo-page cafe-site">
      <nav className="demo-nav" aria-label="Morrow Coffee">
        <a className="cafe-wordmark" href="/websites/cafe"><span aria-hidden="true">✳</span> morrow</a>
        <div><a href="#menu">Menu</a><a href="#visit">Find us</a></div>
      </nav>
      <section className="cafe-hero">
        <div className="cafe-hero-copy">
          <p className="sample-kicker">Coffee for the in-between</p>
          <h1>A softer<br />start to<br /><em>your day.</em></h1>
          <p>Good coffee, warm bread, and a window seat that never asks you to hurry.</p>
          <a className="cafe-button" href="#menu">See what&apos;s brewing <span aria-hidden="true">↘</span></a>
        </div>
        <div className="cafe-cup-art" aria-label="Illustration of a coffee cup">
          <span className="cafe-sun" />
          <span className="cafe-cup"><span>m</span></span>
          <span className="cafe-saucer" />
          <span className="cafe-steam steam-one" />
          <span className="cafe-steam steam-two" />
          <span className="cafe-art-note">TAKE IT<br />SLOW</span>
        </div>
      </section>
      <section className="cafe-menu" id="menu">
        <div className="cafe-section-title"><p className="sample-kicker">Made here, every day</p><h2>A few favorites.</h2></div>
        <ul>{menu.map((entry) => <li key={entry.item}><div><strong>{entry.item}</strong><span>{entry.note}</span></div><b>{entry.price}</b></li>)}</ul>
      </section>
      <PhishingSimulation
        path="/websites/cafe"
        scenario="coffee-reward"
        theme="cafe"
        offer="A free pastry is waiting."
        hook="Offer expires in 10 minutes. Scan to verify your Morrow Rewards account and claim your surprise."
      />
      <footer className="cafe-footer" id="visit"><span>17 WILLOW LANE · EVERYDAY 7–3</span><span>COME AS YOU ARE ☺</span></footer>
      <FictionalFooter />
    </div>
  );
}
