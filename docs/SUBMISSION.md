# Toolstone: submission kit (EmoryHacks 2026)

Final lineup. Chert pitch: **Research, Tutor, Vercel** (plus the FaceTime briefing if it ships).
Security track: **ScanSafe**. Everything below is live unless marked **[if ready]**.

## 1. Before recording (checklist)

- [ ] Phone: Do Not Disturb off; screen recording on (Control Center, long-press, Microphone ON).
- [ ] Signed in at https://chert-community-plugins.vercel.app/apps (that page has **Call me now**).
- [ ] Mac: the Toolstone helper is running (`runner/toolstone_runner.py run`) for the Vercel part.
- [ ] Laptop tabs: Community plugins page; GitHub `plugins/` folder; one research report link.
- [ ] A scam QR code ready on a second screen (security cut).
- [ ] Record each part separately; keep a backup take. Research takes 5-10 min: record the
      request, cut, then record the call-back.

## 2. Elevator pitch (188 characters)

Toolstone: open-source skills for Chert. FaceTime an AI that spots scam QR codes, pays parking only
when you say yes, and researches on its own. Anyone can build, verify and share a skill.

(Chert-only version) Toolstone gives Chert agents verified, open-source skills that use what only
Chert has: FaceTime. A live tutor whiteboard, research that calls you back, your infrastructure by voice.

## 3. Video script (about 2:45)

| Time | Show | Say |
|---|---|---|
| 0:00 | Title card | "Chert gives AI agents iMessage and FaceTime. Toolstone gives them skills: open-source, verified, shareable." |
| 0:12 | Community plugins page, switch to **Chert out of the box**, Call me now | "Out of the box, Chert is a friendly assistant." (one quick exchange) |
| 0:30 | Switch to **Chert + community skills**, Call me now | "Same line, now with community skills." |
| 0:38 | "Help me learn derivatives" — handwritten steps appear; say "why are we using h?"; "can you draw it?" | "The Tutor writes notes by hand on my screen, checks I'm following after every step, explains the why, and draws the graph." |
| 1:10 | "Research the best beginner NASDAQ strategies" → it hangs up by itself | "Research works on its own, then calls me back." |
| 1:20 | Text arrives with the report link; incoming FaceTime walks through sections with cards | "A cited report on my phone, and a walkthrough I can steer." |
| 1:45 | "How's my site?" — deploys read from Vercel via the helper on my Mac | "Vercel runs through a helper on my own computer. My key never leaves it; the AI never sees it. Redeploy only after I say 'yes, redeploy'." |
| 2:05 | **[if ready]** Claude Code finishes a task → FaceTime briefing | "Any coding agent can FaceTime me a walkthrough of what it built, through Toolstone's MCP server." |
| 2:15 | Community plugins: Verified / Needs verification, GitHub `plugins/` | "Every skill is a recipe in a public repo. Unverified skills can't touch money, research or your computer, and editing a skill un-verifies it." |
| 2:30 | Security cut: scam QR on FaceTime | "ScanSafe opens strangers' links in a throwaway Vultr VM and stops scams before you pay." |
| 2:40 | End card | "Toolstone. Skills for Chert." |

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
  - **Research agent:** you say a topic and it hangs up; it researches on its own (Gemini + Google
    Search, at least four rounds, capped spend), texts you a cited report page and FaceTimes you a
    section-by-section walkthrough you can steer. Past reports are searchable (Typesense).
  - **Vercel:** "how's my site?" / "redeploy" through a helper app on your own computer: your key
    stays in a local file, the AI and our servers never see it, and redeploys need "yes, redeploy".
  - **ScanSafe (security):** hold up a QR code; it opens the link in a throwaway, locked-down browser
    on a Vultr VM, streams it live, and warns you about scams.
  - Also in the library: Parking (official app, pays Solana devnet only after "yes, pay"), Squat
    coach, Study buddy, Plugin finder.
- **Community plugins page**, a clone of the Chert console built with Chert's permission: search
  (Typesense), enable, submit, and a switch between Chert out of the box and Chert with skills.
- **[if ready] MCP server:** Claude Code or Cursor can FaceTime you a briefing when they finish a task.

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
