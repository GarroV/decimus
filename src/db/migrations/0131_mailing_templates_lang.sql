-- 0131_mailing_templates_lang.sql
--
-- Язык шаблона письма больше не пара `ru`/`en` (#541, #1619): список языков отчёта живёт в
-- коде (`src/domain/models.py: REPORT_LANGS`), и третий язык не должен упираться в проверку
-- базы. Проверка `in ('ru', 'en')` из `0104` заменяется формой кода — две латинские буквы,
-- как у `country_report_langs` (`0098`); какие языки допустимы, решает код.
--
-- Рейтинги (`0039`) и план действий (`0092`) этим файлом не трогаются: у них свои колонки
-- `name_ru`/`name_en`.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table mailing_templates drop constraint if exists mailing_templates_lang_check;

alter table mailing_templates
    add constraint mailing_templates_lang_check check (lang ~ '^[a-z]{2}$');
