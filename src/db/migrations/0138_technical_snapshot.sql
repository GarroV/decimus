-- Explicit technical checkpoint results and their pinned wording.
-- NULL means that this inspection did not collect technical confirmations.
-- Existing inspection RLS and finalized-row protection apply unchanged.
alter table inspections
    add column technical_snapshot jsonb,
    add constraint inspections_technical_snapshot_object check (
        technical_snapshot is null or jsonb_typeof(technical_snapshot) = 'object'
    );
