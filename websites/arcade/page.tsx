import type { Metadata } from "next";
import PhishingSimulation from "../components/PhishingSimulation";
import FictionalFooter from "../components/FictionalFooter";

export const metadata: Metadata = {
  title: "Pixel Palace | Sample Website",
  description: "A fictional retro arcade where the high score is having a good time.",
};

const games = [
  { name: "Star Snack", genre: "SPACE · 1–2 PLAYERS", score: "001 240", icon: "✦", color: "pink" },
  { name: "Jelly Jump", genre: "PLATFORM · 1 PLAYER", score: "009 850", icon: "◆", color: "lime" },
  { name: "Turbo Toad", genre: "RACING · 1–4 PLAYERS", score: "042 100", icon: "▣", color: "orange" },
];

export default function ArcadePage() {
  return (
    <div className="demo-page arcade-site">
      <nav className="demo-nav" aria-label="Pixel Palace">
        <a className="arcade-wordmark" href="/websites/arcade"><span aria-hidden="true">▣</span> PIXEL PALACE</a>
        <div><a href="#cabinet">The cabinet</a><a href="#high-scores">High scores</a></div>
      </nav>
      <section className="arcade-hero">
        <div className="arcade-stamp">INSERT<br />COIN<br /><span>♥</span></div>
        <p className="sample-kicker">PLAYER ONE, YOU LOOK GREAT</p>
        <h1>GOOD<br />TIMES.<br /><span>NO SAVE<br />POINT.</span></h1>
        <p>Three buttons. A whole afternoon. Welcome to the arcade where nobody asks if you&apos;re too old to play.</p>
        <a className="arcade-button" href="#cabinet">PRESS START <span aria-hidden="true">▶</span></a>
        <div className="arcade-sunburst" aria-hidden="true"><span>PLAY<br />ALL DAY</span></div>
      </section>
      <section className="arcade-cabinet" id="cabinet">
        <div className="arcade-section-head"><div><p className="sample-kicker">Pick your fighter</p><h2>The cabinet.</h2></div><span>3 GAMES LOADED</span></div>
        <div className="arcade-games">{games.map((game) => (
          <article className={`arcade-game game-${game.color}`} key={game.name}>
            <div className="game-screen"><span>{game.icon}</span><small>READY!</small></div>
            <p>{game.genre}</p><h3>{game.name}</h3><div className="game-score"><span>TOP SCORE</span><strong>{game.score}</strong></div>
          </article>
        ))}</div>
      </section>
      <PhishingSimulation
        path="/websites/arcade"
        scenario="arcade-reward"
        theme="arcade"
        offer="You unlocked a rare skin!"
        hook="Your bonus disappears tonight. Scan to verify your player profile and reveal the prize."
      />
      <footer className="arcade-footer" id="high-scores"><span>NO QUARTERS REQUIRED (THIS IS A WEBSITE)</span><span>PIXEL PALACE · OPEN EVERYWHEN</span></footer>
      <FictionalFooter />
    </div>
  );
}
