## Inspiration
Chert gives AI agents their own iMessage and FaceTime line, but every agent starts from zero, and FaceTime, Chert's superpower, is something almost nobody builds for (its closest competitor, Photon, has messaging and an MCP server but no FaceTime). We wanted anyone to be able to give a Chert agent new abilities that work on a real call, and to share them safely: a skill from a stranger is like a QR code from a stranger. You don't know what it does until it runs.

## What it does
**Toolstone is an open-source skill library for Chert.** Anyone can build a skill, and every Chert agent can use it on a live FaceTime call.

- **Skills are recipes:** a short `plugin.yaml` in a public GitHub folder with plain-text instructions and a list of allowed tools. Nothing in a skill is ever executed; tools are wired by name from our own code.
- **Verified vs. unverified:** a skill is verified only when the SHA-256 fingerprint of its exact text is in an admin-owned list. Edit it and it's unverified again. Unverified skills never get payments, research or your computer, and never reach the shared agent.
- **Community plugins page:** a clone of the Chert console (built with Chert's permission) with a "Community plugins" tab: search (Typesense), verified badges, and a switch between *Chert out of the box* and *Chert + community skills*.
- **On a call**, the agent picks a skill by what you mean, in your own words, and switches it on by itself.

Skills we built:
- **Tutor:** handwrites the lesson step by step on your FaceTime screen, checks in after every step, explains the why on sticky notes, draws graphs (with tangent lines and slopes), and shows a "Next step in ~3s" countdown so a pause never looks broken.
- **Research:** you ask, it hangs up, then researches on its own: published studies from OpenAlex plus Google Search, read by Gemini over at least four rounds with a capped spend. It texts you a report page that cites the papers (journal, year, citations), then FaceTimes you back with a section-by-section walkthrough you can steer ("skip to the dopamine part").
- **Vercel:** "How's my site?" runs through a small helper app on your own computer. Your key stays in a local file; the AI and our servers never see it. A redeploy needs you to say "yes, redeploy".
- **ScanSafe (security):** hold up a QR code. It opens the link in a throwaway, locked-down browser on a Vultr VM, streams it live to your call, and warns you before you pay a scammer.
- Also in the library: **Parking** (pays on Solana devnet only after you say "yes, pay"), Squat coach, Study buddy, Plugin finder.

## How we built it
- **Agent:** LiveKit Agents with Gemini Live on a Vultr server, bridged to FaceTime by Chert. The video you see on the call is our own 720x1280 renderer (Python + Pillow): handwriting with a real handwriting font, math symbols, and graphs drawn by a safe math parser (no code execution).
- **Backend:** FastAPI on Vultr; a second Vultr VM runs Playwright in throwaway Docker containers for ScanSafe.
- **Tiger Data (Postgres):** skill memory, research jobs (every research step is written as it happens), helper-app pairings, accounts, scan history.
- **Research engine:** Gemini 3.5 Flash with Google Search grounding plus OpenAlex studies, a plan → search → reflect loop, and spend caps (28 Google searches per job, 120 per day).
- **Helper app:** a small Python app on your computer that connects out to our relay, runs only fixed job types, and keeps keys local.
- **Solana devnet** for consent-gated payments, **Next.js on Vercel** for the console clone.
- A validator checks every skill (format, tool allowlist, no symlinks, no duplicate YAML keys), backed by 1,200+ automated tests.

### How we use Typesense
Typesense is the search layer for everything a person or the agent looks up. We run four collections:
- **`plugins`: the skill library.** Every skill in the repo is indexed (name, trigger phrases, summary, author, weighted 4/3/2/1). It powers the search box on the Community plugins page (type "tutor" and the page says "searched with Typesense"). It also powers the agent's `find_plugin` tool on a live call: say "is there a skill for parking?" and the agent searches Typesense, then offers to turn on a verified match.
- **`research_reports`: your research library.** Every finished report is indexed (topic, sections, summary, weighted 3/2/1) and filtered to its owner, so on a later call you can ask "what did you find about Adderall last time?" and the agent searches your own past reports.
- **`scam_pins`: the scam map.** Every QR scan the security skill flags becomes a geo-pinned document. ScanSafe runs a nearby search on it, which is how its warning can say "other people nearby have reported it too".
- **`scans`: searchable scan history.**

If Typesense is down, skill and report searches fall back to a plain substring match, so a call never breaks.

### How we use Coder
Coder is where you write a new Toolstone skill. We self-host **Coder v2.39 on our Vultr server** with our own template, **`toolstone-skills`**:
- A workspace is a Docker container with **VS Code in the browser** (code-server module).
- On start it **clones the public Toolstone repo** into `~/toolstone` and prints the three steps: copy a skill folder in `plugins/`, edit its `plugin.yaml` (instructions + allowed tools), then run `python3 -m api.plugins_index --check` to validate it before opening a pull request.
- We used it ourselves: our demo workspace `toolstone-demo` runs on the template, and the `scansafe-dev` workspace is where we developed the security skill.

The point: contributing a skill takes no local setup. Open a workspace, edit one YAML file, check it, send a PR.

## Challenges we ran into
- **Real-time voice is fragile.** Gemini Live ended our calls at exactly 2:00 because we were streaming the camera. We stopped sending video to Gemini (ScanSafe reads QR codes with our own decoder) and moved to a newer Live model after intermittent server errors.
- **Models follow scripts too literally.** Our first prompts gave sample lines and trigger phrases, so the tutor parroted the same check-in and only started on exact words. We rewrote everything to work by meaning.
- **Safety for strangers' skills:** fingerprinted verification, a strict tool allowlist, skill text fenced as data, links and phone numbers stripped from anything texted from the line, and caller identity taken only from the call itself.
- **Phone-line plumbing:** a shared FaceTime line stays busy for a moment after each call, and queued calls left stale entries that blocked new ones. We now retry the line ourselves.
- **You can't screen-record FaceTime on an iPhone**, so our demo footage is recorded on the server: exactly the frames the agent sends to the call.

## Accomplishments that we're proud of
- Everything in the demo is a real FaceTime call: handwritten notes appearing live, a research agent that hangs up, reads 30 published studies and calls back, and a scam QR stopped in a sandbox.
- A safety model where a skill from a stranger can't touch money, research or your computer until it's verified, and any edit un-verifies it.
- Keys that never leave your computer, even though the AI on the call can use them.

## What we learned
- On a phone call, latency and turn-taking matter more than anything else: a two-second silence feels broken, which is why the tutor shows a countdown.
- Treat skills like untrusted code even when they're "just text."
- FaceTime is a canvas, not just a voice channel: the screen is where a tutor writes and a research agent shows its sources.

## What's next for Toolstone
- Chert-hosted skills: a real "Community plugins" tab in the Chert console, with a public review queue.
- More local connectors through the helper app (Supabase, ElevenLabs), and importing instruction-only skills from other ecosystems.
- Self-hosting: run the agent on your own server with your own Chert line, while skills that need your keys keep running on your own computer.
