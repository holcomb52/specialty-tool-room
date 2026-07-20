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
streamlit run app.py
```

Opens at [http://localhost:8511](http://localhost:8511).

## Supabase (recommended for cloud / multi-PC)

1. Create a Supabase project
2. SQL Editor → run `supabase/schema.sql`
3. Copy Project URL + **service_role** key into `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_KEY = "your_service_role_key"
APP_PASSWORD = "choose-a-strong-password"
```

Without Supabase, the app still works locally using `data/specialty_tools.json`.

## What it does

| Screen | Purpose |
|--------|---------|
| Check Out / In | Search a tool, assign to a tech, return it later |
| Out Now | Who has what right now |
| Catalog | Search inventory, edit location / qty |
| Add Tool | Log new SST arrivals |
| Technicians | Names for the check-out dropdown |
| Import | Refresh from `.xls` / `.xlsx` inventory |
| History | Audit trail |

## Seed data

`data/specialty_tools_seed.json` was built from:

`2017 NEW SMYRNA BEACH CHRYSLER TOOL INV.xls`

(~1,756 tools — active + non-current). First launch copies that into the live store.
