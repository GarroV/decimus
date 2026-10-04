-- 0034_inspection_acceptance.sql
--
-- D199: у проверки появляется этап приёмки. После обхода она не входит в
-- историю сети сразу — она ждёт в админке, пока человек её вычитает и
-- подтвердит.
--
-- НОВОГО СТАТУСА НЕТ, ЕСТЬ НОВЫЙ СМЫСЛ СТАРОГО. `draft` из `0004` жил только
-- внутри транзакции слива: бот клал проверку черновиком и запечатывал её
-- последним действием той же транзакции. Теперь слив черновик не запечатывает,
-- и `draft` значит «на приёмке», а `finalized` — «принята». Все заслоны `0004`,
-- `0009` и `0010` уже устроены ровно так, как нужно этапу: пока проверка
-- `draft`, её записи, формулировки и кадры правятся (это и нужно правке до
-- подтверждения, D200); как только `finalized` — заморожены.
--
-- КТО ПОДТВЕРЖДАЕТ. Только администратор истории — роль, под которой веб
-- делает действия над проверкой (отклонение, перенос). Приложение, то есть
-- бот, запечатать проверку больше не может: иначе этап приёмки держался бы на
-- том, что бот об этом не вспомнит. Запрет стоит в триггере, а не в
-- привилегиях: колонка `status` приложению выдана целиком с `0004`, и забрать
-- её значило бы сломать слив, который кладёт `status` при вставке.
--
-- ЧЬЮ ПРОВЕРКУ. Роль администратора истории одна на все пространства, поэтому
-- «подтверждает только своё пространство» (D283) держит запрос веба условием
-- `tenant_code = <пространство вошедшего>`, а не эта миграция.
--
-- Кто и когда подтвердил — колонки самой проверки: подтверждение одно и
-- обратно не отматывается, истории у него нет. У проверок, принятых до этой
-- миграции, обе колонки пусты — это правда о них («принята без этапа
-- приёмки»), а не пропуск, и выдумывать им время не нужно.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table inspections
    add column accepted_at timestamptz,
    add column accepted_by text check (accepted_by is null or length(btrim(accepted_by)) > 0),
    add constraint inspections_accepted_both_or_neither
        check ((accepted_at is null) = (accepted_by is null)),
    add constraint inspections_accepted_only_finalized
        check (status = 'finalized' or accepted_at is null);

comment on column inspections.status is
    'draft — проверка на приёмке: обойдена, ждёт вычитки и подтверждения, в историю сети не входит (D199). finalized — принята; тело документа заморожено (0004).';
comment on column inspections.accepted_at is
    'Когда проверку подтвердили на приёмке (D199). Пусто у ждущих и у принятых до появления этапа (0034).';
comment on column inspections.accepted_by is
    'Кто подтвердил проверку на приёмке (D199) — учётная запись админки.';

create function guard_inspection_acceptance() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if old.status = 'finalized' then
        if new.status <> 'finalized' then
            raise exception 'принятую проверку % нельзя вернуть на приёмку', old.id
                using errcode = 'check_violation';
        end if;
        if new.accepted_at is distinct from old.accepted_at
           or new.accepted_by is distinct from old.accepted_by then
            raise exception 'отметку о приёмке проверки % нельзя переписать', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    if new.status = 'finalized' then
        if not pg_has_role(current_user, 'dodo_audit_admin', 'member') then
            raise exception 'подтвердить проверку % может только администратор истории', old.id
                using errcode = 'insufficient_privilege';
        end if;
        if new.accepted_at is null then
            raise exception 'проверка % подтверждается с отметкой, кто и когда', old.id
                using errcode = 'check_violation';
        end if;
    end if;
    return new;
end;
$$;

create trigger inspections_acceptance_guarded
    before update of status, accepted_at, accepted_by on inspections
    for each row execute function guard_inspection_acceptance();

grant update (status, accepted_at, accepted_by) on inspections to dodo_audit_admin;
