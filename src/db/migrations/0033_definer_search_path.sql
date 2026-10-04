-- 0033_definer_search_path.sql
--
-- Функции владельца (`security definer`) — с `pg_temp` ПОСЛЕДНИМ в пути поиска
-- и с полными именами таблиц.
--
-- Почему. У функции владельца путь поиска задаёт сама функция, но временная
-- схема сеанса (`pg_temp`) ищется ПЕРВОЙ, если её не назвать в пути явно. Тогда
-- вызвавший может завести у себя временную таблицу `web_users` или
-- `web_sessions`, и функция с правами владельца прочтёт или перепишет её вместо
-- настоящей. `pg_temp` в конце пути и полные имена `public.<таблица>` закрывают
-- это с двух сторон. Так рекомендует документация Postgres
-- («Writing SECURITY DEFINER Functions Safely»).
--
-- Затронуты все четыре функции владельца в схеме:
-- `log_inspection_move` (`0025`), `inspection_unit_of_space` и
-- `unit_space_frozen` (`0030`, сторожа пространств), `change_own_password`
-- (`0032`). Тела не меняются. Меняются только путь поиска и полные имена.
-- `create or replace` сохраняет триггеры, привязанные к функциям, и выданные
-- права.
--
-- ЧЕГО `change_own_password` НЕ ОБЕСПЕЧИВАЕТ (поправка к заголовку `0032`).
-- Там сказано, что пробитое приложение не сменит пароль человеку, чьей сессии
-- у него нет. Это неверно. Роль приложения читает `web_users.password_hash` и
-- вставляет строки в `web_sessions` (`0014`). Пробитое приложение может само
-- открыть себе сессию любого человека и предъявить функции прочитанный хеш.
-- Функция сужает только ПОВЕРХНОСТЬ: прямой записи хеша у приложения по-прежнему
-- нет, строку выбирает сессия, прежний хеш сверяется. Защиты от пробитого
-- приложения она не даёт. Для такой защиты сверка пароля должна жить в базе, а
-- у приложения нужно отнять чтение хеша. Это отдельная задача, см.
-- `docs/12-web-admin.md`. Отпечаток `0032` заморожен
-- (`tests/test_db_migrations_frozen.py`), поэтому поправка стоит здесь.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create or replace function log_inspection_move() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    причина text := btrim(coalesce(current_setting('decimus.move_reason', true), ''));
    автор text := btrim(coalesce(current_setting('decimus.move_actor', true), ''));
begin
    if причина = '' or автор = '' then
        raise exception 'Перенос проверки % без причины или автора: история переноса обязательна (D195)', old.id
            using errcode = 'check_violation';
    end if;
    if old.retracted_at is not null then
        raise exception 'Отклонённую проверку % перенести нельзя', old.id
            using errcode = 'check_violation';
    end if;
    insert into public.inspection_moves
        (tenant_code, inspection_id, old_date, new_date, old_unit_id, new_unit_id, reason, moved_by)
    values
        (old.tenant_code, old.id, old.inspection_date, new.inspection_date,
         old.unit_id, new.unit_id, причина, автор);
    return new;
end;
$$;

create or replace function inspection_unit_of_space() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    чья text;
    страна text;
begin
    select tenant_code, country into чья, страна from public.units where id = new.unit_id;
    if чья = new.tenant_code and (чья = 'HQ' or exists (
        select 1 from public.space_countries s
         where s.tenant_code = new.tenant_code and s.country = страна
    )) then
        return new;
    end if;
    if чья = 'HQ' and exists (
        select 1 from public.space_countries s
         where s.tenant_code = new.tenant_code and s.country = страна
    ) then
        return new;
    end if;
    raise exception using message =
        'Пиццерия проверки не из справочника страны этого пространства';
end $$;

create or replace function unit_space_frozen() returns trigger
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    if new.tenant_code is distinct from old.tenant_code
       and exists (select 1 from public.inspections i where i.unit_id = old.id) then
        raise exception using message =
            'У пиццерии с проверками пространство не меняется: видимость записанных '
            || 'проверок переехала бы молча';
    end if;
    if new.country is distinct from old.country and (
        (old.country is not null
         and exists (select 1 from public.inspections i where i.unit_id = old.id))
        or exists (select 1 from public.inspections i
                    where i.unit_id = old.id and i.tenant_code <> 'HQ')
    ) then
        raise exception using message =
            'У пиццерии с проверками страна не меняется: видимость записанных '
            || 'проверок переехала бы молча';
    end if;
    return new;
end $$;

create or replace function change_own_password(p_token text, p_old_hash text, p_new_hash text)
    returns boolean
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чей uuid;
begin
    select u.id into чей
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = отпечаток
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       and u.password_hash = p_old_hash;
    if чей is null then
        return false;
    end if;

    update public.web_users set password_hash = p_new_hash where id = чей;

    update public.web_sessions
       set closed_at = now()
     where user_id = чей
       and closed_at is null
       and fingerprint <> отпечаток;
    return true;
end;
$$;

comment on function change_own_password(text, text, text) is
    'Смена СВОЕГО пароля с экрана (#324): строку выбирает живая сессия, чей токен предъявлен; '
    'прежний хеш обязан быть на месте; остальные сессии человека закрываются, своя — нет. '
    'Сужает поверхность (у приложения нет прямой записи хеша), но от пробитого приложения '
    'не защищает: оно читает хеши и открывает сессии само (0033).';
