-- Human-confirmed active finding splits accompany the new inspection snapshot.
-- Existing rows and legacy remain NULL; no accepted inspection is rewritten.
alter table inspections
    add column finding_history jsonb,
    add constraint inspections_finding_history_array check (
        finding_history is null or jsonb_typeof(finding_history) = 'array'
    );
