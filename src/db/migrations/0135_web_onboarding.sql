-- 0135_web_onboarding.sql
--
-- Онбординг партнёра (D756, D759 п.6, #1668): две личные пометки учётки.
--
-- 1. `web_users.tour_seen_at` — когда человек прошёл (или закрыл) тур по интерфейсу.
--    `null` — не видел: партнёру тур откроется сам при первом входе. Повторный запуск
--    из меню учётки ничего не пишет.
-- 2. `web_users.start_hidden_at` — когда человек скрыл карточку «Начало работы» на
--    «Главной». `null` — не скрывал. Карточка исчезает и сама, когда всё сделано;
--    эта пометка — для тех, кому она не нужна раньше.
-- 3. `set_own_onboarding` — записать пометки СВОЕЙ учётки. Строку выбирает сама функция
--    по ЖИВОЙ СЕССИИ, чей ТОКЕН ей предъявлен (приём `0061`, `0077`): роли приложения
--    прямая запись в `web_users` по-прежнему не выдана. `p_tour = true` ставит метку тура
--    один раз (повтор её не двигает); `p_start` — `hide` ставит метку скрытия, `show`
--    снимает, `null` не трогает.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table web_users add column tour_seen_at timestamptz;
alter table web_users add column start_hidden_at timestamptz;

comment on column web_users.tour_seen_at is
    'Когда человек прошёл или закрыл тур по интерфейсу (D756); null — не видел. '
    'Пишет только set_own_onboarding (0135).';
comment on column web_users.start_hidden_at is
    'Когда человек скрыл карточку «Начало работы» (D756); null — не скрывал. '
    'Пишет только set_own_onboarding (0135).';

create function set_own_onboarding(p_token text, p_tour boolean, p_start text)
    returns boolean
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чей uuid;
begin
    if p_start is not null and p_start not in ('hide', 'show') then
        raise exception 'start: hide или show' using errcode = '22023';
    end if;
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
       set tour_seen_at = case
               when coalesce(p_tour, false) then coalesce(tour_seen_at, now())
               else tour_seen_at
           end,
           start_hidden_at = case p_start
               when 'hide' then now()
               when 'show' then null
               else start_hidden_at
           end
     where id = чей;
    return true;
end;
$$;

revoke all on function set_own_onboarding(text, boolean, text) from public;
grant execute on function set_own_onboarding(text, boolean, text) to dodo_audit_app;
