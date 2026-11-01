-- Run once in Supabase: SQL Editor → New query → paste → Run
-- Safe to re-run: every statement is IF NOT EXISTS / ENABLE / GRANT.
-- An existing project that already ran the original file can instead run
-- supabase/migrations/20261101223000_app_errors_and_backups.sql
-- which is the same app_errors and backup tables.

create table if not exists specialty_tools_store (
    store_key text primary key,
    data jsonb not null,
    updated_at timestamptz default now()
);

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
