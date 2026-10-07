# Rate Case Workbench (v1)

A utility rate-case workbench: track Ohio distribution rate cases, compare as-filed
vs. Staff vs. final numbers, keep a tariff/rider inventory, and import it all from Excel.

## Run it

```bash
cd ~/workspace/rate-case-app/app
python3 -m venv .venv          # first time only
.venv/bin/pip install -r requirements.txt   # first time only
.venv/bin/uvicorn main:app --reload
```

Then open http://127.0.0.1:8000. The starter dataset (Ohio electric cases) loads
itself on first launch.

To reload the starter data any time: `cd ~/workspace/rate-case-app/app && .venv/bin/python seed.py`
(it never duplicates anything), or use the "Reload starter data" button on the Import page.

To change where the database lives: `RATECASE_DB=/path/to/file.db .venv/bin/uvicorn main:app --reload`

## What's in v1

- **Dashboard** - utility cards: latest case, last approved ROE, last revenue outcome.
- **Cases** - case list + detail pages with the three-way comparison table
  (as-filed vs. Staff vs. final/stipulation), per test year for multi-year plans.
- **Tariffs & Riders** - inventory with disposition flags: rolls into base rates,
  stays separate, or undecided.
- **Compare** - offline SVG bar charts: revenue outcomes and ROEs across utilities.
- **Import** - download Excel templates, fill them in, upload; friendly plain-language
  validation before anything is saved. Nothing loads unless every row passes.

## Tests

```bash
cd ~/workspace/rate-case-app/app && .venv/bin/python -m pytest tests/ -q
```

## Stack

Python / FastAPI / SQLite (SQLAlchemy) / Jinja2. No frontend build step, no CDN -
the app works fully offline.

## Host it on Railway

The app ships with a `Dockerfile` and `railway.toml` — Railway picks up the
Dockerfile automatically.

1. Push this `app/` folder to a GitHub repo (or run `railway up` from here
   with the Railway CLI).
2. In Railway: New Project → Deploy from Repo → pick the repo. (Or: New
   Service → Dockerfile, if deploying an empty project.)
3. Add a **volume**: service → Volumes → New Volume, mount path `/data`.
4. Set environment variables on the service:
   - `RATECASE_DB=/data/ratecase.db` — keeps the database on the volume so
     imports and scenarios survive redeploys.
   - `APP_PASSWORD=…` — team sign-in password. The app refuses to serve
     anything without it once set. Pick something strong; everyone shares it.
5. Deploy. Railway gives you a public `*.up.railway.app` URL (add your own
   domain later under Settings → Domains — free TLS included).

On first boot against the empty volume the starter dataset seeds itself, same
as local. `/healthz` is the deploy health check.
