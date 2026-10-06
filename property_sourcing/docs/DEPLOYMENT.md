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

## Option B — Any cheap VPS, with systemd (recommended for always-on)
```bash
sudo apt update && sudo apt install -y python3-venv
git clone <your repo> /opt/property_sourcing && cd /opt/property_sourcing/property_sourcing
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in your real values

# Install the two ready-made service files (edit the paths inside first if
# you didn't clone to /opt/property_sourcing):
sudo cp deploy/systemd/property-sourcing-scheduler.service /etc/systemd/system/
sudo cp deploy/systemd/property-sourcing-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now property-sourcing-scheduler
sudo systemctl enable --now property-sourcing-dashboard

# Check status / logs any time with:
sudo systemctl status property-sourcing-scheduler
sudo journalctl -u property-sourcing-scheduler -f
```
This keeps both processes running across reboots and automatically restarts
them if they ever crash.

## Option C — Free-tier cloud (Render / Railway / Fly.io / Heroku-style)
Two ready-made configs are included:
- **`render.yaml`** — a Render.com Blueprint defining a free web service
  (dashboard) and a free background worker (scheduler). Just connect the
  repo on Render and it's auto-detected.
- **`Procfile`** — works with Railway, Heroku and similar platforms that
  read a `web` + `worker` process split directly.

Either way, make sure the web process binds to `0.0.0.0:$PORT` (already
handled by the `gunicorn -b 0.0.0.0:$PORT app:app` command in both configs).
Most of these platforms have a free tier sufficient for this workload
(lightweight, mostly idle, one batch of network calls per day).

## Backups
The entire system's state lives in one file: `data/sourcing.db`. Back it up
however you like (a daily `cp` to cloud storage is plenty for this scale).

## Before you flip the switch
Go through `docs/LAUNCH_CHECKLIST.md` and `docs/LEGAL_COMPLIANCE.md` first —
deployment is the easy part.
