# Family Newsletter Backend

Phase 1 scaffold for a local-first family morning newsletter backend.

## Run locally

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -e .
python -m uvicorn family_newsletter.app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/config/effective`

Generate today's preview:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/runs/today/preview
```

The preview endpoint writes HTML and plaintext drafts under `data/previews/`.

The app runs in sample mode by default. Copy `.env.example` to `.env` when real locations, recipients, source URLs, or provider credentials are available.

## Email delivery

The newsletter is sent over Gmail SMTP (`smtp.gmail.com:587`, STARTTLS). Every
run **regenerates the entire newsletter fresh** (all sections re-fetched)
immediately before sending — no stale/cached previews are ever emailed.

### 1. One-time setup

1. Copy `.env.example` to `.env` (this file is git-ignored — credentials are
   never committed).
2. Generate a **Gmail App Password** (not your normal login password):
   Google Account → Security → 2-Step Verification (must be on) → App passwords
   → generate a 16-character password.
3. Fill in `.env`:

   ```dotenv
   EMAIL_FROM=your-gmail@gmail.com
   EMAIL_RECIPIENTS=person1@example.com, person2@example.com
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your-gmail@gmail.com
   SMTP_PASSWORD=your16charapppassword
   ```

   Recipients may instead be listed under `email.recipients` in the config YAML;
   `EMAIL_RECIPIENTS` takes precedence when set.

### 2. Dry run (safe before credentials exist)

Regenerate + render the newsletter and report what *would* be sent, without
transmitting anything:

```powershell
python -m family_newsletter.app.run_daily --now --dry-run
```

It prints a JSON result including `would_send`, the resolved `recipients`, and
any `missing_config`. It also writes the HTML/text drafts to `data/previews/`.

### 3. Send once now

```powershell
python -m family_newsletter.app.run_daily --now
```

### 4. Run the daily scheduler

Foreground scheduler that fires every morning at **8:00 AM America/Los_Angeles**
(configurable via `NEWSLETTER_SEND_TIME` / `NEWSLETTER_TIMEZONE`):

```powershell
python -m family_newsletter.app.run_daily          # real send at 8:00 AM LA
python -m family_newsletter.app.run_daily --dry-run # scheduled dry runs
```

### Surviving reboots on Windows 11 (Task Scheduler)

APScheduler only runs while the Python process is alive, so register it with
Windows Task Scheduler to auto-start on login/boot:

1. Open **Task Scheduler** → **Create Task…** (not "Basic Task").
2. **General**: name it `Family Newsletter`; select *Run whether user is logged
   on or not*; check *Run with highest privileges*.
3. **Triggers**: New → *At startup* (and optionally *At log on*). This keeps the
   scheduler process running across reboots; the 8:00 AM timing is handled
   inside the app.
4. **Actions**: New → *Start a program*:
   - Program/script: the venv Python, e.g.
     `C:\Users\allyz\Documents\Family newsletter\.venv\Scripts\python.exe`
   - Add arguments: `-m family_newsletter.app.run_daily`
   - Start in: `C:\Users\allyz\Documents\Family newsletter`
5. **Settings**: check *If the task fails, restart every 1 minute* and *If the
   running task does not end when requested, force it to stop* so it self-heals.

Alternatively, skip the long-running scheduler and let Task Scheduler own the
timing directly: use a **Daily** trigger at 8:00 AM and set the action arguments
to `-m family_newsletter.app.run_daily --now`. This fires a fresh
regenerate-and-send once per day and exits, and also survives reboots.
