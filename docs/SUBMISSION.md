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

## 3. Devpost video (2:00): with vs without skills

Speed-ups and several clips on one screen are allowed. Call audio is muted; captions say what the AI
did and a voice-over ties it together. Layout: four phones across one 16:9 frame, labelled
**Tutor · out of the box | Tutor · with skill | Research · out of the box | Research · with skill**.

### Clips to record (AirDrop each one to the Mac as soon as it's done)

Phone = iPhone screen recording (Control Center, Screen Recording). Mac = Cmd+Shift+5, "Record
Selected Portion". Audio doesn't matter (it gets muted).

| # | Device | Setup | Do | Length |
|---|---|---|---|---|
| 1 | Phone | Community plugins page: switch to **Chert out of the box** | Call me now, "Teach me how matrix multiplication works", let it answer, hang up | ~30 s |
| 2 | Phone | Switch to **Chert + community skills** | Call me now, same question; 2-3 steps with check-ins; "can you draw an example?" | 60-90 s |
| 3 | Phone | **Out of the box** | Call me now, "Research what Adderall does to dopamine receptors in teenagers", let it answer, hang up | ~30 s |
| 4a | Phone | **With skills** | Same ask; record until it hangs up by itself | ~40 s |
| 4b | Phone | (when the text arrives) | Open the text, open the report, scroll past the sections to the green **Study** sources | ~30 s |
| 4c | Phone | (the call-back) | Answer, let it walk through one section | ~25 s |
| 5 | Phone | With skills; open `docs/demo-scam-qr.png` big on the laptop | Call me now, "Is this QR code safe?", point the camera at the sticker, record until the warning | ~45 s |
| 6 | Mac | chert-community-plugins.vercel.app | Quickstart and docs, Community plugins, type "tutor" in the search, show the Verified badges and the out-of-the-box switch | ~15 s |
| 7 | Mac | GitHub repo | `plugins/` folder, then `verified.json` | ~8 s |
| 8 | Mac | Tiger Data console | the table list (plugin_records, research_jobs, runners, scans): never the connection URL | ~6 s |
| 9 | Mac | Vultr dashboard | the agent server and the sandbox VM | ~6 s |
| 10 | Mac | http://144.202.25.65:3000 | the Coder workspace page | ~6 s |
| 11 | Mac | https://explorer.solana.com/tx/5yKKNDzwTjTaP5AkgzHv3DRQFP2iuPsmDeDDgpg2npQhz4pKZttFqH81xj4viKYn2iVKWNuXrZeDx1EtnBRwFVC5?cluster=devnet | a real Parking payment on devnet ("Success") | ~6 s |
| 12 | Mac | Google AI Studio / Cloud billing | Gemini usage or the budget cap (optional, Google Cloud track) | ~6 s |
| 13 | Voice memo | after the clips | read the voice-over below, calmly | ~70 s |

### Edit (0:00-2:00), following the voice-over

| Time | On screen | Voice-over |
|---|---|---|
| 0:00-0:10 | Title over clip 6 (Community plugins page) | "Chert gives AI agents a FaceTime line. Toolstone is an open-source skill library for it: anyone can build a skill, and every Chert agent can use it." |
| 0:10-0:40 | Clips 1, 2, 3, 4a-c as four phones across, sped up, caption strip under each | "Here's the difference. Out of the box, Chert just talks. With community skills, it tutors with handwritten notes, and it researches published studies on its own and calls you back." |
| 0:40-1:00 | Clip 7 (GitHub `plugins/`), then clip 6 (search "tutor", Verified badges) | "A skill is just a short recipe in a public GitHub repo: plain instructions and a list of allowed tools. Send a pull request, and it shows up on the Community plugins page, searchable with Typesense." |
| 1:00-1:12 | Clip 7 (`verified.json`), clip 6 (Needs verification badge) | "Because skills come from strangers, they're verified by fingerprint. Edit one and it's unverified again, and unverified skills can't touch money, research, or your computer." |
| 1:12-1:32 | Clip 5 (QR, live locked-down browser, warning) | "Our security skill shows why that matters: hold up a QR code, and ScanSafe opens it in a throwaway browser on a Vultr VM, so the scam never touches your phone." |
| 1:32-1:52 | Grid of clips 8-12, 3-4 s each | "Under the hood: Tiger Data stores each skill's memory and research, Gemini on Google Cloud runs the agent with spend caps, Coder gives you a ready workspace to write a skill, and the Parking skill pays on Solana devnet only after you say yes, pay." |
| 1:52-2:00 | End card | "Toolstone. Skills for Chert, built by everyone." |

YouTube chapters: 0:00 Intro · 0:10 With vs without skills · 0:40 Anyone can build a skill · 1:12
ScanSafe · 1:32 Under the hood.

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
