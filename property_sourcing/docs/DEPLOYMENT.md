# Deployment (for when you're ready to actually launch)

You need one always-on machine to run `scheduler.py` (the automation loop)
and, optionally, `app.py` (the dashboard) so you can check in from anywhere.

## Option A — Docker (recommended, works anywhere)
```bash
cp .env.example .env   # fill in your real values first
docker compose up -d --build
```
This runs the dashboard on port 8000 and the scheduler loop, both backed by
the same `./data/sourcing.db` SQLite file on disk.

## Option B — Any cheap VPS (no Docker)
```bash
sudo apt update && sudo apt install -y python3-venv
git clone <your repo>  && cd property_sourcing
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your real values

# Run the scheduler forever with systemd (recommended) or a tool like pm2/supervisor:
nohup python scheduler.py >> scheduler.log 2>&1 &
nohup python app.py >> dashboard.log 2>&1 &
```
A `systemd` service file is the more robust way to keep these running across
reboots — happy to generate one when you're at this stage.

## Option C — Free-tier cloud (Render / Railway / Fly.io)
- Deploy as a **Background Worker** for `scheduler.py`.
- Deploy as a **Web Service** for `app.py` (make sure it binds to
  `0.0.0.0:$PORT` — set `DASHBOARD_PORT` from the platform's `$PORT` env var).
- Most of these have a free tier sufficient for this workload (lightweight,
  mostly idle, one network call batch per day).

## Backups
The entire system's state lives in one file: `data/sourcing.db`. Back it up
however you like (a daily `cp` to cloud storage is plenty for this scale).

## Before you flip the switch
Go through `docs/LAUNCH_CHECKLIST.md` and `docs/LEGAL_COMPLIANCE.md` first —
deployment is the easy part.
