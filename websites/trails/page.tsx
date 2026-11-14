import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Trail Notes | Sample Website",
  description: "A fictional guide to getting outside and finding an easygoing trail.",
};

const trails = [
  { name: "Fern Loop", place: "Pine Hollow Preserve", distance: "2.4 mi", difficulty: "Easy", color: "fern" },
  { name: "Lookout Ridge", place: "North Tablelands", distance: "5.8 mi", difficulty: "Moderate", color: "ridge" },
  { name: "Creekside Way", place: "Mossy Creek Park", distance: "1.2 mi", difficulty: "Easy", color: "creek" },
];

export default function TrailsPage() {
  return (
    <div className="demo-page trails-site">
      <nav className="demo-nav" aria-label="Trail Notes">
        <a className="trails-wordmark" href="/websites/trails"><span aria-hidden="true">⌁</span> trail notes</a>
        <div><a href="#trails">Find a trail</a><a href="#field-note">Field note</a></div>
      </nav>
      <section className="trails-hero">
        <p className="sample-kicker">A field guide for the almost-outside</p>
        <h1>Take the<br /><span>scenic route.</span></h1>
        <p>Little walks, big views, and the reminder that you don&apos;t have to go far to get lost in a good way.</p>
        <a className="trails-button" href="#trails">Pick a path <span aria-hidden="true">↓</span></a>
        <div className="trail-landscape" aria-hidden="true"><span className="trail-moon" /><span className="trail-hill hill-back" /><span className="trail-hill hill-front" /><span className="trail-tree tree-one">♠</span><span className="trail-tree tree-two">♠</span><span className="trail-path" /></div>
        <span className="trails-coordinate">34° 02&apos; N · 84° 19&apos; W</span>
      </section>
      <section className="trails-list" id="trails">
        <div className="trails-title"><div><p className="sample-kicker">On the map today</p><h2>Choose your pace.</h2></div><span>3 LOCAL FAVORITES</span></div>
        <div className="trail-cards">{trails.map((trail, index) => (
          <article className={`trail-card trail-${trail.color}`} key={trail.name}>
            <span className="trail-card-number">0{index + 1}</span><div><h3>{trail.name}</h3><p>{trail.place}</p></div>
            <span className="trail-distance">{trail.distance}<small>round trip</small></span>
            <span className="trail-difficulty">{trail.difficulty}</span>
          </article>
        ))}</div>
      </section>
      <aside className="field-note" id="field-note"><span aria-hidden="true">✳</span><p><strong>A note from the trail:</strong> Bring water, leave room for a snack, and let someone know where you&apos;re headed.</p></aside>
      <footer className="trails-footer"><span>GO GENTLY. LEAVE IT LOVELY.</span><span>TRAIL NOTES / FIELD GUIDE 004</span></footer>
    </div>
  );
}
