# DEPLOY — run in the cloud (GitHub Actions), laptop off

This runs the pipeline on GitHub's free cloud runners on a schedule, so it posts 24/7 without
your laptop. The code, schedule, and a secrets uploader are already in the repo; you do the
one-time steps below.

> **How it works:** a scheduled workflow (`.github/workflows/post.yml`) spins up a fresh Linux
> runner 3×/day, restores your secrets from encrypted **GitHub Secrets**, pulls gameplay from a
> **Release**, runs `python main.py`, and commits `data/state.json` back so it never double-posts.
> Secrets are **never** committed to the repo.

---

## ⚠️ Step 0 — Publish the OAuth app (REQUIRED, do this first)

While your Google OAuth consent screen is in **"Testing,"** refresh tokens **expire after 7 days**
— the cloud would break every week. Fix it permanently:

- Google Cloud Console → **APIs & Services → OAuth consent screen** → **PUBLISH APP** → Confirm.
- (For your own personal use you don't need Google's verification — publishing is enough.)

Then **re-run the three auth commands locally** so the saved tokens are long-lived, e.g.:
```powershell
.\.venv\Scripts\python.exe -m src.auth_youtube --token-file .\secrets\youtube_token.json
.\.venv\Scripts\python.exe -m src.auth_youtube --token-file .\secrets\youtube_token_stories.json
.\.venv\Scripts\python.exe -m src.auth_youtube --token-file .\secrets\youtube_token_characters.json
```

## Step 1 — Install the GitHub CLI
```powershell
winget install GitHub.cli
gh auth login        # pick GitHub.com → HTTPS → login in browser
```

## Step 2 — Push your secrets + gameplay to GitHub
```powershell
.\scripts\setup_github_secrets.ps1
```
This sets two encrypted GitHub Secrets (`ENV_FILE` = your `.env`, `SECRETS_TAR_B64` = your
`secrets/` folder) and uploads your `data/broll_gameplay/*.mp4` to a Release named `assets`.

## Step 3 — Commit the workflows + dedup state, then push
```powershell
git add .github .gitignore DEPLOY.md scripts/setup_github_secrets.ps1 data/state.json
git commit -m "Add GitHub Actions cloud deployment"
git push
```
*(Committing `data/state.json` gives the cloud your current "already-posted" history so it
doesn't repeat the test videos. Only `state.json` is tracked — no media, no secrets.)*

## Step 4 — Free minutes: make the repo public (recommended)
- **Public repo → unlimited free Actions minutes.** Settings → General → Danger Zone → Change visibility → Public.
- **Private is fine too** — 2,000 free min/month, and this uses ~700–900/month, so you're under the cap either way.
- Either way your **secrets stay private** (encrypted), and only `state.json` (post records, not sensitive) is in the repo.

## Step 5 — Set the schedule to your timezone
Times in `.github/workflows/post.yml` are **UTC**. Edit the three `cron:` lines to match when you
want to post in your local time. (e.g. if you're US Eastern, UTC = local + 4–5h.) Each line is one
post per channel; keep three lines for 3×/day. Commit + push after editing.

## Step 6 — Test it now (don't wait for the schedule)
- GitHub → **Actions** tab → **post-shorts** → **Run workflow** → Run.
- Watch the logs; it should generate + upload one Short per channel. Confirm they appear on YouTube.

## Step 7 — Turn OFF the local Windows schedule (avoid double-posting!)
The cloud now owns posting. Disable the laptop's scheduler so they don't both run:
```powershell
.\scripts\remove_schedule.ps1
```

---

## Done
The cloud posts on its own, laptop on or off. The daily `state.json` commits also keep the
scheduled workflow alive (GitHub disables schedules after 60 days of *no* repo activity).

### Updating secrets later (token re-auth, new keys, new gameplay)
Re-run `.\scripts\setup_github_secrets.ps1` after changing `.env`, re-authing a token, or adding
gameplay — it overwrites the secrets/release.

### Things to know
- **Cron can fire a few minutes late** under GitHub load — fine for 3×/day.
- **First run is slower** (downloads Whisper/YuNet models + gameplay); after that they're cached.
- **One workflow run = one post per enabled channel.** Adjust per-channel `max_per_run` or add
  cron lines to change frequency.
- **Don't run the local schedule and the cloud at the same time** — their `state.json` would
  diverge and double-post.
