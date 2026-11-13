-- Prepared setup only: no hosted project is modified by the application.
-- Run in the chosen Supabase project when shared persistence is authorized.
-- These names are reserved for meet'cool. Existing unrelated tables are untouched.
begin;

create table if not exists public.meetcool_meetings (
    id text primary key,
    admin_token text not null,
    payload jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists public.meetcool_participants (
    meeting_id text not null references public.meetcool_meetings(id) on delete cascade,
    id text not null,
    payload jsonb not null,
    primary key (meeting_id, id)
);

alter table public.meetcool_meetings enable row level security;
alter table public.meetcool_participants enable row level security;

-- Browser clients never query these tables. FastAPI checks the invitation or
-- organizer token and accesses the database with its server-only service key.
revoke all on table public.meetcool_meetings from public, anon, authenticated;
revoke all on table public.meetcool_participants from public, anon, authenticated;
grant select, insert, update, delete on table public.meetcool_meetings to service_role;
grant select, insert, update, delete on table public.meetcool_participants to service_role;

commit;
