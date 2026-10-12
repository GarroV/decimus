-- 0056_finish_modes.sql
--
-- D449: «Завершить» в мини-аппе работает в одном из двух режимов, и каждый
-- аудитор выбирает свой в настройках приложения: `summary` — сначала сводка в
-- чат, `report` — сразу отчёт. Выбор живёт за ЧЕЛОВЕКОМ, как язык бота
-- (`0035`), и переживает проверки и перезапуск.
--
-- Ключ — Telegram ID, по той же причине, что в `0035`: в бот входят и люди без
-- учётки веба. Строка одна на человека, выбор перезаписывается; нет строки —
-- действует умолчание `summary` (оно в коде, `db/finish_modes.py`, а не в
-- базе: «не выбирал» и «выбрал сводку» различать незачем).
--
-- Пишет и читает роль приложения — мини-апп ходит ею. Удалять строки не может
-- никто: «забыть выбор» — это выбрать заново.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table finish_modes (
    telegram_id bigint primary key,
    mode text not null check (mode in ('summary', 'report')),
    chosen_at timestamptz not null default now()
);

grant select, insert on finish_modes to dodo_audit_app;
grant update (mode, chosen_at) on finish_modes to dodo_audit_app;

alter table finish_modes enable row level security;
alter table finish_modes force row level security;
create policy finish_modes_access on finish_modes
    for all using (true) with check (true);

comment on table finish_modes is
    'Режим «Завершить» в мини-аппе, выбранный аудитором (D439): summary или report. Одна строка на Telegram ID.';
