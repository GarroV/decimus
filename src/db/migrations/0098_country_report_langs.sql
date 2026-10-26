-- 0098_country_report_langs.sql
--
-- Языки отчёта страны, изменяемые из веба (D640, #1251, вкладка «Администрирование → Страны»).
-- До этого перечень лежал только в `report_langs.json` каталога методики (D415). Строка здесь
-- перекрывает файл для своей страны; нет строки — действует файл (или `ru`, `en`).
-- «Как по умолчанию» в вебе — это удаление строки.
--
-- Какие языки допустимы (языки методики, `TEXT_LANGS`), решает код: база проверяет формат
-- и что перечень не пуст. Порядок массива — порядок, в котором бот предлагает языки.
--
-- КТО ПИШЕТ И КТО ЧИТАЕТ. Читает роль приложения (бот выбирает языки отчёта проверки в
-- пространстве партнёра, поэтому политики по пространству нет: языки страны — не
-- персональные данные). Пишет администратор истории, как договор страны (0088): кто из УК
-- вправе — решает веб (`space.manage`), база видит лишь подпись `updated_by`.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table country_report_langs (
    country text primary key check (country ~ '^[A-Z]{2}$'),
    langs text[] not null
        check (cardinality(langs) between 1 and 8 and array_position(langs, null) is null
               and array_to_string(langs, ',') ~ '^[a-z]{2}(,[a-z]{2})*$'),
    updated_by text not null check (length(btrim(updated_by)) > 0),
    updated_at timestamptz not null default now()
);

comment on table country_report_langs is
    'Языки отчёта страны, перекрывающие report_langs.json (D640). Нет строки — перечень из файла.';

grant select on country_report_langs to dodo_audit_app;
grant select, insert, update, delete on country_report_langs to dodo_audit_admin;
