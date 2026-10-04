-- 0028_login_across_spaces.sql
--
-- Волна 1 пространств (#340, D282): у каждого человека свой логин, уникальный
-- во всей системе, и один адрес админки на все пространства.
--
-- ЧТО БЫЛО. Логин и почта Google были уникальны ВНУТРИ арендатора (0014, 0021),
-- стенд отвечал за один арендатор (`WEB_TENANT`), и опознание искало строку по
-- паре «арендатор стенда + логин». Партнёр на стенде УК войти не мог.
--
-- ЧТО СТАЛО. Опознание ищет по логину (или почте) во всей базе, пространство
-- человека — `tenant_code` его строки.
--
-- ДВОЙНИКИ НЕ РАЗРЕШАЮТСЯ МОЛЧА: накат отказывает и говорит, сколько их и как
-- найти. Логины в отказ не печатаются — он уходит в журнал наката.
--
-- Логин сравнивается БЕЗ УЧЁТА РЕГИСТРА И ПРОБЕЛОВ ПО КРАЯМ: «Director» и
-- «director» — один человек для входа (`authenticate` приводит ввод к нижнему
-- регистру), значит, и двойник. Считаются все строки, отключённые тоже:
-- уникальность держит индекс по всем строкам. Хранится логин только в
-- приведённом виде — это держит ограничение схемы, а не одна дверь кода.
--
-- Раннер оборачивает файл в одну транзакцию сам.

do $$
declare
    двойников bigint;
begin
    select count(*) into двойников
      from (select lower(btrim(login)) from web_users
             group by lower(btrim(login)) having count(*) > 1) d;
    if двойников > 0 then
        raise exception using message =
            'Логины, совпадающие без учёта регистра (в том числе в разных пространствах '
            || 'и у отключённых учёток): ' || двойников::text
            || '. Найти: select lower(btrim(login)) from web_users '
            || 'group by lower(btrim(login)) having count(*) > 1. '
            || 'Переименуйте их, затем повторите накат';
    end if;
    select count(*) into двойников from web_users where login <> lower(btrim(login));
    if двойников > 0 then
        raise exception using message =
            'Логины не в приведённом виде (заглавные буквы или пробелы по краям): '
            || двойников::text
            || '. Найти: select id from web_users where login <> lower(btrim(login)). '
            || 'Приведите их к нижнему регистру, затем повторите накат';
    end if;
    select count(*) into двойников
      from (select email from web_users where email is not null
             group by email having count(*) > 1) d;
    if двойников > 0 then
        raise exception using message =
            'Почта привязана к учёткам нескольких пространств: ' || двойников::text
            || '. Снимите лишние привязки, затем повторите накат';
    end if;
end $$;

create unique index web_users_login_uq on web_users (login);
alter table web_users add constraint web_users_login_normalized
    check (login = lower(btrim(login)));
drop index web_users_tenant_login_idx;

create unique index web_users_email_global_uq on web_users (email) where email is not null;
drop index web_users_email_uq;

comment on column web_users.login is
    'Логин, единый на всю систему (D282): опознание ищет по нему во всей базе, '
    'пространство человека — tenant_code его строки.';
