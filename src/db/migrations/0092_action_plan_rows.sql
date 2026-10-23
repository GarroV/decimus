-- 0092_action_plan_rows.sql
--
-- Электронный план исправлений, шаг 2 эпика #1168 (спека 2026-10-22-electronic-action-plan-design;
-- D612, D613, D617, D618, D621). План перестаёт быть только файлом: по каждому нарушению
-- проверки заводится СТРОКА (что сделаем, кто отвечает, к какому сроку), партнёр
-- заполняет её на экране, УК принимает план и подтверждает выполнение по строкам.
--
-- ЖИЗНЕННЫЙ ЦИКЛ ЭЛЕКТРОННОГО ПЛАНА
--
--   requested ──(партнёр: «на согласование»)──► on_review ──(УК принял)──► in_work ──► closed
--       ▲                                           │                            (все строки
--       └─────────(УК вернул, комментарий)──────────┘                             подтверждены)
--
--   Строка:  filling ──(взяли в работу)──► in_work ──(сделано)──► done ──(УК)──► confirmed
--                                                       ▲                    └──► returned
--                                                       └──────(сделано снова)──────┘
--
-- Файловые планы (`accepted` — старый путь «файл → приём») остаются как есть: признак
-- `electronic` стоит только у запросов, по которым заведены строки. Переходы файловых
-- запросов этой миграцией не меняются ни на букву.
--
-- КТО ЧТО ПИШЕТ — ДЕРЖИТ БАЗА, КАК В 0036.
--
--   Партнёр (роль приложения):  текст строки (мера, ответственный, причина), свой срок —
--       только РАНЬШЕ положенного, и только пока план в заполнении (`requested`); перевод
--       плана на согласование (все строки с мерой и ответственным); по строке — «взяли в
--       работу» и «сделано», когда план принят (`in_work`). Только строки пространства, чья
--       страна у партнёра (политика 0062 + проверка страны в триггере). Вердикт — нет.
--   УК (администратор истории):  строки заводит, план принимает или возвращает (комментарий
--       обязателен), строку подтверждает или возвращает (причина обязательна), план закрывает
--       (только когда подтверждены все строки), начало отсчёта правит. За партнёра заполнить
--       мера/ответственный/причину не может: колонок для этого ей не выдано.
--
-- СРОК СТРОКИ. `days` — дни из методики на момент заведения (пункт, не больше потолка
-- класса; D3 — ноль, считает `src/domain/plan_due.py`, числа в базе не живут). Положенный
-- срок — `count_from + days`; `own_due` — более ранний срок партнёра; `extended_due` —
-- срок, перенесённый с согласием (шаг позже, колонка заложена). Действующий `due_on`
-- считает триггер по одной формуле `plan_row_due`; записать его руками нельзя. Сдвиг
-- `count_from` пересчитывает все строки, кроме перенесённых. «Просрочено» не хранится.
--
-- ПОДПИСЬ. Каждый переход, как и правка срока в 0036, идёт с подписью транзакции
-- `decimus.plan_actor`: без неё триггер отказывает, а история (`action_plan_events`,
-- пишут только триггеры) получает автора.
--
-- РЕВИЗИЯ. `action_plan_requests.revision` растёт на каждую правку содержимого строк: по
-- ней файл «туда и обратно» (следующий шаг) заметит, что план на экране поменяли.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

-- ── Запрос плана ────────────────────────────────────────────────────────────

alter table action_plan_requests drop constraint if exists action_plan_requests_status_check;
alter table action_plan_requests
    add constraint action_plan_requests_status_check
    check (status in ('requested', 'on_review', 'accepted', 'in_work', 'closed'));

alter table action_plan_requests add column count_from date;
alter table action_plan_requests add column revision integer not null default 1;
alter table action_plan_requests add column electronic boolean not null default false;
alter table action_plan_requests add column review_comment text;

-- Начало отсчёта у уже заведённых — дата запроса (D613: по умолчанию дата создания).
-- Принятые планы триггером не правятся, поэтому на время заполнения он выключен.
alter table action_plan_requests disable trigger action_plan_requests_guarded;
update action_plan_requests set count_from = (requested_at at time zone 'UTC')::date;
alter table action_plan_requests enable trigger action_plan_requests_guarded;

alter table action_plan_requests alter column count_from set not null;
alter table action_plan_requests alter column count_from set default ((now() at time zone 'UTC')::date);

-- Очередь УК (`action_plans._OPEN_SQL`) читает открытые: закрытые копятся, как принятые.
-- Условие индекса — литерал того же вида, что в запросе, иначе планировщик его не узнает.
drop index if exists action_plan_requests_open_idx;
create index action_plan_requests_open_idx on action_plan_requests (due_on, requested_at)
    where status <> 'accepted' and status <> 'closed';

comment on column action_plan_requests.count_from is
    'Начало отсчёта срока (D613): по умолчанию дата создания, УК может назвать другую. Срок ответа планом = count_from + plan_due_days, срок строки = count_from + её дни.';
comment on column action_plan_requests.revision is
    'Ревизия плана: растёт на каждую правку содержимого строк. По ней файл «туда и обратно» замечает, что план на экране поменяли.';
comment on column action_plan_requests.electronic is
    'У запроса заведены строки (электронный план). Ложь — файловый план старого пути, переходы по 0036.';
comment on column action_plan_requests.review_comment is
    'Комментарий последнего возврата электронного плана партнёру.';

-- ── Строки плана ────────────────────────────────────────────────────────────

create function plan_row_due(начало date, дни integer, свой date, перенос date) returns date
    language sql immutable
    set search_path = pg_catalog
as $$
    select case
        when перенос is not null then перенос
        when свой is null then начало + дни
        else least(свой, начало + дни)
    end
$$;

comment on function plan_row_due(date, integer, date, date) is
    'Действующий срок строки плана: перенос с согласием, иначе более ранний из срока партнёра и положенного (начало + дни). Зеркало `src/domain/plan_due.py: effective_row_due`.';

create table action_plan_rows (
    id uuid primary key default gen_random_uuid(),
    request_id uuid not null references action_plan_requests (id),
    finding_id uuid not null references findings (id),
    -- Порядок показа: тяжёлые сверху, внутри класса — как в проверке.
    position integer not null check (position > 0),
    -- Снимок на момент заведения: код пункта, класс, зона и формулировки по методике
    -- издания проверки. Связь — кодом (принцип 5), формулировки — для показа.
    item_code text not null check (length(btrim(item_code)) > 0),
    level text not null check (level ~ '^D[0-9]+$'),
    zone text not null check (length(btrim(zone)) > 0),
    title_ru text,
    title_en text,
    -- Дни из методики на момент заведения (потолок класса уже учтён).
    days integer not null check (days >= 0),
    measure text check (length(measure) <= 2000),
    responsible text check (length(responsible) <= 500),
    reason text check (length(reason) <= 2000),
    own_due date,
    extended_due date,
    due_on date not null,
    status text not null default 'filling'
        check (status in ('filling', 'in_work', 'done', 'confirmed', 'returned')),
    return_reason text check (length(return_reason) <= 2000),
    updated_at timestamptz not null default now(),
    unique (request_id, finding_id),
    unique (request_id, position)
);

create index action_plan_rows_request_idx on action_plan_rows (request_id, position);

comment on table action_plan_rows is
    'Строки электронного плана исправлений (D612): по строке на нарушение проверки. Мера, ответственный, причина, срок — заполняет партнёр; подтверждает УК. Права и переходы — триггеры 0092.';
comment on column action_plan_rows.days is
    'Дни на устранение из методики на момент заведения (пункт, не больше потолка класса; D3 — ноль). Считает домен, в базе чисел методики нет.';
comment on column action_plan_rows.own_due is
    'Срок, который партнёр поставил себе сам: только раньше положенного.';
comment on column action_plan_rows.extended_due is
    'Срок, перенесённый с согласием УК (D621): не двигается вместе с началом отсчёта. Колонка заложена, перенос — следующий шаг.';
comment on column action_plan_rows.due_on is
    'Действующий срок: считает триггер по plan_row_due, руками не пишется. Просрочку считает чтение.';

alter table action_plan_events add column row_id uuid references action_plan_rows (id);

alter table action_plan_events drop constraint if exists action_plan_events_action_check;
alter table action_plan_events
    add constraint action_plan_events_action_check
    check (action in (
        'requested', 'due_changed', 'uploaded', 'accepted', 'returned',
        'submitted', 'closed', 'count_from_changed',
        'row_started', 'row_done', 'row_confirmed', 'row_returned'
    ));

comment on column action_plan_events.row_id is
    'Строка плана, о которой событие; пусто — событие плана целиком.';

-- ── Переходы запроса (замена 0036: файловая ветка без изменений) ───────────

create or replace function guard_action_plan_request() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    последняя uuid;
    вердикт text;
    автор text;
    чья text;
    стадия text;
    отклонена timestamptz;
    страна text;
    всего integer;
    не_заполнено integer;
    не_подтверждено integer;
begin
    if tg_op = 'INSERT' then
        if new.status <> 'requested' then
            raise exception 'запрос экшн-плана заводится только запрошенным, а не %', new.status
                using errcode = 'insufficient_privilege';
        end if;
        select i.tenant_code, i.status, i.retracted_at, u.country
          into чья, стадия, отклонена, страна
        from public.inspections i
        join public.units u on u.id = i.unit_id
        where i.id = new.inspection_id;
        if чья is distinct from 'HQ' then
            raise exception 'экшн-план запрашивают по проверке УК, а проверка % не её', new.inspection_id
                using errcode = 'check_violation';
        end if;
        if стадия is distinct from 'finalized' or отклонена is not null then
            raise exception 'экшн-план запрашивают по принятой и не отклонённой проверке'
                using errcode = 'check_violation';
        end if;
        if страна is null then
            raise exception 'у точки проверки % нет страны — запрос некому показать', new.inspection_id
                using errcode = 'check_violation';
        end if;
        if new.revision <> 1 or new.review_comment is not null then
            raise exception 'новый запрос заводится с первой ревизией и без комментария возврата'
                using errcode = 'check_violation';
        end if;
        new.due_set_by := new.requested_by;
        return new;
    end if;

    if old.status in ('accepted', 'closed') then
        raise exception 'принятый экшн-план % не меняется', old.id
            using errcode = 'check_violation';
    end if;
    if new.electronic is distinct from old.electronic then
        if old.electronic or not new.electronic
           or not pg_has_role(current_user, 'dodo_audit_admin', 'member')
           or exists (select 1 from public.action_plan_files f where f.request_id = old.id) then
            raise exception 'запрос % электронным делает только УК и только запрос без файла', old.id
                using errcode = 'check_violation';
        end if;
    end if;
    if new.count_from is distinct from old.count_from then
        if not pg_has_role(current_user, 'dodo_audit_admin', 'member') then
            raise exception 'начало отсчёта срока правит только УК' using errcode = 'insufficient_privilege';
        end if;
        if btrim(coalesce(current_setting('decimus.plan_actor', true), '')) = '' then
            raise exception 'начало отсчёта запроса % правят с подписью (decimus.plan_actor)', old.id
                using errcode = 'check_violation';
        end if;
    end if;
    if new.due_on is not distinct from old.due_on then
        if new.due_set_by is distinct from old.due_set_by then
            raise exception 'кто назначил срок, не меняется без правки срока'
                using errcode = 'check_violation';
        end if;
    else
        автор := btrim(coalesce(current_setting('decimus.plan_actor', true), ''));
        if автор = '' then
            raise exception 'срок запроса % правят с подписью (decimus.plan_actor)', old.id
                using errcode = 'check_violation';
        end if;
        new.due_set_by := автор;
    end if;
    if new.status = old.status then
        return new;
    end if;

    -- ── Электронный план ────────────────────────────────────────────────────
    if old.electronic then
        if btrim(coalesce(current_setting('decimus.plan_actor', true), '')) = '' then
            raise exception 'переход запроса % идёт с подписью (decimus.plan_actor)', old.id
                using errcode = 'check_violation';
        end if;
        if old.status = 'requested' and new.status = 'on_review' then
            -- На согласование отправляет партнёр страны, а не УК за него.
            if pg_has_role(current_user, 'dodo_audit_admin', 'member') then
                raise exception 'на согласование план % отправляет партнёр, а не УК', old.id
                    using errcode = 'insufficient_privilege';
            end if;
            select u.country into страна
            from public.inspections i
            join public.units u on u.id = i.unit_id
            where i.id = old.inspection_id;
            perform public.decimus_plan_partner_of(страна);
            select count(*), count(*) filter (
                       where btrim(coalesce(r.measure, '')) = '' or btrim(coalesce(r.responsible, '')) = ''
                   )
              into всего, не_заполнено
            from public.action_plan_rows r
            where r.request_id = old.id;
            if всего = 0 or не_заполнено > 0 then
                raise exception 'на согласование план % уходит, когда у каждой строки есть мера и ответственный', old.id
                    using errcode = 'check_violation';
            end if;
            return new;
        end if;
        if not pg_has_role(current_user, 'dodo_audit_admin', 'member') then
            raise exception 'принять, вернуть и закрыть экшн-план % может только УК', old.id
                using errcode = 'insufficient_privilege';
        end if;
        if old.status = 'on_review' and new.status = 'in_work' then
            return new;
        end if;
        if old.status = 'on_review' and new.status = 'requested' then
            if btrim(coalesce(new.review_comment, '')) = '' then
                raise exception 'вернуть план % можно только с комментарием', old.id
                    using errcode = 'check_violation';
            end if;
            return new;
        end if;
        if old.status = 'in_work' and new.status = 'closed' then
            select count(*) filter (where r.status <> 'confirmed')
              into не_подтверждено
            from public.action_plan_rows r
            where r.request_id = old.id;
            if не_подтверждено > 0 or not exists (
                select 1 from public.action_plan_rows r where r.request_id = old.id
            ) then
                raise exception 'план % закрывается, когда подтверждены все строки', old.id
                    using errcode = 'check_violation';
            end if;
            return new;
        end if;
        raise exception 'переход электронного плана % из % в % не предусмотрен', old.id, old.status, new.status
            using errcode = 'check_violation';
    end if;

    -- ── Файловый план (0036) ────────────────────────────────────────────────
    select f.id into последняя
    from public.action_plan_files f
    where f.request_id = old.id
    order by f.version desc
    limit 1;
    select r.verdict into вердикт from public.action_plan_reviews r where r.file_id = последняя;

    if old.status = 'requested' and new.status = 'on_review' then
        if последняя is null or вердикт is not null then
            raise exception 'на приёмку запрос % уходит только с новой версией файла', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    if old.status = 'on_review' and new.status in ('accepted', 'requested') then
        if not pg_has_role(current_user, 'dodo_audit_admin', 'member') then
            raise exception 'принять или вернуть экшн-план % может только УК', old.id
                using errcode = 'insufficient_privilege';
        end if;
        if вердикт is distinct from (case new.status when 'accepted' then 'accepted' else 'returned' end) then
            raise exception 'у последней версии запроса % нет вердикта под этот переход', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    raise exception 'переход запроса % из % в % не предусмотрен', old.id, old.status, new.status
        using errcode = 'check_violation';
end;
$$;


-- ── Строки: что и кто может ────────────────────────────────────────────────

-- Правит ли пространство обращения строки этой страны: партнёр страны (D284). УК
-- строки партнёра не пишет, служебная работа (`*`) — как везде (0062).
create function decimus_plan_partner_of(страна text) returns void
    language plpgsql stable
    set search_path = pg_catalog, public
as $$
declare
    пространство text := btrim(coalesce(current_setting('decimus.space', true), ''));
begin
    if пространство = '*' then
        return;
    end if;
    if пространство = '' then
        raise exception 'decimus.space is not set: the request did not say which space it acts for'
            using errcode = 'insufficient_privilege';
    end if;
    if пространство = 'HQ' or not exists (
        select 1 from space_countries s
         where s.tenant_code = пространство and s.country = страна
    ) then
        raise exception 'строки плана правит партнёр страны %, а не пространство %', страна, пространство
            using errcode = 'insufficient_privilege';
    end if;
end
$$;

create function guard_action_plan_row() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    начало date;
    стадия text;
    страна text;
    это_ук boolean := pg_has_role(current_user, 'dodo_audit_admin', 'member');
    автор text := btrim(coalesce(current_setting('decimus.plan_actor', true), ''));
    правится_текст boolean;
    предел date;
begin
    select r.count_from, r.status, u.country
      into начало, стадия, страна
    from public.action_plan_requests r
    join public.inspections i on i.id = r.inspection_id
    join public.units u on u.id = i.unit_id
    where r.id = new.request_id;
    if начало is null then
        raise exception 'у строки плана нет запроса %', new.request_id using errcode = 'check_violation';
    end if;

    if tg_op = 'INSERT' then
        if not это_ук then
            raise exception 'строки плана заводит только УК' using errcode = 'insufficient_privilege';
        end if;
        if стадия <> 'requested' then
            raise exception 'строки заводят плану в заполнении (сейчас %)', стадия
                using errcode = 'check_violation';
        end if;
        if new.status <> 'filling' or new.measure is not null or new.responsible is not null
           or new.reason is not null or new.own_due is not null or new.extended_due is not null
           or new.return_reason is not null then
            raise exception 'строка заводится пустой и в заполнении' using errcode = 'check_violation';
        end if;
        new.due_on := public.plan_row_due(начало, new.days, null, null);
        new.updated_at := now();
        return new;
    end if;

    -- Снимок строки не меняется ни у кого.
    if new.request_id is distinct from old.request_id or new.finding_id is distinct from old.finding_id
       or new.position is distinct from old.position or new.item_code is distinct from old.item_code
       or new.level is distinct from old.level or new.zone is distinct from old.zone
       or new.title_ru is distinct from old.title_ru or new.title_en is distinct from old.title_en
       or new.days is distinct from old.days then
        raise exception 'снимок строки плана не меняется' using errcode = 'check_violation';
    end if;
    if old.status = 'confirmed' and (
           new.status is distinct from old.status or new.measure is distinct from old.measure
           or new.responsible is distinct from old.responsible or new.reason is distinct from old.reason
           or new.own_due is distinct from old.own_due or new.extended_due is distinct from old.extended_due
       ) then
        raise exception 'подтверждённая строка плана не меняется' using errcode = 'check_violation';
    end if;

    правится_текст := new.measure is distinct from old.measure
        or new.responsible is distinct from old.responsible
        or new.reason is distinct from old.reason
        or new.own_due is distinct from old.own_due;

    if правится_текст then
        -- Текст и свой срок — только партнёр страны и только пока план в заполнении.
        if это_ук then
            raise exception 'мера, ответственный, причина и срок строки — слово партнёра, а не УК'
                using errcode = 'insufficient_privilege';
        end if;
        if стадия <> 'requested' then
            raise exception 'строку правят, пока план в заполнении (сейчас %)', стадия
                using errcode = 'check_violation';
        end if;
        if new.status is distinct from old.status then
            raise exception 'текст строки и её статус меняют разными действиями'
                using errcode = 'check_violation';
        end if;
        perform public.decimus_plan_partner_of(страна);
        if new.own_due is distinct from old.own_due and new.own_due is not null then
            предел := coalesce(new.extended_due, начало + new.days);
            if new.own_due > предел then
                raise exception 'срок строки позже положенного (%): позже — только переносом с согласием УК', предел
                    using errcode = 'check_violation';
            end if;
            if new.own_due < начало then
                raise exception 'срок строки раньше начала отсчёта (%)', начало
                    using errcode = 'check_violation';
            end if;
        end if;
    end if;

    if new.status is distinct from old.status then
        if автор = '' then
            raise exception 'переход строки плана идёт с подписью (decimus.plan_actor)'
                using errcode = 'check_violation';
        end if;
        if стадия <> 'in_work' then
            raise exception 'строки двигают, когда план принят (сейчас %)', стадия
                using errcode = 'check_violation';
        end if;
        if old.status = 'filling' and new.status = 'in_work' and not это_ук then
            perform public.decimus_plan_partner_of(страна);
        elsif old.status in ('in_work', 'returned') and new.status = 'done' and not это_ук then
            perform public.decimus_plan_partner_of(страна);
        elsif old.status = 'done' and new.status = 'confirmed' and это_ук then
            null;
        elsif old.status = 'done' and new.status = 'returned' and это_ук then
            if btrim(coalesce(new.return_reason, '')) = '' then
                raise exception 'вернуть строку можно только с причиной' using errcode = 'check_violation';
            end if;
        else
            raise exception 'переход строки из % в % не предусмотрен для этой роли', old.status, new.status
                using errcode = 'insufficient_privilege';
        end if;
    elsif new.return_reason is distinct from old.return_reason then
        raise exception 'причина возврата пишется вместе с возвратом' using errcode = 'check_violation';
    end if;

    new.due_on := public.plan_row_due(начало, new.days, new.own_due, new.extended_due);
    new.updated_at := now();
    return new;
end;
$$;

create trigger action_plan_rows_guarded
    before insert or update on action_plan_rows
    for each row execute function guard_action_plan_row();

-- ── Ревизия, пересчёт срока и история ──────────────────────────────────────

create function bump_action_plan_revision() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    update public.action_plan_requests set revision = revision + 1 where id = new.request_id;
    return null;
end;
$$;

-- Сдвиг начала отсчёта пересчитывает срок каждой строки: сам пересчёт делает
-- триггер строки по `plan_row_due`, перенесённых с согласием он не трогает.
create function recalc_action_plan_rows() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    update public.action_plan_rows set days = days where request_id = new.id;
    return null;
end;
$$;

create function log_action_plan_status() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    автор text := btrim(coalesce(current_setting('decimus.plan_actor', true), ''));
begin
    if new.count_from is distinct from old.count_from then
        insert into public.action_plan_events (request_id, action, actor, detail)
        values (new.id, 'count_from_changed', автор, old.count_from::text || ' ' || new.count_from::text);
    end if;
    -- Файловый план пишет историю триггерами файла и вердикта (0036).
    if new.electronic and new.status is distinct from old.status then
        insert into public.action_plan_events (request_id, action, actor, detail)
        values (
            new.id,
            case
                when old.status = 'requested' and new.status = 'on_review' then 'submitted'
                when new.status = 'in_work' then 'accepted'
                when new.status = 'requested' then 'returned'
                else 'closed'
            end,
            автор,
            case when new.status = 'requested' then new.review_comment end
        );
    end if;
    return null;
end;
$$;

create function log_action_plan_row() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    автор text := btrim(coalesce(current_setting('decimus.plan_actor', true), ''));
begin
    insert into public.action_plan_events (request_id, row_id, action, actor, detail)
    values (
        new.request_id,
        new.id,
        case new.status
            when 'in_work' then 'row_started'
            when 'done' then 'row_done'
            when 'confirmed' then 'row_confirmed'
            else 'row_returned'
        end,
        автор,
        case when new.status = 'returned' then new.return_reason end
    );
    return null;
end;
$$;

revoke all on function bump_action_plan_revision() from public;
revoke all on function recalc_action_plan_rows() from public;
revoke all on function log_action_plan_status() from public;
revoke all on function log_action_plan_row() from public;

create trigger action_plan_rows_revised
    after update of measure, responsible, reason, own_due, extended_due on action_plan_rows
    for each row execute function bump_action_plan_revision();
create trigger action_plan_requests_recalc
    after update of count_from on action_plan_requests
    for each row execute function recalc_action_plan_rows();
create trigger action_plan_requests_status_logged
    after update of status, count_from on action_plan_requests
    for each row execute function log_action_plan_status();
create trigger action_plan_rows_logged
    after update of status on action_plan_rows
    for each row execute function log_action_plan_row();

-- ── Права и пространство ───────────────────────────────────────────────────

grant select on action_plan_rows to dodo_audit_app, dodo_audit_admin;

-- Партнёр (роль приложения): текст строки, свой срок, статус строки. Какой статус и
-- когда — решает триггер, а не право на колонку.
grant update (measure, responsible, reason, own_due, status) on action_plan_rows to dodo_audit_app;

-- УК (администратор истории): строки заводит, вердикт по строке, перенос с согласием.
grant insert on action_plan_rows to dodo_audit_admin;
grant update (status, return_reason, extended_due) on action_plan_rows to dodo_audit_admin;
grant update (count_from, review_comment, electronic) on action_plan_requests to dodo_audit_admin;

alter table action_plan_rows enable row level security;
alter table action_plan_rows force row level security;
create policy action_plan_rows_access on action_plan_rows
    for all using (true) with check (true);
-- Строка — вслед за видимым запросом (0062): чужая страна не читается и не пишется.
create policy action_plan_rows_space on action_plan_rows as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from action_plan_requests r where r.id = action_plan_rows.request_id))
    with check (exists (select 1 from action_plan_requests r where r.id = action_plan_rows.request_id));
