-- 0122_session_acting_tenant.sql
--
-- Переключатель пространств главного админа (D726): `web_sessions.acting_tenant` — в чьё
-- пространство сессия сейчас смотрит. `null` — в своё (обычное состояние). Состояние живёт
-- на сессии, на сервере: умирает вместе с ней (выход, срок, закрытие), в куке, адресе и
-- браузере его нет.
--
-- Выставляет колонку только функция `set_session_acting_tenant`, а не роль приложения:
-- прав на запись в колонку приложению не выдано, и пробитое приложение не подставит
-- чужое пространство обычной сессии. Функция сама сверяет: сессия живая, учётка —
-- главный админ УК, вторая ступень пройдена (или способа нет вовсе), пространство
-- заведено. Какие именно пространства допустимы — решает код (`src/domain/peek.py`).
--
-- Старый заслон закрытия сессий (`0014`) остаётся в силе, но проверка новой строки
-- смягчена: прежняя `with check (closed_at is not null)` пропускала только закрытие, и
-- правка любой другой колонки живой строки отклонялась. Теперь правка допускается, если
-- строка до правки была живой (`using`); воскресить закрытую по-прежнему нельзя — для
-- закрытой `using` ложно, — а какие колонки вправе менять роль приложения, как и раньше
-- говорят её привилегии (`update (closed_at)` и только).
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table web_sessions add column acting_tenant text references tenants (code);

comment on column web_sessions.acting_tenant is
    'Пространство, в которое главный админ УК заглянул переключателем (D726); null — своё. '
    'Пишет только set_session_acting_tenant; читается вместе с сессией на каждом запросе.';

alter policy web_sessions_are_closed_not_reopened on web_sessions
    using (closed_at is null)
    with check (true);

create function set_session_acting_tenant(p_token text, p_tenant text)
    returns boolean
    language plpgsql
    security definer
    set search_path = pg_catalog, public
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чья uuid;
    сессия uuid;
    после_ступени boolean;
begin
    select s.id, u.id, s.second_step_at is not null into сессия, чья, после_ступени
      from web_sessions s
      join web_users u on u.id = s.user_id
     where s.fingerprint = отпечаток
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       and u.role = 'superadmin'
       and u.tenant_code in ('HQ', 'default');
    if сессия is null then
        return false;
    end if;
    -- Вторая ступень: у кого способ входа есть, тот переключается только в сессии после неё.
    if not после_ступени and (
        exists (select 1 from web_passkeys p where p.user_id = чья)
        or exists (select 1 from web_totp t where t.user_id = чья and t.confirmed_at is not null)
    ) then
        return false;
    end if;
    if p_tenant is not null and not exists (select 1 from tenants t where t.code = p_tenant) then
        return false;
    end if;
    update web_sessions set acting_tenant = p_tenant where id = сессия;
    return true;
end;
$$;

comment on function set_session_acting_tenant(text, text) is
    'Переключатель пространств (D726): выставляет или снимает (p_tenant = null) пространство '
    'просмотра у ЖИВОЙ сессии главного админа УК после второй ступени. false — отказано.';

revoke all on function set_session_acting_tenant(text, text) from public;
grant execute on function set_session_acting_tenant(text, text) to dodo_audit_app;
