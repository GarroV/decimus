-- 0123_session_peeks_table.sql
--
-- Переключатель пространств (D726): состояние «в чьё пространство смотрит сессия» уходит из
-- колонки `web_sessions.acting_tenant` (`0122`) в отдельную таблицу `web_session_peeks`, а
-- заслон закрытия сессий возвращается к строгому виду из `0014`.
--
-- Зачем. `0122` смягчил `with check` политики `web_sessions_are_closed_not_reopened` до
-- `true`, чтобы функция переключателя могла писать колонку на живой сессии. Владелец: правило
-- закрытия не ослабляем. Теперь функция пишет НЕ в `web_sessions`, а в свою таблицу, и
-- политика снова пропускает ровно один переход: живая строка → закрытая.
--
-- Таблица. Одна строка на сессию (`session_id` — первичный ключ), уходит вместе с сессией
-- (`on delete cascade`). Пишет только `set_session_acting_tenant` (security definer): роли
-- приложения выданы лишь `select` — вставить, подправить или снять строку напрямую она не
-- может, поэтому пробитое приложение не подставит чужое пространство. «Действует ли» строка,
-- решает не она: опознание сессии берёт её только для живой сессии (закрытая и просроченная
-- не опознаются вовсе), а допустимость пространства и роли — заслон входа (`domain.peek`).
--
-- RLS включён, и политика разрешающая, как у `web_sessions` в `0014`: `force` держит правила
-- при любой роли, включая владельца схемы, а без единой политики при включённом RLS не
-- проходит ничего. Привилегии (`select` и только) — вся граница; политика ничего не
-- добавляет к ним и существует ради `force`.
--
-- Админской роли (`dodo_audit_admin`) таблица не нужна: она читает сессии лишь затем, чтобы
-- закрыть их (`0022`), а переключатель к этому не относится.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table web_session_peeks (
    session_id uuid primary key references web_sessions (id) on delete cascade,
    tenant_code text not null references tenants (code),
    set_at timestamptz not null default now()
);

comment on table web_session_peeks is
    'Переключатель пространств главного админа УК (D726): в чьё пространство смотрит сессия. '
    'Нет строки — смотрит в своё. Пишет только set_session_acting_tenant; читается вместе с сессией.';

alter table web_session_peeks enable row level security;
alter table web_session_peeks force row level security;
create policy web_session_peeks_access on web_session_peeks
    for all using (true) with check (true);

grant select on web_session_peeks to dodo_audit_app;

-- Живые сессии с включённым просмотром переезжают как есть.
insert into web_session_peeks (session_id, tenant_code)
select id, acting_tenant
  from web_sessions
 where acting_tenant is not null
   and closed_at is null
   and expires_at > now();

-- Строгий заслон закрытия возвращается (`0014`): живая → закрытая и больше ничего.
alter policy web_sessions_are_closed_not_reopened on web_sessions
    using (closed_at is null)
    with check (closed_at is not null);

alter table web_sessions drop column acting_tenant;

create or replace function set_session_acting_tenant(p_token text, p_tenant text)
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
    if p_tenant is null then
        delete from web_session_peeks where session_id = сессия;
    else
        insert into web_session_peeks (session_id, tenant_code)
        values (сессия, p_tenant)
        on conflict (session_id) do update set tenant_code = excluded.tenant_code, set_at = now();
    end if;
    return true;
end;
$$;

comment on function set_session_acting_tenant(text, text) is
    'Переключатель пространств (D726): выставляет или снимает (p_tenant = null) пространство '
    'просмотра у ЖИВОЙ сессии главного админа УК после второй ступени. false — отказано.';

revoke all on function set_session_acting_tenant(text, text) from public;
grant execute on function set_session_acting_tenant(text, text) to dodo_audit_app;
