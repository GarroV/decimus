-- D690: contact people and inspection recipients are separate from access spaces.
-- 0109 is reserved for the persisted electronic action-plan switch.
-- No historical backfill and no changes to country ownership or DKK contacts.
create table country_contacts (
    id uuid primary key default gen_random_uuid(),
    country text not null check (country ~ '^[A-Z]{2}$'),
    kind text not null check (kind in ('partner', 'mailing')),
    name text not null default ''
        check (length(name) <= 200 and name !~ '[[:cntrl:]]'),
    email text not null default ''
        check (length(email) <= 254 and
            (email = '' or email ~
                '^[^@[:space:],;:<>"''[:cntrl:]]+@[^@[:space:],;:<>"''[:cntrl:]]+\.[^@[:space:],;:<>"''[:cntrl:]]+$')),
    updated_by text not null check (length(btrim(updated_by)) > 0),
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    check (length(btrim(name)) > 0 or email <> ''),
    check (kind <> 'mailing' or email <> '')
);
create index country_contacts_country_idx on country_contacts(country, kind, created_at, id);
create unique index country_contacts_email_idx on country_contacts(country, kind, lower(email))
    where email <> '';
create unique index country_contacts_name_idx on country_contacts(country, kind, lower(name))
    where email = '';

comment on table country_contacts is
    'Country partner contacts and inspection mail recipients; private to HQ, separate from access spaces and DKK contracts.';

grant select on country_contacts to dodo_audit_app;
grant select, insert, delete on country_contacts to dodo_audit_admin;
grant update(name, email, updated_by, updated_at) on country_contacts to dodo_audit_admin;
alter table country_contacts enable row level security;
alter table country_contacts force row level security;
create policy country_contacts_app_read on country_contacts for select to dodo_audit_app
    using (decimus_space() in ('*', 'HQ'));
create policy country_contacts_admin on country_contacts for all to dodo_audit_admin
    using (true) with check (true);
