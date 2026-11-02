-- Explicit country mailing To: defaults. Absence restores legacy behaviour;
-- an empty configured list suppresses fallback. Issuing a prescription never updates it.
create table country_mailing_recipients (
    country text primary key check (country ~ '^[A-Z]{2}$'),
    recipients text not null check (
        length(recipients) <= 2000 and recipients = lower(recipients)
        and recipients !~ '[[:cntrl:]]'
        and (recipients = '' or recipients ~
            ('^[^@[:space:],;<>"''[:cntrl:]]+@[^@[:space:],;<>"''[:cntrl:]]+\.[^@[:space:],;<>"''[:cntrl:]]+'
             || '(, [^@[:space:],;<>"''[:cntrl:]]+@[^@[:space:],;<>"''[:cntrl:]]+\.[^@[:space:],;<>"''[:cntrl:]]+)*$'))
    ),
    updated_by text not null check (length(btrim(updated_by)) > 0),
    updated_at timestamptz not null default now()
);
grant select on country_mailing_recipients to dodo_audit_app;
grant select, insert, update, delete on country_mailing_recipients to dodo_audit_admin;
alter table country_mailing_recipients enable row level security;
alter table country_mailing_recipients force row level security;
create policy country_mailing_recipients_read on country_mailing_recipients
    for select to dodo_audit_app using (decimus_space() in ('*', 'HQ'));
create policy country_mailing_recipients_admin on country_mailing_recipients
    for all to dodo_audit_admin using (true) with check (true);
