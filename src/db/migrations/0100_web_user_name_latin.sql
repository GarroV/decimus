-- 0100_web_user_name_latin.sql
--
-- Имя проверяющего латиницей в карточке человека (D644). Имя и фамилия из
-- карточки уходят партнёру на штамп кадра и в отчёт; партнёры разные, и
-- записывается оно латиницей. `web_users.display_name_latin` — необязательное
-- поле, которое правит админ в карточке «Людей»: заполнено — берётся оно, пусто —
-- имя из `display_name` переводится автоматически (ICAO 9303, `src/domain/auditor_name.py`).
-- Внутри компании («Люди») имя показывается как записано.
--
-- Правит роль `dodo_audit_admin` (как почту, `0021`): приложение таблицу только
-- читает, и грант на запись — колоночный, чтобы вместе с полем не раздать лишнего.
--
-- ОТКАТ по смыслу: `alter table web_users drop column display_name_latin;` —
-- теряется только введённое вручную написание, автоперевод остаётся.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table web_users
    add column display_name_latin text
        check (display_name_latin is null or char_length(display_name_latin) between 1 and 120);

comment on column web_users.display_name_latin is
    'Имя и фамилия латиницей для отчёта и штампа (D644); NULL — переводится '
    'автоматически из display_name.';

grant select (display_name_latin), update (display_name_latin) on web_users to dodo_audit_admin;
