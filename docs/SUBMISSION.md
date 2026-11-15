# Toolstone: submission kit (EmoryHacks 2026)

Status markers: **[live]** deployed and tested, **[built]** done but not deployed/tested yet,
**[in progress]** being built now, **[pitch]** idea only, say "next".

## 1. Setup checklist (do these before recording)

- [ ] Phone: FaceTime works with the Chert line (+1 650-444-4331); Do Not Disturb off.
- [ ] Sign in on the dashboard with your phone: https://chert-community-plugins.vercel.app/apps
- [ ] Have these QR codes ready on a second screen or printed:
      a scam QR (ScanSafe demo site), the Dogwood parking meter QR, the ParkMobile QR (zone 91987).
- [ ] ParkMobile saved sign-in is still valid (expires about a day after it was saved).
- [ ] Dashboard switch "Next call uses" set to the mode you are about to show.
- [ ] iPhone screen recording on (Control Center, long-press record, Microphone ON).
- [ ] Laptop: dashboard open on Community plugins; second tab on GitHub `plugins/`.
- [ ] Optional: Coder link sent to Claude (for the Coder workspace); else drop Coder for Good.
- [ ] Optional: add `GEMINI_API_KEY` as a GitHub Actions secret (AI safety review on plugin PRs).

## 2. Elevator pitch (188 characters)

Toolstone: open-source skills for Chert. FaceTime an AI that spots scam QR codes, pays parking only
when you say yes, and researches on its own. Anyone can build, verify and share a skill.

## 3. Video script (about 2:30)

| Time | Show | Say |
|---|---|---|
| 0:00 | Title card | "Chert gives AI agents iMessage and FaceTime. Toolstone gives them skills: open-source, verified, and shareable." |
| 0:15 | Dashboard, switch to "Chert out of the box", FaceTime the line | "Out of the box, Chert is a friendly assistant." (ask it something simple) |
| 0:35 | Switch to "Chert + community skills", call again: "What skills do I have?" | It lists the skills. "Same call, now with community skills." |
| 0:50 | "Research the best NASDAQ trading strategies for beginners", answer "anything else?", hang up | "It works on its own for up to 15 minutes and calls me back." **[in progress]** |
| 1:05 | Incoming FaceTime: research results, cards on screen, ask to go deeper on one section | "It walks me through it, section by section, and I can steer it." **[in progress]** |
| 1:30 | Scan the parking meter QR in the app → FaceTime: official app filled live, "yes, pay" | "Parking: it fills the official app and pays only when I say yes, pay. Solana devnet, test money." **[live]** |
| 1:55 | Community plugins page: verified badges, search, "Needs verification", GitHub folder | "Every skill is a recipe in a public repo. Anyone can submit one; it stays unverified and locked out of payments until an admin verifies it. Edit it and it drops back to unverified." **[live]** |
| 2:15 | Security track cut: hold a scam QR up on FaceTime | "ScanSafe, our security skill, opens strangers' links in a throwaway Vultr VM and stops scams before you pay." **[live]** |
| 2:30 | End card with tracks | "Toolstone: skills for Chert." |

Record a backup take of each part.

## 4. Devpost text

**Inspiration.** Chert lets AI agents text and FaceTime people, but every agent starts from zero.
We wanted a way for anyone to give a Chert agent new abilities that actually work on a real call,
and to share them safely, because a skill from a stranger is like a QR code from a stranger: you
don't know what it does until it runs.

**What it does.** Toolstone is an open-source skill platform for Chert.
- Skills are recipes (`plugins/<id>/plugin.yaml`: instructions plus a list of allowed tools) in a
  public GitHub folder. Anyone can submit one with a pull request.
- A skill is **unverified** until an admin approves its fingerprint (SHA-256 of its files). Edit it
  and it is unverified again. Unverified skills never get payments, parking or research, and never
  reach the shared demo agent.
- On a FaceTime call, the Chert agent (Gemini Live) loads the enabled skills, tells you what it can
  do, and switches skills when you ask. Skills can remember things (stored in Tiger Data), text you
  afterwards and keep history you can see by signing in with your phone number.
- Skills we built: Research agent **[in progress]**, Parking (official app or ParkMobile, pays with
  Solana devnet only after a spoken "yes, pay"), ScanSafe QR checker, Safe browser, Plugin finder,
  Squat coach, Study buddy (spaced repetition).
- A Community plugins page (a clone of the Chert console, built with Chert's permission) to browse,
  search (Typesense), enable and submit skills, plus a switch between Chert out of the box and Chert
  with skills.

**How we built it.** FastAPI backend and a LiveKit + Gemini Live agent on a Vultr server, bridged to
FaceTime by Chert. A second Vultr server runs a locked-down Playwright browser in throwaway Docker
containers (no downloads, network guard on every request) for risky pages and parking sites, and
streams it live onto the call. Tiger Data stores scan history, install counts and skill memory;
Typesense powers skill search and the scam map; Solana devnet handles consent-gated payments;
Next.js on Vercel for the dashboard.

**Challenges.** Making skills safe to share: a fingerprint-based verified list, a strict tool
allowlist, refusing symlinks and duplicate YAML keys, keeping unverified skills off the shared agent,
fencing skill and web text as data, and stripping links and phone numbers from anything texted from
the line. Real sites: ParkMobile needed a saved sign-in, a vehicle step and a hard stop at payment.

**What's next.** A helper app on your own computer so skills like a form filler and "find my file"
run locally (data stays on your machine, with a choice of Tiger Data or local storage), and letting
Chert host skills natively.

## 5. Tracks: what to point at

| Track | Point at |
|---|---|
| Security (main) | ScanSafe in the locked-down VM; verified/unverified skills, tool allowlist, fingerprinting |
| Chert | the whole platform: skills on real FaceTime calls, research call-back, parking |
| MLH Gemini | Gemini Live as the FaceTime agent; Gemini + Google Search research loop; AI review of skill PRs |
| Tiger Data | skill memory (cloud by default, local option), scan history, install counts, research jobs |
| Typesense | skill search, scam map search (scam look-alike vector search if built) |
| Solana | parking payment on devnet, only after "yes, pay" |
| Vultr | the agent server and the throwaway browser VM |
| A-Team | opt in |
| Cut unless true | Coder for Good (only with a real Coder workspace), Entire, DEV (only with a dev.to post) |

## 6. Test checklist (run each twice before recording)

| Skill | Do | Expect |
|---|---|---|
| Baseline | Switch to "out of the box", call | Plain assistant, no skills, no QR checking |
| List skills | Switch back, call, "what skills do I have?" | Names of the enabled skills |
| Research | "Research …", "anything else?" → no, hang up | Text + FaceTime back within ~15 min with cards per section |
| Parking | Scan the meter QR in the app, "yes, pay" | Official app filled live, pays only after yes |
| ParkMobile | Scan the ParkMobile QR while signed in | Confirm parking with the total, stops |
| ScanSafe | Hold a scam QR up | Locked-down browser live, scam verdict |
| Community page | Search "parking", open a plugin | Verified badge, tools, permissions |
| My apps | Sign in with your phone | Your saved skill data |
