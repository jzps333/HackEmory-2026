# Desktop site: black, lime, a bit of motion

Short design, 2026-11-14 (EmoryHacks, before the 3 AM feature freeze). Branch `desktop-site`.

## Intent

Give people on a computer (judges included) a desktop version of scansafe.nyc: black background, lime
green accents, a bit of motion. A teammate owns the phone UI; this must not touch it.

## Decided by the user

- All four desktop pages: Home (`/`), Map (`/map`), Stats (`/dashboard`), About (`/about`).
- Black background, lime green accents; red only for scams.
- Every visual effect comes as-is from the four repos: react-bits, Vanta, GSAP, Lenis. Nothing visual
  is generated or hand-made. Only layout and glue code are written.
- No QR scanning on desktop (phone only). Home has a paste-a-link check that runs the real scan with the
  live sandbox view.
- The interactive scam map is on desktop.

## Goals / non-goals / anti-goals

- Goals: one consistent black/lime desktop site; working link check, map (live Typesense pins), stats.
- Non-goals: phone UI, onboarding, FaceTime setup flow, new backend endpoints.
- Anti-goals: motion that makes text hard to read for older users; breaking or conflicting with the
  teammate's phone files; any self-made graphic.

## Approaches

1. **Picked: separate desktop routes + device routing.** New pages under `app/src/app/desktop/`; a Next
   proxy rewrites desktop browsers from `/`, `/map`, `/dashboard`, `/about` to them (URLs unchanged).
   `?view=phone|desktop` sets a cookie override. No phone files change; phones never load this code.
2. Same pages switched by width: edits every phone file, so it guarantees merge conflicts.
3. Separate desktop app + deploy: new project and DNS, too much for tonight.

## Design (Claude's calls, correct any)

- **Colors:** black `#000`, white text, lime `#0ae448` with light lime `#abff84` (GSAP's own brand
  colors, from the gsap repo). Scam red = the site's existing `#c0262d`. Verdicts: scam red, safe lime,
  "be careful" white.
- **Shared:** Lenis smooth scroll driven by the GSAP ticker; react-bits **PillNav** for the nav;
  react-bits **AnimatedContent/FadeContent** (GSAP ScrollTrigger) for section entrances.
- **Home:** Vanta **NET** hero background (lime on black), react-bits **SplitText** headline, paste-a-link
  box with a react-bits **StarBorder** button. Check runs through the existing `scanUrlLive` →
  `LiveCheck` (live view) → `ResultView`, recolored through CSS tokens inside the desktop wrapper. Below:
  live interactive map, how it works, stat counters, built with.
- **Map:** existing map logic and Leaflet map, full width; tiles darkened with a CSS filter, red pins kept.
- **Stats:** existing dashboard data; react-bits **Counter** for the numbers, **SpotlightCard** tiles.
- **About:** existing About copy and artwork; react-bits **SpotlightCard** features, **ScrollReveal** for
  the problem paragraph. "Peachtree Parking Co." corrected to "Dogwood Lot & Meter Co.".
- **Libraries:** `gsap`, `@gsap/react`, `lenis`, `vanta`, `three@0.134.0` (Vanta's tested version).
  react-bits components are copied from `src/ts-default` (plain CSS, no Tailwind); only ones that need
  nothing beyond React and GSAP.
- **Motion off** when the computer asks for reduced motion: no Vanta, no Lenis, entrances shown at rest.
- Root layout's phone header and `main` width are hidden/overridden from the desktop wrapper with CSS
  `:has()`, so the shared layout file is not edited.

## Left to the builder

Exact spacing and type sizes; which Vanta NET options (points, spacing, speed) read best; small
responsive fixes for narrow desktop windows.

## Done when

Desktop Chrome shows all four pages black/lime with motion; a pasted demo scam link returns a red
result with the live view; the map shows the live Typesense pin; phones (and `?view=phone`) still get
the existing pages; `tsc` and the Next build pass.
