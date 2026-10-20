-- 0081_inspection_edits.sql
--
-- Журнал правок записей проверки на приёмке (аудит F-134, #1006). Вычитка —
-- базовая механика приёмки, и правит её и управляющая компания, и партнёр (D341,
-- D367): правка не ограничивается, но у каждой правки должен быть след. Записи и
-- оценка читаются как факт, а до этой миграции «было D1, стало D3» нигде не
-- оставалось: не восстановить, кто и когда переписал находку и сдвинул процент.
--
-- 1. Одна строка на правку (`revise` — исправление записи, `add` — добавление
--    записи): кто (учётка и её роль), когда, в какой проверке и записи, и ЧТО
--    изменилось — `changes` вида {"level": {"old": "D1", "new": "D3"}, ...} по
--    каждому изменившемуся полю записи и по оценке (`score_pct`, `score_grade`, `score_deductions`).
--    Отдельная таблица, а не `action_journal` (0067): там действие обрезается до 120
--    знаков и хранит только сводку цели, «старое → новое» в нём не уместить.
-- 2. Строка пишется в ТОЙ ЖЕ транзакции, что и сама правка (`src/db/revise.py`,
--    `src/db/review_edit.py`): откатилась правка — откатилась и строка, прошла — не
--    бывает без строки.
-- 3. Роль приложения только ДОПИСЫВАЕТ (`insert`), как у журналов и расхода модели:
--    ни `select`, ни `update`, ни `delete`. Задним числом не поправить.
-- 4. Внешних ключей нет намеренно: след правки не должен исчезать вместе со
--    строкой проверки или записи и не должен мешать её удалению. `tenant_code` —
--    пространство правки: правит каждый только своё (D283), оно же пространство
--    проверки; УК это или партнёр, видно по нему и по роли.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table inspection_edits (
    id bigint generated always as identity primary key,
    occurred_at timestamptz not null default now(),
    inspection_id uuid not null,
    finding_id uuid not null,
    tenant_code text not null,
    -- Учётка правившего: логин и роль на момент правки (роль потом сменится, запись нет).
    user_id uuid not null,
    login text not null check (length(btrim(login)) > 0 and char_length(login) <= 120),
    role text not null check (length(btrim(role)) > 0 and char_length(role) <= 40),
    kind text not null check (kind in ('revise', 'add')),
    -- {поле: {"old": ..., "new": ...}}: старое и новое значение каждого изменившегося поля.
    changes jsonb not null check (jsonb_typeof(changes) = 'object')
);

create index inspection_edits_inspection_idx on inspection_edits (inspection_id, occurred_at);

comment on table inspection_edits is
    'Журнал правок записей проверки на приёмке (F-134): кто, когда и что изменил — поле, '
    'старое и новое значение, оценка до и после. Пишется той же транзакцией, что и правка. '
    'Роль приложения только дописывает.';

grant insert on inspection_edits to dodo_audit_app;
grant usage on sequence inspection_edits_id_seq to dodo_audit_app;
