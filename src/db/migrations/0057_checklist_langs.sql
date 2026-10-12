-- 0057_checklist_langs.sql
--
-- D451: язык чек-листа, выбранный аудитором на старте проверки в мини-аппе,
-- запоминается за ЧЕЛОВЕКОМ — на следующем старте экран подставляет его же.
-- Хранить его больше было негде: язык речи живёт только внутри проверки
-- (`inspections.speech_lang`), а проверка сносится и заменяется.
--
-- Ключ — Telegram ID, по той же причине, что в `0035` и `0056`. Строка одна на
-- человека, выбор перезаписывается; нет строки — умолчание берёт код (язык
-- интерфейса человека, `web/walk_start.py`). Язык не сверяется с перечнем в
-- базе: перечень языков чек-листа растёт словарём в коде, а не миграцией, и
-- лишний код отсекает чтение.
--
-- Пишет и читает роль приложения — мини-апп ходит ею. Удалять строки не может
-- никто: «забыть выбор» — это выбрать заново.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table checklist_langs (
    telegram_id bigint primary key,
    lang text not null check (lang ~ '^[a-z]{2,8}$'),
    chosen_at timestamptz not null default now()
);

grant select, insert on checklist_langs to dodo_audit_app;
grant update (lang, chosen_at) on checklist_langs to dodo_audit_app;

alter table checklist_langs enable row level security;
alter table checklist_langs force row level security;
create policy checklist_langs_access on checklist_langs
    for all using (true) with check (true);

comment on table checklist_langs is
    'Язык чек-листа, выбранный аудитором на старте проверки в мини-аппе (D440). Одна строка на Telegram ID.';
