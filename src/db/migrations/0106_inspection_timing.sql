-- Visit timestamps are primary evidence, independent of push and acceptance time.
-- Historical rows deliberately stay NULL; no inference or backfill.
alter table inspections
    add column started_at timestamptz,
    add column finished_at timestamptz,
    add constraint inspections_visit_interval check (
        finished_at is null or (started_at is not null and finished_at >= started_at)
    );
