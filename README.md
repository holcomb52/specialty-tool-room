# Specialty Tool Room

Standalone Streamlit app for **specialty service tool** accountability at New Smyrna Beach Chrysler.

Technicians check tools **out** and **in** from the special tool room. New tools can be added with a location/assignment. The catalog is seeded from the Chrysler Tool Organization inventory spreadsheet.

## Stack

| Layer | Tech |
|-------|------|
| UI | Streamlit |
| Database | Optional Supabase (Postgres jsonb store) |
| Cloud | Streamlit Community Cloud |

## Quick start (local)

```bash
cd ~/Projects/specialty-tool-room
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py --server.port 8511
```

Opens at [http://localhost:8511](http://localhost:8511).

## Cloud deploy (shop-wide)

Full walkthrough: **[DEPLOY-CLOUD.md](DEPLOY-CLOUD.md)**

Quick summary:

1. Create a **new** Supabase project for this app only (do not reuse Fixed Ops Hub)
2. SQL Editor → run `supabase/schema.sql`
3. Deploy at [share.streamlit.io](https://share.streamlit.io) with secrets from `streamlit-cloud-secrets.example.toml`
4. Bookmark your `https://….streamlit.app` URL

## Supabase (this project only)

1. Create a **dedicated** Supabase project named e.g. `specialty-tool-room`
2. SQL Editor → run `supabase/schema.sql`
3. Copy that project’s URL + **service_role** key into `.streamlit/secrets.toml` or Streamlit Cloud secrets:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_KEY = "your_service_role_key"
APP_PASSWORD = "choose-a-strong-manager-password"
TECH_PASSWORD = "choose-a-shared-tech-password"
```

**Logins**
| Tab | How to sign in | Can see |
|-----|----------------|---------|
| Manager | `APP_PASSWORD` | Everything, including **Admin users** |
| Admin | Username + password (added under Admin users) | Everything except **Admin users** |
| Technician | Shared `TECH_PASSWORD` | Check Out, Check In, Out Now, Catalog (view), Reports, History |

`APP_PASSWORD` also seeds a starter Admin account (`admin`) if none exist yet. Add more admins in-app under **Admin users**.

Without Supabase, the app still works locally using `data/specialty_tools.json`.

## Tests, failed saves, and backups

```bash
pip install -r requirements-dev.txt
python -m pytest
```

GitHub Actions runs that on every push and pull request. The test job has no Supabase secrets. Tests mock the database and do not read or write the shop project.

When a save to Supabase fails, the screen still says **Not saved to the shop database**. The same failure is stored with a timestamp, the action (`checkout`, `checkin`, and so on), the error text, and the signed-in user (`user_name`). Until the migration below has been run, that record is a row in `specialty_tools_store` with `store_key = app_errors` (not the inventory). After the migration, new failures go to `public.app_errors`.

### What to set up once

1. **SQL (existing project).** In the Supabase SQL Editor, run `supabase/migrations/20261101223000_app_errors_and_backups.sql`. This adds `app_errors` and `specialty_tools_backups` and turns on row level security. It does not change the inventory row. A brand-new project can keep using `supabase/schema.sql`, which now includes the same tables.
2. **GitHub Actions secrets** (Settings → Secrets and variables → Actions). Do not commit these.
   - `SUPABASE_URL` — same Project URL as Streamlit
   - `SUPABASE_SERVICE_ROLE_KEY` — the service_role key (the same value as Streamlit's `SUPABASE_KEY`, not the anon key)
3. **Daily backup.** `.github/workflows/backup-specialty-tools.yml` runs at 11:15 UTC (6:15am EST / 7:15am EDT). It reads `specialty_tools`, uploads `backups/specialty_tools.json` as an artifact kept 90 days, and inserts a copy into `specialty_tools_backups` (45 days kept in the table). You can also run it from the Actions tab. If the migration has not been applied, the artifact is still uploaded and the job fails on the table insert.
4. **Signed-in smoke test (optional, read-only).** It logs in and opens every tab for that role. It does not click Check out or Check in, and it blocks Supabase writes.

   ```bash
   export TOOL_ROOM_SMOKE=1
   export TOOL_ROOM_SMOKE_ROLE=technician   # or admin, or manager
   export TOOL_ROOM_SMOKE_PASSWORD='the password for that role'
   # admin only:
   # export TOOL_ROOM_SMOKE_USERNAME=some-admin
   # optional, to read the live catalog while staying read-only:
   # export SUPABASE_URL=...
   # export SUPABASE_KEY=...   # service_role
   python scripts/smoke_signed_in.py
   ```

   The same script is on the Actions tab as **Signed-in smoke test**, manual only. That workflow also needs secrets `TOOL_ROOM_SMOKE_ROLE`, `TOOL_ROOM_SMOKE_PASSWORD`, and `TOOL_ROOM_SMOKE_USERNAME` (admin only). It reuses `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

## What it does

| Screen | Purpose |
|--------|---------|
| Check Out | Search a tool and assign it to a tech |
| Check In | Return a tool that was signed out |
| Out Now | Who has what right now |
| Catalog | Search inventory, edit location / qty |
| Reports | By tech / all out / returned — export PDF |
| Add Tool | Log new SST arrivals |
| Technicians | Names for the check-out dropdown |
| Admin users | Add/remove people with full admin access |
| Import | Refresh from `.xls` / `.xlsx` inventory |
| History | Audit trail |

Tools out **5+ days** show a yellow alert at the top of every screen. You can pick a date to hide that alert until then, or check the tool in from the alert.

## Seed data

`data/specialty_tools_seed.json` was built from:

`2017 NEW SMYRNA BEACH CHRYSLER TOOL INV.xls`

(~1,756 tools — active + non-current). First launch copies that into the live store.
