-- Manual service settings; installation does not enable action plans.
create table service_settings (
    key text primary key check (key in ('action_plans_enabled')),
    enabled boolean not null,
    notifications_after timestamptz,
    changed_by text not null check (length(btrim(changed_by)) > 0),
    changed_at timestamptz not null default now()
);

grant select on service_settings to dodo_audit_app;
grant select, insert, update on service_settings to dodo_audit_admin;
alter table service_settings enable row level security;
alter table service_settings force row level security;
-- All product processes/spaces must observe the same operational switch.
create policy service_settings_app_read on service_settings
    for select to dodo_audit_app using (true);
create policy service_settings_admin on service_settings
    for all to dodo_audit_admin using (true) with check (true);
