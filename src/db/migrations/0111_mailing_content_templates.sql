-- Extend immutable template versions; existing inspection body slots are preserved.
alter table mailing_templates add column subject text
    check (subject is null or (length(btrim(subject)) between 1 and 300
                              and subject !~ '[[:cntrl:]]'));
alter table mailing_templates drop constraint mailing_templates_kind_check;
alter table mailing_templates drop constraint mailing_templates_slot_check;
alter table mailing_templates add constraint mailing_templates_kind_check
    check (kind in ('inspection', 'prescription', 'plan', 'document'));
alter table mailing_templates add constraint mailing_templates_slot_check check (
    (kind = 'inspection' and slot in ('plan', 'clean', 'empty', 'message'))
    or (kind in ('prescription', 'plan', 'document') and slot = 'message')
);
