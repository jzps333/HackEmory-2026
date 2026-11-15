# Desktop Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A black / lime desktop version of scansafe.nyc (Home with paste-a-link check, Map, Stats, About) that phones never see.

**Architecture:** New pages under `app/src/app/desktop/`; `app/src/proxy.ts` rewrites desktop browsers from the public paths to them. Desktop pages reuse the existing API helpers and components (`scanUrlLive`, `LiveCheck`, `ResultView`, `MapClient`, `DashboardClient`), recolored by redefining the site's CSS tokens inside a `.desk` wrapper. Every visual effect is a react-bits component copied verbatim, Vanta NET, GSAP, or Lenis.

**Tech Stack:** Next.js 16.4 (App Router, `proxy.ts`), React 19, TypeScript, plain CSS / CSS modules, gsap 3.15, @gsap/react, lenis 1.3, vanta 0.5.24, three 0.134.0.

**Spec:** `docs/superpowers/specs/2026-11-14-desktop-site-design.md`

## Global Constraints

- Do not edit any existing file under `app/src/` except `package.json`/lockfile. Phone UI belongs to a teammate.
- No self-made visuals: effects come only from react-bits (`~/HackEmory-refs/react-bits/src/ts-default`, copied verbatim; type-only fixes allowed and noted in a comment), Vanta, GSAP, Lenis.
- Colors: background `#000`, text `#fff`, lime `#0ae448`, light lime `#abff84`, scam red `#c0262d`. Verdicts: scam red, safe lime, careful white.
- No QR scanning UI on desktop. No location sent from desktop scans (`null`).
- `prefers-reduced-motion: reduce` → no Vanta, no Lenis, all content visible at rest.
- Public paths ↔ desktop paths: `/`↔`/desktop`, `/map`↔`/desktop/map`, `/dashboard`↔`/desktop/stats`, `/about`↔`/desktop/about`.
- `?view=phone|desktop` sets cookie `ss_view` (30 days) and wins over the user agent.

## Review Focus

- A phone (or tablet with a mobile UA) must never get desktop pages; `?view=phone` must stick across later navigations. → Task 1 tests.
- Reduced motion: entrance animations must not leave text at opacity 0, and no WebGL canvas appears. → Task 2 `Reveal`, checked in Task 6.
- A failed or timed-out desktop check must show the "couldn't check" message, never a safe result. → Task 3 step.
- Navigating Home → Map → Home must not stack Vanta canvases or leak the WebGL context. → Task 2 `VantaNet` cleanup, checked in Task 6.
- A narrow desktop window (1024 px and 800 px wide) must not scroll sideways. → Task 6.

---

### Task 1: Device routing

**Files:**
- Create: `app/src/lib/view.ts`, `app/src/proxy.ts`
- Test: `app/tests/view.test.ts` (run with Node 26's built-in TS support: `node --test tests/`)

**Interfaces:**
- Produces: `type View = "desktop" | "phone"`; `pickView(input: { ua: string | null; query: string | null; cookie: string | null }): View`; `DESKTOP_PATHS: Record<string, string>` (public → desktop); `publicPath(pathname: string): string` (desktop → public, identity otherwise).
- `view.ts` imports nothing (so Node can run it without the `@/` alias).

- [ ] **Step 1: Write the failing tests** — `pickView`: iPhone Safari UA → `phone`; Android Chrome phone UA → `phone`; Mac Chrome UA → `desktop`; Windows Edge UA → `desktop`; empty/null UA → `phone`; Mac UA + `query: "phone"` → `phone`; iPhone UA + `cookie: "desktop"` → `desktop`; query beats cookie; junk query/cookie values ignored. `publicPath`: `/desktop`→`/`, `/desktop/map`→`/map`, `/desktop/stats`→`/dashboard`, `/desktop/about`→`/about`, `/map`→`/map`.
- [ ] **Step 2: Run** `cd app && node --test tests/` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement `view.ts`** — mobile = `/Mobi|Android|iPhone|iPod|iPad|Silk|Kindle|Opera Mini/i`.
- [ ] **Step 4: Run** `node --test tests/` — Expected: all PASS.
- [ ] **Step 5: Implement `proxy.ts`** — `export function proxy(req: NextRequest)`; `config.matcher = ["/", "/map", "/dashboard", "/about"]`; read `view` search param and `ss_view` cookie; desktop → `NextResponse.rewrite(new URL(DESKTOP_PATHS[path] + search, req.url))`, else `NextResponse.next()`; when the query param is valid, set the cookie on the response; add `Vary: User-Agent, Cookie`.
- [ ] **Step 6: Commit** `feat(desktop): route desktop browsers to /desktop pages`

### Task 2: Libraries, react-bits copies, desktop shell

**Files:**
- Modify: `app/package.json` (+ lockfile) — `npm i gsap @gsap/react lenis vanta three@0.134.0 && npm i -D @types/three@0.134.0`
- Create: `app/src/components/reactbits/{PillNav,SplitText,StarBorder,SpotlightCard,Counter,AnimatedContent,FadeContent,ScrollReveal}/*` (verbatim copies of the `ts-default` folders)
- Create: `app/src/types/vanta.d.ts`, `app/src/components/desktop/{motion.ts,VantaNet.tsx,Reveal.tsx,DesktopShell.tsx}`, `app/src/app/desktop/{layout.tsx,desktop.css}`

**Interfaces:**
- Produces: `usePrefersReducedMotion(): boolean` (motion.ts); `<VantaNet className? />` (fills its parent, absolutely positioned; lime `0x0ae448` on `0x000000`; `destroy()` on unmount; renders nothing under reduced motion); `<Reveal>` (wraps `AnimatedContent`, `trigger="scroll"`, `once`; plain `<div>` under reduced motion); `<DesktopShell>` (Lenis `ReactLenis root` with `autoRaf:false` driven by `gsap.ticker`, `ScrollTrigger.update` on scroll; PillNav `theme="dark"`, items Home/Map/Stats/About at the public paths, `linkComponent={Link}`, `activeHref={publicPath(usePathname())}`, `highlightColor="#0ae448"`).
- `desktop.css` redefines tokens on `.desk` (`--page`, `--surface`, `--ink`, `--muted`, `--line`, `--border`, `--purple`, `--blue`, `--gradient*`, `--focus`, `--tint*`, `--safe-*` → lime, `--warn-*` → white/neutral, `--bad-*` → red on dark) and uses `body:has(.desk)` to hide `.site-header`, set black background, and `main:has(> .desk)` to drop the 680 px max-width and padding.

- [ ] **Step 1:** Install deps; copy the eight react-bits folders.
- [ ] **Step 2:** Run `cd app && npx tsc --noEmit` — Expected: PASS (fix only type errors inside copies, with a `// typefix:` comment).
- [ ] **Step 3:** Implement the shell files and a placeholder `app/desktop/page.tsx` (heading only).
- [ ] **Step 4:** Run `npx tsc --noEmit` and load `/?view=desktop` in dev — Expected: black page, PillNav, no phone header, no console errors.
- [ ] **Step 5: Commit** `feat(desktop): black/lime shell with Lenis, PillNav, Vanta`

### Task 3: Desktop Home

**Files:** Create `app/src/app/desktop/page.tsx` (metadata `title: "ScanSafe"`), `app/src/components/desktop/DeskHome.tsx`, `app/src/components/desktop/DeskStatTiles.tsx`, `app/src/components/desktop/home.module.css`

**Interfaces:**
- Consumes: `scanUrlLive`, `getPins`, `getStats` (`@/lib/api`); `createLiveFeed`, `LiveCheck`; `ResultView` with `facetime={null}`; `ScamMap` via `next/dynamic` `ssr:false`; Task 2 components.
- Produces: `<DeskStatTiles />` (four tiles from `getStats(24)`: checked, scams caught (red), looked risky, average check time; react-bits `Counter` inside `SpotlightCard` `spotlightColor="rgba(10,228,68,0.25)"`), reused by Task 4.

- [ ] **Step 1:** Hero: `VantaNet` behind; `SplitText` `tag="h1"` "Check a link before you open it."; sub-line; form with input + `StarBorder as="button"` "Check this link". Phase state mirrors `app/src/app/page.tsx` (`idle | checking | result | error`), with `location = null` and the same error copy: "We couldn't check this link right now. Please don't open it yet. Try again in a moment."
- [ ] **Step 2:** Sections below the hero, each in `<Reveal>`: live map (`getPins(33.79, -84.32, 5)`, 520 px tall, link to `/map`), how it works (the four steps' copy from `app/src/app/about/page.tsx`, desktop wording: "Paste the link" for step 1), `<DeskStatTiles />`, built-with chips.
- [ ] **Step 3:** Run `npx tsc --noEmit`; in dev check `https://scansafe-demo-sites.vercel.app/websites/scams/unpaid-toll` → live view then red "scam" result; stop the API URL (set an invalid `NEXT_PUBLIC_API_URL` for one run) → the error message, not a safe verdict.
- [ ] **Step 4: Commit** `feat(desktop): home with link check, live map, stats`

### Task 4: Desktop Map and Stats

**Files:** Create `app/src/app/desktop/map/page.tsx`, `app/src/app/desktop/stats/page.tsx`, `app/src/components/desktop/pages.module.css`

- [ ] **Step 1:** Map page: `<Reveal>` around `<MapClient />` in a wide container; CSS makes `.map-wrap` ~70vh and darkens tiles with `filter` on `.leaflet-tile-pane` only (pins stay red).
- [ ] **Step 2:** Stats page: own `SplitText` h1 "Stats", `<DeskStatTiles />`, then `<DashboardClient />` with its own `h1`, first `p` and `.tiles` section hidden by CSS inside the wrapper; chart bars use lime / red via tokens.
- [ ] **Step 3:** Run `npx tsc --noEmit`; dev check both pages show live data (map pin near Emory).
- [ ] **Step 4: Commit** `feat(desktop): map and stats pages`

### Task 5: Desktop About

**Files:** Create `app/src/app/desktop/about/page.tsx`, `app/src/components/desktop/DeskAbout.tsx`, `app/src/components/desktop/about.module.css`

- [ ] **Step 1:** Same sections and copy as `app/src/app/about/page.tsx` (hero, problem, how it works, features, privacy, demo video, built with, closing CTA, footer) with: `VantaNet` hero background; problem paragraph in `ScrollReveal`; features in `SpotlightCard`s; sections in `<Reveal>`; CTAs "Check a link" → `/` and the FaceTime number; "Peachtree Parking Co." → "Dogwood Lot & Meter Co." everywhere.
- [ ] **Step 2:** Run `npx tsc --noEmit`; dev check.
- [ ] **Step 3: Commit** `feat(desktop): about page`

### Task 6: Verify and ship-ready

- [ ] **Step 1:** `cd app && node --test tests/ && npx tsc --noEmit && npx next build` — Expected: all pass.
- [ ] **Step 2:** Browser (dev server): desktop UA sees black site on all four public paths; mobile emulation sees the existing phone pages; `?view=phone` then navigate → still phone.
- [ ] **Step 3:** Review Focus checks: reduced-motion emulation (text visible, no canvas); Home → Map → Home leaves exactly one Vanta canvas; widths 1024 and 800 have no horizontal scroll.
- [ ] **Step 4:** Screenshots of each page for the user. Merge to `main` and deploy only with the user's OK.
