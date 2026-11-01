-- Save-failure log and daily snapshots for Specialty Tool Room.
--
-- Run this once in the Supabase SQL Editor for the EXISTING project
-- (Dashboard → SQL Editor → New query → paste → Run).
-- Do not expect this repository to apply it. Nothing here drops or rewrites
-- specialty_tools.
--
-- Until public.app_errors exists, the app records a failed save on the
-- table that is already in production:
--   specialty_tools_store.store_key = 'app_errors'
-- That row is not the inventory. After this migration, new failures are
-- inserted into public.app_errors instead.
--
-- The daily GitHub Action inserts one row into specialty_tools_backups and
-- also uploads a JSON artifact. The artifact still works if this migration
-- has not been run; the table insert will fail until it has.

create table if not exists public.app_errors (
    id uuid primary key default gen_random_uuid(),
    occurred_at timestamptz not null default now(),
    action text not null,
    error text not null,
    -- Signed-in technician, admin, or Manager. "user" is reserved in Postgres.
    user_name text not null default '',
    detail jsonb not null default '{}'::jsonb
);

create index if not exists app_errors_occurred_at_idx
    on public.app_errors (occurred_at desc);

alter table public.app_errors enable row level security;

revoke all on table public.app_errors from anon, authenticated;
grant select, insert, update, delete on table public.app_errors to service_role;

create table if not exists public.specialty_tools_backups (
    id uuid primary key default gen_random_uuid(),
    store_key text not null,
    data jsonb not null,
    source_updated_at timestamptz,
    backed_up_at timestamptz not null default now()
);

create index if not exists specialty_tools_backups_backed_up_at_idx
    on public.specialty_tools_backups (backed_up_at desc);

alter table public.specialty_tools_backups enable row level security;

revoke all on table public.specialty_tools_backups from anon, authenticated;
grant select, insert, update, delete on table public.specialty_tools_backups to service_role;
