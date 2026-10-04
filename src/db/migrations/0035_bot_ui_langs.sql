-- 0035_bot_ui_langs.sql
--
-- D303 (#411): аудитор сам выбирает язык бота, и выбор живёт за ЧЕЛОВЕКОМ —
-- переживает проверки и перезапуск бота.
--
-- Ключ — Telegram ID, а не учётка веба. В бот входят и люди без учётки
-- (совместимость до D286: `ALLOWED_TELEGRAM_IDS`, связки `roster.json`), и
-- выбор нужен им так же. Telegram ID — это и есть человек в боте; привязка к
-- учётке (`0031`) может смениться, а язык от этого меняться не должен.
--
-- Строка одна на человека: выбор перезаписывается. Истории выборов не ведётся —
-- вопроса «на каком языке говорил бот в прошлый вторник» никто не задаёт.
--
-- Список языков в ограничении не перечислен намеренно: третий язык добавляется
-- словарём бота (`src/bot/texts.py: UI_LANGS`), и миграция ради него была бы
-- лишней. Ограничение держит только форму кода; заведён ли язык, сверяет бот
-- при записи и при чтении.
--
-- Пишет и читает роль приложения — бот ходит ею (как в `0031`). Функций
-- владельца здесь нет, поэтому пути поиска (`0033`) нечего задавать. Удалять
-- строки не может никто: «забыть выбор» — это выбрать заново.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table bot_ui_langs (
    telegram_id bigint primary key,
    ui_lang text not null check (ui_lang ~ '^[a-z]{2,3}$'),
    chosen_at timestamptz not null default now()
);

grant select, insert on bot_ui_langs to dodo_audit_app;
grant update (ui_lang, chosen_at) on bot_ui_langs to dodo_audit_app;

alter table bot_ui_langs enable row level security;
alter table bot_ui_langs force row level security;
create policy bot_ui_langs_access on bot_ui_langs
    for all using (true) with check (true);

comment on table bot_ui_langs is
    'Язык интерфейса бота, выбранный человеком (D303). Одна строка на Telegram ID.';
