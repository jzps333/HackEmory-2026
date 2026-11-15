# Toolstone helper app

A small program that runs on **your own computer** so your FaceTime agent can fill web forms and
check or redeploy Vercel projects for you. Your saved info and API keys never leave this computer:
the helper connects out to the Toolstone relay, asks for jobs, runs them here, and sends back only
results (field labels, deploy status) plus screenshots of the browser window it opens.

Contract: `docs/superpowers/specs/2026-11-15-helper-app-contract.md`.

## Install (macOS)

```bash
python3 -m pip install -r runner/requirements.txt
python3 -m playwright install chromium
```

## Use

```bash
python3 runner/toolstone_runner.py pair      # text a code from your phone; links this computer
python3 runner/toolstone_runner.py profile   # creates ~/.toolstone/profile.json and ~/.toolstone/.env
python3 runner/toolstone_runner.py run       # waits for jobs; Ctrl-C to stop
python3 runner/toolstone_runner.py status    # paired? which connections?
```

- **profile.json** starts with placeholder demo values (marked `_demo`). Replace them with your
  own: name, first_name, last_name, email, phone, street_address, city, state, zip,
  license_plate, vehicle_make, vehicle_model, vehicle_color.
- **.env** holds keys. To connect Vercel, uncomment and fill in `VERCEL_TOKEN=` (and
  `VERCEL_TEAM_ID=` for a team), from https://vercel.com/account/tokens.

Environment: `TOOLSTONE_API` (default `https://api.scansafe.nyc`), `TOOLSTONE_HOME`
(default `~/.toolstone`), `TOOLSTONE_HEADLESS=1` (no visible window; tests only),
`TOOLSTONE_FILL_DELAY` (seconds between fields, default 0.25, so the fill is visible on video).

## Jobs

| Kind | What it does |
|---|---|
| `form_fill` | Opens a visible Chromium window on the URL (or your active Google Chrome tab when the URL is empty), fills fields from profile.json, streams ~3 screenshots/s. Never touches password, card/CVV, SSN, bank, file fields or checkboxes. Does not submit. Keeps the page open 10 minutes. |
| `form_submit` | Only after you said "yes, submit": ticks the "I certify / agree" box (never marketing opt-ins) and clicks the form's own Submit button. |
| `vercel_status` | Latest deployment of up to 5 projects (or the named one). |
| `vercel_redeploy` | Redeploys the project's latest production deployment (after you said "yes, redeploy"). |
| `connections_list` | Names of connected services (e.g. `vercel`), never keys. |

Any other job kind is refused.

## Security

- `~/.toolstone/` is 0700; `runner.json`, `profile.json` and `.env` are 0600.
- The runner token and keys are never printed, logged, put in results, progress notes or frames;
  outgoing text is scrubbed of them. Form results carry field labels and profile key names, not
  values. Text read back from a page after submitting is scrubbed of your name, email, phone,
  street and plate.
- Only `http(s)` URLs are opened. The only command the helper runs is the fixed
  `osascript` call that reads the active Chrome tab's URL.
- The phone sign-in token used during `pair` is revoked right after pairing; only the runner
  token is kept.
