-- 0052_agg_requests.sql
--
-- Заявка на обновление оценок агрегаторов вне суточного расписания (D420,
-- docs/17-aggregators.md). Контроль УК просит обновить кнопкой на странице
-- рейтингов или через Claude (MCP) — но собирает не тот процесс, что принял
-- просьбу: сбор живёт в боте (D389). Заявка — строка здесь; бот раз в минуту
-- смотрит таблицу, собирает указанные агрегаторы и закрывает заявку исходом.
--
-- `aggregators` — какие собрать; `null` — все, что бот собирает сам. Незакрытая
-- заявка может быть только одна (частичный уникальный индекс): повторная просьба,
-- пока предыдущая не выполнена, второй строки не плодит — ей отвечают «уже в
-- очереди». Закрытая заявка остаётся следом: кто, когда и чем кончилось.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table agg.requests (
    id bigserial primary key,
    requested_at timestamptz not null default now(),
    requested_by text not null check (length(btrim(requested_by)) between 1 and 200),
    aggregators text[] check (aggregators is null or cardinality(aggregators) > 0),
    done_at timestamptz,
    outcome text check (outcome in ('ok', 'failed')),
    error text,
    check ((done_at is null) = (outcome is null))
);
create unique index requests_one_open_idx on agg.requests ((true)) where done_at is null;

-- Принимает просьбу тот, кто её получил (веб, MCP), закрывает бот: все они ходят
-- ролью приложения, поэтому право на правку — только на столбцы закрытия.
grant select, insert on agg.requests to dodo_audit_app;
grant update (done_at, outcome, error) on agg.requests to dodo_audit_app;
grant usage on sequence agg.requests_id_seq to dodo_audit_app;
grant select on agg.requests to dodo_audit_admin;
