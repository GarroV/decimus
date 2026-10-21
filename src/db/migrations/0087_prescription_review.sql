-- 0087_prescription_review.sql
--
-- Согласование предписания ОСБ (D599, D600, шаг 1 спеки 2026-10-21-osb-prescriptions-design).
-- До этой миграции любой сотрудник УК клал черновик в Gmail сам (0037). Теперь
-- ни одно предписание не уходит партнёру без согласования ОСБ.
--
-- ЖИЗНЕННЫЙ ЦИКЛ
--
--   draft ──(запросили)──► review ──(ОСБ согласовала)──► approved ──(черновик в Gmail)──► issued ──(закрыли)──► closed
--     ▲                      │                              ▲
--     └──(ОСБ вернула, комментарий)         draft ──(ОСБ согласовала сама)──┘
--
-- * `draft` — черновик автора; `review` — ждёт ОСБ; `approved` — согласовано,
--   текст, нарушения и адресаты заморожены; `issued`, `closed` — как в 0037.
-- * Возврат `review → draft` — только с комментарием (настройка транзакции
--   `decimus.prescription_comment`, как подпись у `decimus.prescription_actor`):
--   без комментария триггер отказывает.
-- * Правка согласованного (текст, адресаты, срок, пиццерии, основания) снимает
--   согласование: статус сам становится `review` (событие `edited`, деталь
--   `approval_dropped`). Согласование можно и просто снять назад в `review`.
-- * Отправка (`→ issued`) — только из `approved`. Из черновика и из `review` она
--   недостижима ни у какой роли.
-- * Вставка по-прежнему только черновиком (урок #490).
-- * Выданные и закрытые до миграции остаются как есть: поля согласования у них
--   пусты, а ограничение это допускает.
--
-- КТО ИМЕННО ОСБ — решает веб (`prescription.manage`): база видит лишь подпись
-- действующего. Здесь держится порядок переходов, а не роли.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table prescriptions add column approved_by text;
alter table prescriptions add column approved_at timestamptz;

alter table prescriptions drop constraint prescriptions_status_check;
alter table prescriptions add constraint prescriptions_status_check
    check (status in ('draft', 'review', 'approved', 'issued', 'closed'));

alter table prescriptions drop constraint prescriptions_check;
alter table prescriptions add constraint prescriptions_steps_check check (
    (status in ('draft', 'review')
        and approved_by is null and approved_at is null
        and issued_by is null and issued_at is null
        and closed_by is null and closed_at is null and close_comment is null)
    or (status = 'approved'
        and length(btrim(coalesce(approved_by, ''))) > 0 and approved_at is not null
        and issued_by is null and issued_at is null
        and closed_by is null and closed_at is null and close_comment is null)
    -- Выданные: согласование есть у новых, у прежних (до 0087) пусто — оба поля вместе.
    or (status = 'issued' and length(btrim(coalesce(issued_by, ''))) > 0
        and issued_at is not null
        and ((approved_by is null) = (approved_at is null))
        and closed_by is null and closed_at is null and close_comment is null)
    or (status = 'closed' and length(btrim(coalesce(issued_by, ''))) > 0
        and issued_at is not null
        and ((approved_by is null) = (approved_at is null))
        and length(btrim(coalesce(closed_by, ''))) > 0 and closed_at is not null
        and length(btrim(coalesce(close_comment, ''))) > 0)
);

alter table prescription_events drop constraint prescription_events_action_check;
alter table prescription_events add constraint prescription_events_action_check
    check (action in ('created', 'edited', 'requested', 'returned', 'approved',
                      'issued', 'replied', 'closed'));

-- Очередь УК: открытые — всё, что не закрыто (частичный индекс 0037 остаётся).

grant update (approved_by) on prescriptions to dodo_audit_admin;

comment on column prescriptions.approved_by is
    'Кто согласовал (ОСБ). Пусто у черновика, у запроса и у выданных до 0087.';
comment on column prescriptions.approved_at is 'Когда согласовано; ставит триггер.';
comment on table prescriptions is
    'Предписания УК партнёру страны (D266, D270, D599). draft → review → approved → issued (черновик лёг в Gmail) → closed (с комментарием); возврат review → draft с комментарием. Отправленное не правится; просрочка считается.';

-- ── Переходы предписания ────────────────────────────────────────────────────

create or replace function guard_prescription() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чужая text;
    правка boolean;
    подпись text := btrim(coalesce(current_setting('decimus.prescription_actor', true), ''));
begin
    if tg_op = 'INSERT' then
        if new.status <> 'draft' or new.issued_by is not null or new.issued_at is not null
           or new.closed_by is not null or new.closed_at is not null
           or new.close_comment is not null
           or new.approved_by is not null or new.approved_at is not null then
            raise exception 'предписание заводится только черновиком, а не %', new.status
                using errcode = 'insufficient_privilege';
        end if;
        if not exists (
            select 1 from public.units u where u.tenant_code = 'HQ' and u.country = new.country
        ) then
            raise exception 'в справочнике нет пиццерий страны % — предписание некому адресовать', new.country
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    perform public.lock_prescription(old.id);
    if new.id is distinct from old.id or new.country is distinct from old.country
       or new.created_by is distinct from old.created_by
       or new.created_at is distinct from old.created_at then
        raise exception 'страна и авторство предписания % не меняются', old.id
            using errcode = 'check_violation';
    end if;
    if old.status = 'closed' then
        raise exception 'закрытое предписание % не меняется', old.id
            using errcode = 'check_violation';
    end if;

    if old.status = 'issued' then
        if new.status <> 'closed'
           or new.subject is distinct from old.subject or new.body is distinct from old.body
           or new.recipients is distinct from old.recipients
           or new.due_on is distinct from old.due_on
           or new.issued_by is distinct from old.issued_by
           or new.issued_at is distinct from old.issued_at
           or new.approved_by is distinct from old.approved_by
           or new.approved_at is distinct from old.approved_at then
            raise exception 'отправленное предписание % не правится: закройте его и составьте новое', old.id
                using errcode = 'check_violation';
        end if;
        if length(btrim(coalesce(new.close_comment, ''))) = 0
           or length(btrim(coalesce(new.closed_by, ''))) = 0 then
            raise exception 'предписание % закрывают с подписью и комментарием', old.id
                using errcode = 'check_violation';
        end if;
        new.closed_at := now();
        return new;
    end if;

    -- old.status in ('draft', 'review', 'approved')
    if new.status = 'closed' then
        raise exception 'предписание % не закрывают, пока оно не отправлено', old.id
            using errcode = 'check_violation';
    end if;
    if new.closed_by is not null or new.close_comment is not null or new.closed_at is not null then
        raise exception 'у неотправленного предписания % нет закрытия', old.id
            using errcode = 'check_violation';
    end if;

    правка := new.subject is distinct from old.subject or new.body is distinct from old.body
              or new.recipients is distinct from old.recipients
              or new.due_on is distinct from old.due_on;

    -- Согласованное правится только со снятием согласования: статус становится review сам.
    if old.status = 'approved' and new.status = 'approved' then
        if new.approved_by is distinct from old.approved_by
           or new.approved_at is distinct from old.approved_at then
            raise exception 'кто и когда согласовал предписание %, не переписывают', old.id
                using errcode = 'check_violation';
        end if;
        if not правка then
            return new;
        end if;
        if подпись = '' then
            raise exception 'предписание % правят с подписью (decimus.prescription_actor)', old.id
                using errcode = 'check_violation';
        end if;
        new.status := 'review';
        new.approved_by := null;
        new.approved_at := null;
        return new;
    end if;

    -- Согласование не подставляют руками: оно приходит только переходом в approved.
    if new.status in ('draft', 'review') and (new.approved_by is not null or new.approved_at is not null) then
        raise exception 'у предписания % в статусе % нет согласования', old.id, new.status
            using errcode = 'check_violation';
    end if;
    if new.status in ('draft', 'review') and new.issued_by is not null then
        raise exception 'у предписания % нет отправителя', old.id
            using errcode = 'check_violation';
    end if;

    -- Правка на месте (draft → draft, review → review) и снятие согласования (approved → review).
    if new.status = old.status or (old.status = 'approved' and new.status = 'review') then
        if подпись = '' then
            raise exception 'предписание % правят с подписью (decimus.prescription_actor)', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    -- draft → review: запрос на согласование. Автор мог поправить текст в той же форме.
    if old.status = 'draft' and new.status = 'review' then
        if подпись = '' then
            raise exception 'запрос на согласование предписания % подписывается', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    -- review → draft: возврат автору, только с комментарием.
    if old.status = 'review' and new.status = 'draft' then
        if правка then
            raise exception 'предписание % возвращают как есть: правка и возврат — разными шагами', old.id
                using errcode = 'check_violation';
        end if;
        if подпись = '' then
            raise exception 'возврат предписания % подписывается', old.id
                using errcode = 'check_violation';
        end if;
        if btrim(coalesce(current_setting('decimus.prescription_comment', true), '')) = '' then
            raise exception 'предписание % возвращают с комментарием: что поправить', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    -- draft | review → approved: согласовано тем, что лежит, без правки.
    if new.status = 'approved' and old.status in ('draft', 'review') then
        if правка then
            raise exception 'предписание % согласуют тем, что лежит, без правки', old.id
                using errcode = 'check_violation';
        end if;
        if length(btrim(coalesce(new.approved_by, ''))) = 0 then
            raise exception 'согласование предписания % подписывается', old.id
                using errcode = 'check_violation';
        end if;
        if new.issued_by is not null or new.issued_at is not null then
            raise exception 'у согласуемого предписания % нет отправителя', old.id
                using errcode = 'check_violation';
        end if;
        new.approved_at := now();
        return new;
    end if;

    if new.status = 'issued' and old.status <> 'approved' then
        raise exception 'предписание % отправляют только согласованным (сейчас %)', old.id, old.status
            using errcode = 'check_violation';
    end if;

    -- approved → issued: содержимое то же, что согласовано.
    if new.status <> 'issued' then
        raise exception 'переход предписания % из % в % не предусмотрен', old.id, old.status, new.status
            using errcode = 'check_violation';
    end if;
    if правка or new.approved_by is distinct from old.approved_by
       or new.approved_at is distinct from old.approved_at then
        raise exception 'предписание % отправляют тем, что согласовано, без правки', old.id
            using errcode = 'check_violation';
    end if;
    if length(btrim(coalesce(new.issued_by, ''))) = 0 then
        raise exception 'отправка предписания % подписывается', old.id
            using errcode = 'check_violation';
    end if;
    if length(btrim(new.recipients)) = 0 then
        raise exception 'у предписания % нет адресатов', old.id
            using errcode = 'check_violation';
    end if;
    if new.due_on < public.prescription_today() then
        raise exception 'срок предписания % уже прошёл', old.id
            using errcode = 'check_violation';
    end if;
    select u.name into чужая
    from public.prescription_units pu
    join public.units u on u.id = pu.unit_id
    where pu.prescription_id = old.id and u.country is distinct from old.country
    limit 1;
    if чужая is not null then
        raise exception 'пиццерия % уже не в стране %', чужая, old.country
            using errcode = 'check_violation';
    end if;
    if exists (
        select 1
        from public.prescription_inspections pi
        join public.inspections i on i.id = pi.inspection_id
        join public.units u on u.id = i.unit_id
        where pi.prescription_id = old.id
          and (i.tenant_code <> 'HQ' or i.status <> 'finalized' or i.retracted_at is not null
               or u.country is distinct from old.country)
    ) then
        raise exception 'проверка-основание предписания % отклонена или уже не в стране %', old.id, old.country
            using errcode = 'check_violation';
    end if;
    new.issued_at := now();
    return new;
end;
$$;

-- ── Связи: у черновика, запроса и согласованного (последнее снимает согласование) ──

create or replace function guard_prescription_unit() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чья uuid := case when tg_op = 'DELETE' then old.prescription_id else new.prescription_id end;
    статус text;
    страна text;
begin
    perform public.lock_prescription(чья);
    select p.status, p.country into статус, страна from public.prescriptions p where p.id = чья;
    if статус is null or статус not in ('draft', 'review', 'approved') then
        raise exception 'пиццерии меняют только у неотправленного предписания (сейчас %)', coalesce(статус, 'нет предписания')
            using errcode = 'check_violation';
    end if;
    if btrim(coalesce(current_setting('decimus.prescription_actor', true), '')) = '' then
        raise exception 'связи черновика % правят с подписью (decimus.prescription_actor)', чья
            using errcode = 'check_violation';
    end if;
    if tg_op = 'DELETE' then
        perform public.drop_prescription_approval(чья, статус);
        return old;
    end if;
    if not exists (
        select 1 from public.units u
        where u.id = new.unit_id and u.tenant_code = 'HQ' and u.country = страна
    ) then
        raise exception 'пиццерия % не из страны %', new.unit_id, страна
            using errcode = 'check_violation';
    end if;
    perform public.drop_prescription_approval(чья, статус);
    return new;
end;
$$;

create or replace function guard_prescription_inspection() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чья uuid := case when tg_op = 'DELETE' then old.prescription_id else new.prescription_id end;
    статус text;
    страна text;
begin
    perform public.lock_prescription(чья);
    select p.status, p.country into статус, страна from public.prescriptions p where p.id = чья;
    if статус is null or статус not in ('draft', 'review', 'approved') then
        raise exception 'основания меняют только у неотправленного предписания (сейчас %)', coalesce(статус, 'нет предписания')
            using errcode = 'check_violation';
    end if;
    if btrim(coalesce(current_setting('decimus.prescription_actor', true), '')) = '' then
        raise exception 'связи черновика % правят с подписью (decimus.prescription_actor)', чья
            using errcode = 'check_violation';
    end if;
    if tg_op = 'DELETE' then
        perform public.drop_prescription_approval(чья, статус);
        return old;
    end if;
    if not exists (
        select 1
        from public.inspections i
        join public.units u on u.id = i.unit_id
        where i.id = new.inspection_id and i.tenant_code = 'HQ' and i.status = 'finalized'
          and i.retracted_at is null and u.country = страна
    ) then
        raise exception 'основанием служит принятая и не отклонённая проверка УК страны %', страна
            using errcode = 'check_violation';
    end if;
    perform public.drop_prescription_approval(чья, статус);
    return new;
end;
$$;

-- Правка связей согласованного снимает согласование — как правка текста.
-- security definer: снять `approved_at` ролью администратора нельзя (колонку ставит
-- только триггер), а снятие согласования при правке связей — его же работа.
create function drop_prescription_approval(ident uuid, current_status text) returns void
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if current_status = 'approved' then
        update public.prescriptions
        set status = 'review', approved_by = null, approved_at = null
        where id = ident;
    end if;
end;
$$;

-- ── История ─────────────────────────────────────────────────────────────────

create or replace function log_prescription() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    подпись text := btrim(coalesce(current_setting('decimus.prescription_actor', true), ''));
begin
    if tg_op = 'INSERT' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'created', new.created_by, new.country || ' ' || new.due_on::text);
    elsif new.status = 'review' and old.status = 'draft' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'requested', подпись, null);
    elsif new.status = 'draft' and old.status = 'review' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'returned', подпись,
                btrim(current_setting('decimus.prescription_comment', true)));
    elsif new.status = 'approved' and old.status in ('draft', 'review') then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'approved', new.approved_by, null);
    elsif new.status = 'issued' and old.status = 'approved' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'issued', new.issued_by, new.recipients);
        insert into public.country_recipients (country, recipients, updated_by)
        values (new.country, new.recipients, new.issued_by)
        on conflict (country) do update
            set recipients = excluded.recipients,
                updated_by = excluded.updated_by,
                updated_at = now();
    elsif new.status = 'closed' and old.status = 'issued' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'closed', new.closed_by, new.close_comment);
    elsif old.status = 'approved' and new.status = 'review' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'edited', подпись, 'approval_dropped');
    else
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'edited', подпись, null);
    end if;
    return null;
end;
$$;

revoke all on function drop_prescription_approval(uuid, text) from public;
grant execute on function drop_prescription_approval(uuid, text) to dodo_audit_admin;
