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
| Technician | Shared `TECH_PASSWORD` | Check Out / In, Out Now, Catalog (view), Reports, History |

`APP_PASSWORD` also seeds a starter Admin account (`admin`) if none exist yet. Add more admins in-app under **Admin users**.

Without Supabase, the app still works locally using `data/specialty_tools.json`.

## What it does

| Screen | Purpose |
|--------|---------|
| Check Out / In | Search a tool, assign to a tech, return it later |
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
