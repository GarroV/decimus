-- Keep technical checkpoint confirmations in the existing append-only audit.
-- A checkpoint has no finding UUID when its answer is OK or not applicable.
alter table inspection_edits alter column finding_id drop not null;
alter table inspection_edits drop constraint inspection_edits_kind_check;
alter table inspection_edits
    add constraint inspection_edits_kind_check check (
        kind in ('revise', 'add', 'delete', 'technical')
    );

comment on column inspection_edits.finding_id is
    'Finding affected by this edit; NULL for an explicit technical checkpoint confirmation. '
    'Technical checkpoint id, zone and complete before/after evidence are in changes.';
