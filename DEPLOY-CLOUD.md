# Put Specialty Tool Room in the Cloud

Use this when you want **one web link** that works on Mac, Windows, phone, or any browser — **no installs**.

You will get a URL like:

`https://specialty-tool-room.streamlit.app`

Bookmark that in Google Chrome on every device.

---

## What you need (free)

1. A **GitHub** account — [github.com](https://github.com)
2. A **Supabase** account — [supabase.com](https://supabase.com) (shared inventory across PCs)
3. A **Streamlit Cloud** account — [share.streamlit.io](https://share.streamlit.io) (hosts the app)

---

## Step 1 — Supabase database (this app only)

Create a **new** Supabase project just for Specialty Tool Room. Do **not** reuse Fixed Ops Hub or any other app’s project.

1. Go to [supabase.com](https://supabase.com) → **New project**.
2. Name it something like `specialty-tool-room`.
3. Open **SQL Editor → New query**.
4. Paste everything from `supabase/schema.sql` and click **Run**.
5. Go to **Project Settings → API** and copy:
   - **Project URL**
   - **service_role** key (keep this secret)

---

## Step 2 — Push code to GitHub

Already done if this repo is on GitHub as `specialty-tool-room`.

If you need to push updates later:

```bash
cd ~/Projects/specialty-tool-room
git add .
git commit -m "Update Specialty Tool Room"
git push
```

---

## Step 3 — Deploy on Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **Create app**.
3. Choose your `specialty-tool-room` repo, branch `main`, main file `app.py`.
4. Click **Advanced settings**:
   - **Python version:** `3.11` (do not use 3.14)
   - **Secrets:** paste from `streamlit-cloud-secrets.example.toml` and fill in real values:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_KEY = "your_service_role_key_here"
APP_PASSWORD = "Dino1169"
TECH_PASSWORD = "Jeep1234"
```

Use the **service_role** key from Supabase (not the anon key).

5. Click **Deploy**.

Wait 2–5 minutes. Streamlit gives you a public URL.

---

## Step 4 — Bookmark it

In **Google Chrome** on Mac and Windows, bookmark your Streamlit URL.

| Tab | Sign in with |
|-----|----------------|
| Manager | `APP_PASSWORD` |
| Admin | Username + password (add under Admin users while signed in as Manager) |
| Technician | Shared `TECH_PASSWORD` |

---

## Important notes

| Topic | Detail |
|-------|--------|
| **No Windows install** | Cloud runs on Streamlit servers — shop PCs only need Chrome |
| **Shared data** | Tools, checkouts, and locations sync through Supabase |
| **Updates** | Push changes to GitHub → Streamlit redeploys automatically |
| **First Manager** | `APP_PASSWORD` also seeds username `admin` for the Admin tab if needed |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| App asks for password and rejects Manager | Confirm `APP_PASSWORD` in Streamlit secrets matches what you type |
| Database shows LOCAL | Confirm `SUPABASE_URL` / `SUPABASE_KEY` and that `schema.sql` was run |
| DNS / nodename errors | Do not leave `YOUR_PROJECT` placeholders in secrets |
| Python build fails | Set Python to **3.11** in Advanced settings |
