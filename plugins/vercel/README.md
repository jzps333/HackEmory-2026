# Vercel

Ask "how's my site?" on FaceTime. The agent reads your Vercel projects' latest deploys (did it
work, when, which commit) and, if one failed, offers to redeploy it. It only redeploys after you
say "yes, redeploy".

- **Runs on:** your own computer, through the Toolstone helper app (connect it once with
  `python3 runner/toolstone_runner.py pair`, then keep `python3 runner/toolstone_runner.py run`
  going). Our server only relays the job and the result. **Tools:** speak, screen, computer
  (verified plugins only).
- **Setup:** put `VERCEL_TOKEN=...` (and optionally `VERCEL_TEAM_ID=...`) in `~/.toolstone/.env`
  on your computer. The key never leaves it: the AI and our server never see it, only deploy
  states.
