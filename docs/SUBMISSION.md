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

## 3. Devpost video (2:00, split screen, every track)

Speed-ups and several things on one screen are allowed. Judges read captions at 1x, so every
panel gets a caption strip; the call audio is muted and a voice-over plus captions tell the story.

| Time | On screen | Voice-over (short) | Tracks hit |
|---|---|---|---|
| 0:00-0:06 | Title card: "Toolstone: verified skills for Chert" over the Community plugins page | "Toolstone gives any Chert agent new skills that work on a real FaceTime call." | Chert |
| 0:06-0:50 | **Three phones side by side**, each its own screen recording at 2-3x, a label on top and a caption strip under it: **Tutor** (handwritten steps, countdown chip) · **Research** (asks, hangs up, "4 min later", text, report with green Study tags, call-back) · **Vercel** ("How's my site?", deploys read back) | "On the left it teaches with handwritten notes. In the middle it researches published studies on its own and calls back. On the right it checks my Vercel site through a helper on my own computer: my key never leaves it." | Chert, Gemini, Google Cloud, Typesense, Security |
| 0:50-1:15 | **ScanSafe**, split: phone holding up `docs/demo-scam-qr.png` · the locked-down browser streaming from the Vultr VM · the scam warning | "Hold up a QR code and it opens the link in a throwaway, locked-down browser on a Vultr VM, so the scam never touches your phone." | Security, Vultr |
| 1:15-1:30 | Community plugins page: search (Typesense), Verified / Needs verification, GitHub `plugins/` + `verified.json` | "Every skill is a recipe in a public repo. It's verified by fingerprint; edit it and it's unverified again, and unverified skills never touch money, research or your computer." | Security, Chert, Typesense |
| 1:30-1:52 | **Under the hood grid**, 2x3 tiles, 3 s each lit up: Tiger Data tables (plugin_records, research_jobs, runners) · Typesense collections · Gemini on our Google Cloud project with spend caps · Vultr agent server + sandbox VM · Coder workspace "Write a Toolstone skill" · Solana devnet: Parking pays only after "yes, pay" | one line per tile | Tiger Data, Typesense, Gemini/Google Cloud, Vultr, Coder, Solana |
| 1:52-2:00 | End card: Toolstone, repo link, track logos | "Toolstone. Skills for Chert." | |

Editing (CapCut or iMovie): one 16:9 canvas, three vertical phone clips at equal width, speed each to
2-3x so the key moment lands inside 0:06-0:50, add a caption strip per panel, mute clip audio, record
the voice-over last. Chapters in the YouTube description: 0:00 Intro · 0:06 Tutor, Research, Vercel ·
0:50 ScanSafe · 1:15 Verified skills · 1:30 Under the hood.

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
