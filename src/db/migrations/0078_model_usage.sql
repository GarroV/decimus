-- 0078_model_usage.sql
--
-- Расход модели (D537): одна строка на каждый вызов провайдера — когда, какого вида,
-- какая модель, сколько токенов на входе и выходе (или секунд звука), кто спросил, в
-- какой проверке и пространстве, удался ли вызов. Нужна экрану «Расход модели» в
-- «Администрировании»: сколько потрачено, по дням, видам, людям и проверкам.
--
-- 1. Пишет роль приложения, и только ДОПИСЫВАЕТ (`insert`): ни `select`, ни `update`, ни
--    `delete`. Тот же приём, что у журналов (`0067`): задним числом не поправить, прочитать
--    таблицу напрямую нельзя.
-- 2. Читает функция `model_usage_read`: зритель определяется по токену живой сессии, и
--    видят расход только главный админ и админ УК. Всем остальным — пусто.
-- 3. `user_id` — учётка человека (веб; у бота — учётка, к которой привязан Telegram),
--    `telegram_id` — Telegram ID, когда вызов пришёл из бота или мини-аппа. Внешнего ключа
--    нет намеренно: запись расхода не должна отказать из-за строки учётки, а вызов
--    провайдера уже оплачен. `inspection_ref` — номер проверки в базе (веб) либо личность
--    проверки чата `run_id` (бот и мини-апп: в базе проверки до сдачи ещё нет).
-- 4. Цены здесь НЕ хранятся: стоимость — оценка по `src/recognize/model_prices.json` на
--    момент просмотра, чтобы поправка цены пересчитала и прошлое.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table model_usage (
    id bigint generated always as identity primary key,
    occurred_at timestamptz not null default now(),
    -- Стабильный код вида вызова (`src/domain/model_usage.py`).
    kind text not null
        check (kind in ('recognize', 'suggest', 'revise', 'merge', 'translate', 'transcribe', 'other')),
    model text not null check (char_length(model) <= 120),
    -- Токены, как их отдал провайдер; null — провайдер не сообщил.
    input_tokens integer check (input_tokens is null or input_tokens >= 0),
    output_tokens integer check (output_tokens is null or output_tokens >= 0),
    -- Секунды звука, когда расшифровка отдала длительность, а не токены.
    audio_seconds numeric check (audio_seconds is null or audio_seconds >= 0),
    ok boolean not null,
    user_id uuid,
    telegram_id bigint,
    tenant_code text,
    inspection_ref text check (inspection_ref is null or char_length(inspection_ref) <= 80)
);

create index model_usage_time_idx on model_usage (occurred_at desc);

comment on table model_usage is
    'Расход модели (D537): одна строка на вызов провайдера. Роль приложения только '
    'дописывает; читает функция model_usage_read (главный админ и админ УК).';

grant insert on model_usage to dodo_audit_app;
grant usage on sequence model_usage_id_seq to dodo_audit_app;

-- Расход глазами зрителя: суммы по четырём срезам одним ответом. Срез `day` — день (UTC),
-- `kind` — вид вызова, `person` — человек, `inspection` — двадцать проверок с наибольшим
-- расходом токенов. Деньги считает приложение: у функции цен нет.
create function model_usage_read(p_token text, p_from timestamptz, p_to timestamptz)
returns table (
    dim text, key text, label text, model text, calls bigint, failed bigint,
    input_tokens bigint, output_tokens bigint, audio_seconds numeric
)
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    роль text;
    пространство text;
begin
    select u.role, u.tenant_code into роль, пространство
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = encode(sha256(convert_to(p_token, 'UTF8')), 'hex')
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null;
    if роль is null or not (роль = 'superadmin' or (роль = 'admin' and пространство = 'HQ')) then
        return;
    end if;
    return query
    with base as (
        select m.*, coalesce(m.user_id::text, 'tg:' || m.telegram_id::text, '') as who
          from public.model_usage m
         where (p_from is null or m.occurred_at >= p_from)
           and (p_to is null or m.occurred_at < p_to)
    ),
    top_inspections as (
        select b.inspection_ref
          from base b
         where b.inspection_ref is not null
         group by b.inspection_ref
         order by sum(coalesce(b.input_tokens, 0) + coalesce(b.output_tokens, 0)) desc,
                  b.inspection_ref
         limit 20
    )
    select 'day'::text, to_char(b.occurred_at at time zone 'UTC', 'YYYY-MM-DD'), ''::text, b.model,
           count(*), count(*) filter (where not b.ok),
           coalesce(sum(b.input_tokens), 0)::bigint, coalesce(sum(b.output_tokens), 0)::bigint,
           coalesce(sum(b.audio_seconds), 0)
      from base b group by 2, 4
    union all
    select 'kind', b.kind, '', b.model,
           count(*), count(*) filter (where not b.ok),
           coalesce(sum(b.input_tokens), 0)::bigint, coalesce(sum(b.output_tokens), 0)::bigint,
           coalesce(sum(b.audio_seconds), 0)
      from base b group by 2, 4
    union all
    select 'person', b.who, coalesce(u.login, ''), b.model,
           count(*), count(*) filter (where not b.ok),
           coalesce(sum(b.input_tokens), 0)::bigint, coalesce(sum(b.output_tokens), 0)::bigint,
           coalesce(sum(b.audio_seconds), 0)
      from base b
      left join public.web_users u on u.id = b.user_id
     group by b.who, u.login, b.model
    union all
    select 'inspection', b.inspection_ref, '', b.model,
           count(*), count(*) filter (where not b.ok),
           coalesce(sum(b.input_tokens), 0)::bigint, coalesce(sum(b.output_tokens), 0)::bigint,
           coalesce(sum(b.audio_seconds), 0)
      from base b
      join top_inspections t on t.inspection_ref = b.inspection_ref
     group by b.inspection_ref, b.model;
end $$;

revoke all on function model_usage_read(text, timestamptz, timestamptz) from public;
grant execute on function model_usage_read(text, timestamptz, timestamptz) to dodo_audit_app;
