# Form filler

Say "fill out this form" on FaceTime. The form opens in a browser on **your own computer** and is
filled in from the info saved there (`~/.toolstone/profile.json`), while you watch it live on the
call's video. The agent reads back which fields it filled and which it couldn't, then asks
"Should I submit it? Say yes, submit." Nothing is sent until you say that.

- **Runs on:** your own computer, through the Toolstone helper app (connect it once with
  `python3 runner/toolstone_runner.py pair`, then keep `python3 runner/toolstone_runner.py run`
  going). Our server only relays the job and the picture. **Tools:** speak, screen, computer
  (verified plugins only).
- **Guardrails:** your saved info stays on your computer: the AI only hears field names, never
  what was typed. Password, card, SSN and file fields are never touched. It only submits after
  your own "yes, submit".
