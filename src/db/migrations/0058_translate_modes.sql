-- 0058_translate_modes.sql
--
-- D443: перевод комментариев на язык отчёта — автоматически или по кнопке, и
-- каждый аудитор выбирает свой в настройках мини-аппа: `button` — переводит
-- сам по кнопке под полем (D394), `auto` — комментарии переводятся при сборке
-- отчёта. Выбор живёт за ЧЕЛОВЕКОМ, как режим «Завершить» (`0056`).
--
-- Ключ — Telegram ID, по той же причине, что в `0035` и `0056`. Строка одна на
-- человека, выбор перезаписывается; нет строки — действует умолчание `button`
-- (оно в коде, `db/translate_modes.py`, а не в базе).
--
-- Пишет и читает роль приложения — мини-апп ходит ею, отчёт читает тем же
-- подключением. Удалять строки не может никто: «забыть выбор» — выбрать заново.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table translate_modes (
    telegram_id bigint primary key,
    mode text not null check (mode in ('button', 'auto')),
    chosen_at timestamptz not null default now()
);

grant select, insert on translate_modes to dodo_audit_app;
grant update (mode, chosen_at) on translate_modes to dodo_audit_app;

alter table translate_modes enable row level security;
alter table translate_modes force row level security;
create policy translate_modes_access on translate_modes
    for all using (true) with check (true);

comment on table translate_modes is
    'Перевод комментариев на язык отчёта, выбранный аудитором (D443): button или auto. Одна строка на Telegram ID.';
