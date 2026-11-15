# Toolstone: submission kit (EmoryHacks 2026)

Final lineup. Chert pitch: **Tutor, Research, Vercel**. Security track: **ScanSafe**. Everything below is live.

## 1. Before recording (checklist)

- [ ] Phone: Do Not Disturb off; screen recording on (Control Center, long-press, Microphone ON).
- [ ] Signed in at https://chert-community-plugins.vercel.app/apps (that page has **Call me now**).
- [ ] Mac: the Toolstone helper is running (`runner/toolstone_runner.py run`) for the Vercel part.
- [ ] Laptop tabs: Community plugins page; GitHub `plugins/` folder; one research report link.
- [ ] A scam QR code ready on a second screen (security cut): open `docs/demo-scam-qr.png` (a fake
      "unpaid toll" sticker pointing at our demo scam page).
- [ ] Record each part separately; keep a backup take. Research takes 4-10 min: record the
      request, cut, then record the call-back.
- [ ] Never on screen: `~/.toolstone/.env`, `.env` files, the Coder token, the Tiger connection URL.
- [ ] Vercel: only "How's my site?" today (a redeploy hits Vercel's free 100-deploys/day limit).

## 2. Elevator pitch (188 characters)

Toolstone: open-source skills for Chert. FaceTime an AI that spots scam QR codes, pays parking only
when you say yes, and researches on its own. Anyone can build, verify and share a skill.

(Chert-only version) Toolstone gives Chert agents verified, open-source skills that use what only
Chert has: FaceTime. A live tutor whiteboard, research that calls you back, your infrastructure by voice.

## 3. Devpost video (2:00, every track, YouTube chapters)

Judges watch at 1x: every sped-up clip gets an on-screen caption ("2x", "4 minutes later"). Paste
the chapter list into the YouTube description and the Devpost "Tracks" text.

| Chapter | Clip (record separately) | Say / caption | Tracks |
|---|---|---|---|
| 0:00 What Toolstone is | **Mac screen**: Community plugins page under Quickstart and docs, flip to "Chert + community skills", click Call me now | "Chert gives AI agents a phone line. Toolstone is the skill layer on top: anyone builds a skill, it gets verified, and any Chert agent can use it on a real FaceTime call." | Chert |
| 0:12 Tutor | **Phone**: "Teach me matrix multiplication"; first handwritten step at 1x, the rest at 2x; the "Next step in ~3s" chip | "It writes the notes by hand on my screen and checks in after every step." | Chert, Gemini |
| 0:35 Research | **Phone**: ask (1x) → it hangs up by itself → card "4 minutes later" → text with link → report page scrolled at 2x (green **Study** tags) → 5 s of the call-back | "It researches on its own from published studies, texts me a cited report and calls me back." | Gemini, Typesense |
| 1:05 Vercel | **Phone**: "How's my site?" + **Mac**: the helper's terminal running (never the .env) | "It runs through a helper on my own computer: my Vercel key never leaves it." | Security |
| 1:20 ScanSafe | **Phone**: hold up `docs/demo-scam-qr.png`; live locked-down browser at 2x; the scam warning | "Hold up a QR code: it opens the link in a throwaway VM on Vultr and stops the scam before you pay." | Security, Vultr |
| 1:40 Under the hood | **Mac**, fast cuts with captions: GitHub `plugins/` + `verified.json` · Tiger Data tables (plugin_records, research_jobs) · Coder workspace · Solana devnet | "Skills are recipes in a public repo, verified by fingerprint. Tiger Data holds memory and research, Typesense searches it, Coder is where you write a skill." | Tiger Data, Coder, Solana, Typesense |
| 1:55 End card | "Toolstone. Skills for Chert." + repo link | | |

## 3b. Live pitch to Chert (they've already seen the project)

Lead with the why, demo the three Chert skills live, keep time for questions.

1. **Why (20 s):** Chert's superpower is FaceTime, and nobody builds for it (Photon has messaging and
   MCP, no FaceTime). Toolstone makes skills that use the call itself: the screen, the voice, calling back.
2. **Tutor (live, 45 s):** a real question in your own words; point at the handwriting, the check-ins,
   the countdown chip.
3. **Research (live, 30 s):** ask, it hangs up by itself; show a finished report on the laptop (Study
   tags, cited papers) instead of waiting for the call-back.
4. **Vercel (live, 20 s):** "How's my site?" through the helper; the key stays on the Mac; a redeploy
   needs "yes, redeploy".
5. **The platform (30 s):** Community plugins page in the Chert console, verified vs unverified,
   editing a skill un-verifies it, unverified skills never touch money, research or your computer.
6. **Ask:** Chert-hosted skills: a "Community plugins" tab in the real console.

## 4. Devpost text

**Inspiration.** Chert lets AI agents text and FaceTime people, but every agent starts from zero, and
FaceTime is Chert's superpower that nobody is building for (its closest competitor, Photon, has
messaging and an MCP server but no FaceTime). We wanted anyone to be able to give a Chert agent new
abilities that actually work on a real call, and to share them safely: a skill from a stranger is
like a QR code from a stranger, you don't know what it does until it runs.

**What it does.** Toolstone is an open-source skill platform for Chert.
- **Skills are recipes** (`plugins/<id>/plugin.yaml`: plain-text instructions + a list of allowed
  tools) in a public GitHub folder. Anyone can submit one with a pull request; a GitHub check
  validates it.
- **Verified vs unverified.** A skill is verified only when its SHA-256 fingerprint is in an
  admin-owned list; editing it un-verifies it. Unverified skills never get payments, research or
  your computer, and never reach the shared agent.
- **On a call**, the Chert agent (Gemini Live) loads the enabled skills and switches to the right one
  when you ask. Skills can remember things (Tiger Data), text you, and show things on the video.
- **Skills we built:**
  - **Tutor:** a handwritten whiteboard on your FaceTime screen, step by step, checks in after every
    step, explains the why on sticky notes, and draws graphs (safe math parser, no code execution).
  - **Research agent:** you say a topic and it hangs up; it researches on its own (published studies
    from OpenAlex plus Google Search, read by Gemini over at least four rounds, capped spend), texts
    you a report page that cites the papers (journal, year, citations) and FaceTimes you a
    section-by-section walkthrough you can steer. Past reports are searchable (Typesense).
  - **Vercel:** "how's my site?" / "redeploy" through a helper app on your own computer: your key
    stays in a local file, the AI and our servers never see it, and redeploys need "yes, redeploy".
  - **ScanSafe (security):** hold up a QR code; it opens the link in a throwaway, locked-down browser
    on a Vultr VM, streams it live, and warns you about scams.
  - Also in the library: Parking (official app, pays Solana devnet only after "yes, pay"), Squat
    coach, Study buddy, Plugin finder.
- **Community plugins page**, a clone of the Chert console built with Chert's permission: search
  (Typesense), enable, submit, and a switch between Chert out of the box and Chert with skills.

**How we built it.** FastAPI backend and a LiveKit + Gemini Live agent on a Vultr server, bridged to
FaceTime by Chert; our own 720x1280 video renderer for the whiteboard, cards and live views. A second
Vultr server runs locked-down Playwright browsers in throwaway Docker containers. A small helper app
on the user's Mac connects out to a relay for local skills (keys stay on the machine; screenshots
mask filled fields). Tiger Data for skill memory, research jobs, pairings and install counts;
Typesense for skill and report search; Solana devnet for consent-gated payments; Next.js on Vercel;
a Coder workspace template for writing skills.

**Challenges.** Safety for strangers' skills: fingerprinted verification, a strict tool allowlist,
no symlinks or duplicate YAML keys, unverified skills kept off the shared agent, every piece of web
or skill text fenced as data, links and phone numbers stripped from anything texted from the line,
caller identity only from the call itself. Real-time voice: tuning turn-taking, cutting steps so
skills start immediately. Rendering handwriting with proper math symbols at video frame rates.

**What's next.** Chert-hosted skills, more local connectors (Supabase, ElevenLabs) through the helper,
importing instruction-only Claude skills, and a public review queue for community skills.

## 5. Tracks

| Track | Point at |
|---|---|
| Security (main) | ScanSafe in the throwaway VM; verified/unverified skills, tool allowlist, fingerprints, keys that never leave your computer |
| Chert | the whole platform: FaceTime-native skills (Tutor, Research call-back, Vercel), community page |
| MLH Gemini | Gemini Live as the FaceTime agent; Gemini + Google Search research loop |
| Tiger Data | skill memory, research jobs, runner pairings, install counts, scan history |
| Typesense | skill search, research library search, scam map |
| Solana | Parking pays on devnet only after "yes, pay" |
| Vultr | agent server + throwaway browser VM |
| Coder for Good | our Coder deployment: the `scansafe-dev` workspace and the "Write a Toolstone skill" template |
| A-Team | opt in |
| Cut | GoDaddy, Entire, DEV (unless you write a dev.to post) |

## 6. Test checklist

| Skill | Do | Expect |
|---|---|---|
| Baseline | Switch to out of the box, Call me now | Plain assistant |
| Tutor | "Help me learn derivatives", "why?", "draw it" | Handwritten steps, check-in every step, sticky note, graph |
| Research | "Research …" | One question, it hangs up, text + call-back in 5-10 min with cards |
| Vercel | "How's my site?" (helper running) | Latest deploys read back |
| ScanSafe | Hold a scam QR up | Locked-down browser live, scam warning |
| Community page | Search, open a skill | Verified badge, tools, permissions |
