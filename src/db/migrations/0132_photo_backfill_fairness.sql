-- Справедливая очередь дозагрузки: недоступный кадр не заслоняет хвост.
--
-- Отметка задаёт порядок попыток, а не бессрочную аренду. После сбоя процесса
-- кадр остаётся доказательством на повтор в той же очереди.
alter table photos add column backfill_attempted_at timestamptz;
comment on column photos.backfill_attempted_at is
    'Последнее взятие кадра ограниченным проходом дозагрузки; NULL — ещё не брали.';

create index photos_backfill_pending_idx on photos
    (backfill_attempted_at nulls first, created_at, id)
    where storage_path is null and purged_at is null;
