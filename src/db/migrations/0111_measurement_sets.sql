-- Explicit human-confirmed product groups; old inspections remain empty.
-- Existing inspection RLS and finalized-row protection apply to this column.
alter table inspections
    add column measurement_sets jsonb not null default '{}'::jsonb,
    add constraint inspections_measurement_sets_object check (
        jsonb_typeof(measurement_sets) = 'object'
    );
