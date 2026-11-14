import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Orbit Post | Sample Website",
  description: "A fictional journal for curious people looking up at the night sky.",
};

export default function OrbitPage() {
  return (
    <div className="demo-page orbit-site">
      <nav className="demo-nav" aria-label="Orbit Post">
        <a className="orbit-wordmark" href="/websites/orbit"><span aria-hidden="true">✳</span> ORBIT POST</a>
        <div><a href="#dispatch">Dispatches</a><a href="#newsletter">The signal</a></div>
      </nav>
      <section className="orbit-hero">
        <div className="orbit-topline"><span>VOL. 08 / NOVEMBER</span><span>THOUGHTS FROM THE GREAT OUT THERE</span></div>
        <div className="orbit-planet" aria-hidden="true"><span className="orbit-ring" /><span className="orbit-crater crater-one" /><span className="orbit-crater crater-two" /><span className="orbit-crater crater-three" /></div>
        <p className="sample-kicker">The night shift · 6 min read</p>
        <h1>Somewhere,<br />it&apos;s always<br /><em>the first light.</em></h1>
        <p className="orbit-deck">A small meditation on distant suns, the patience of stargazers, and why looking up still feels like going somewhere.</p>
        <a className="orbit-read" href="#dispatch">Read the dispatch <span aria-hidden="true">↗</span></a>
        <div className="orbit-hero-foot"><span>WORDS BY L. MORENO</span><span>01 — 04</span></div>
      </section>
      <section className="orbit-dispatch" id="dispatch">
        <p className="sample-kicker">From the observatory</p>
        <h2>The universe<br />doesn&apos;t mind if<br />you&apos;re late.</h2>
        <div><p>Light from a star can spend centuries on its way to us. By the time it reaches your backyard, the whole world might have changed—and still, there it is. A tiny, ancient hello.</p><p>Tonight&apos;s assignment: find one bright point in the sky. You don&apos;t need its name. Just give it a minute.</p><a href="#newsletter">Get the next dispatch →</a></div>
      </section>
      <footer className="orbit-footer" id="newsletter"><span>KEEP LOOKING UP</span><span>ORBIT POST · AN INDEPENDENT SPACE JOURNAL</span><span>✦</span></footer>
    </div>
  );
}
