-- 0077_web_country_filter.sql
--
-- «Страны» (D536): постоянный отбор стран у человека — «мне нужен только
-- Кавказ». Хранится в профиле учётки и поэтому действует на всех устройствах и
-- в следующих сессиях, как язык сайта (`web_lang`, `0061`).
--
-- 1. `web_users.country_filter` — коды стран, которые человек оставил на экране
--    «Страны»; `null` — отбора нет, видны все страны его охвата. Кластер
--    (Кавказ, CEE и так далее) в базе не хранится: выбор кластера на экране —
--    это выбор его стран, и состав кластера читается из справочника рейтингов.
--    Отбор только СУЖАЕТ охват: страны вне охвата человека он не открывает,
--    охват по-прежнему решает дверь (`reach.py`).
-- 2. `set_own_country_filter` — записать отбор своей учётки. Строку выбирает
--    сама функция по ЖИВОЙ СЕССИИ, чей ТОКЕН ей предъявлен (приём `0061`):
--    роли приложения прямая запись в `web_users` по-прежнему не выдана.
--    Пустой массив и `null` снимают отбор.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table web_users add column country_filter text[]
    check (
        country_filter is null
        or (cardinality(country_filter) between 1 and 300
            and array_to_string(country_filter, ',') ~ '^[A-Z]{2}(,[A-Z]{2})*$')
    );

comment on column web_users.country_filter is
    'Постоянный отбор стран экрана «Страны» (D536): коды ISO; null — все страны охвата. '
    'Только сужает охват, не расширяет. Пишет только set_own_country_filter (0077).';

create function set_own_country_filter(p_token text, p_countries text[])
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
       and u.disabled_at is null;
    if чей is null then
        return false;
    end if;
    update public.web_users
       set country_filter = case
               when p_countries is null or cardinality(p_countries) = 0 then null
               else p_countries
           end
     where id = чей;
    return true;
end;
$$;

revoke all on function set_own_country_filter(text, text[]) from public;
grant execute on function set_own_country_filter(text, text[]) to dodo_audit_app;
