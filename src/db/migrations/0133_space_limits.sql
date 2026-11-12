-- 0133_space_limits.sql
--
-- D755, D759 п.5 (#1670): настраиваемые лимиты пространства партнёра.
--
-- 1. `space_limits` — по строке на пространство: сколько проверок на пиццерию и какой
--    месячный потолок расхода модели, $. Пустое значение — «без лимита». Нет строки —
--    действует умолчание партнёра (5 проверок, 50 $; `src/domain/space_limits.py`).
--    Пространство УК лимитов не имеет, строка ему ничего не меняет.
--    Читает роль приложения (бот, слив и загрузка сверяют лимит), пишет администратор
--    истории (`_managing`, как заведение пространства): права на экране — главный админ и
--    админ УК, это решает веб, а база не даёт писать роли приложения вовсе.
-- 2. `model_usage.tenant_code` уже есть (0078); проверка потолка считает сумму по нему за
--    месяц на каждый платный вызов, поэтому — индекс по паре «пространство, время».
-- 3. `model_usage_spend` — сводка расхода пространства за период для проверки потолка и
--    экрана. У роли приложения на `model_usage` только `insert` (0078), читать таблицу
--    напрямую она не вправе; функция отдаёт только суммы по моделям одного пространства.
--    Деньги считает приложение по `model_prices.json`, как и экран «Расход модели».
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table space_limits (
    tenant_code text primary key references tenants (code) check (tenant_code <> 'HQ'),
    inspections_per_unit integer check (inspections_per_unit is null or inspections_per_unit >= 1),
    monthly_spend_usd numeric(12, 2)
        check (monthly_spend_usd is null or monthly_spend_usd >= 0),
    updated_by text check (updated_by is null or char_length(updated_by) <= 120),
    updated_at timestamptz not null default now()
);

comment on table space_limits is
    'Лимиты пространства партнёра (D759): проверок на пиццерию и потолок расхода модели в '
    'месяц, $. Пустое значение — без лимита; нет строки — умолчание из кода.';
comment on column space_limits.updated_by is 'Логин того, кто менял, и время — updated_at.';

grant select on space_limits to dodo_audit_app;
grant select, insert, update on space_limits to dodo_audit_admin;

create index model_usage_tenant_time_idx on model_usage (tenant_code, occurred_at);

create function model_usage_spend(p_tenant text, p_from timestamptz)
returns table (model text, input_tokens bigint, output_tokens bigint, audio_seconds numeric)
language sql stable security definer set search_path = pg_catalog, public, pg_temp as $$
    select m.model,
           coalesce(sum(m.input_tokens), 0)::bigint,
           coalesce(sum(m.output_tokens), 0)::bigint,
           coalesce(sum(m.audio_seconds), 0)
      from public.model_usage m
     where m.tenant_code = p_tenant and m.occurred_at >= p_from
     group by m.model
$$;

revoke all on function model_usage_spend(text, timestamptz) from public;
grant execute on function model_usage_spend(text, timestamptz) to dodo_audit_app;
