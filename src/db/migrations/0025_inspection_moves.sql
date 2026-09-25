-- 0025_inspection_moves.sql
--
-- D195: у проведённой проверки можно сменить дату и пиццерию, и каждая такая
-- правка остаётся в истории. Содержимое проверки — записи, оценка, буква,
-- разбивка — не правится: перенос меняет «когда и где», а не документ.
--
-- ЗАЧЕМ. Проверку заводят руками, и ошибка в шапке — обычное дело: на площадке
-- 24.09.2026 рядом лежат «Тбилиси-1» и «Тбилиси -1», две точки там, где точка
-- одна. Отклонять из-за этого проверку и проводить заново нельзя — обход
-- состоялся, запись верна, неверна только подпись.
--
-- ПОЧЕМУ ИСТОРИЮ ПИШЕТ ТРИГГЕР, А НЕ КОД. История, которую пишет вызывающий,
-- держится на том, что он не забудет её записать: правка шапки мимо функции
-- переноса прошла бы бесследно, а выглядела бы законной. Здесь перенос без
-- следа невозможен физически — след пишет сама база на том же `update`, в той
-- же транзакции.
--
-- Причина и автор приходят настройками транзакции (`set local
-- decimus.move_reason`, `decimus.move_actor`): у `update` нет места для них, а
-- класть их в колонки проверки значило бы хранить в шапке последнюю причину
-- вместо истории. Нет причины или автора — отказ, а не перенос «без
-- объяснения».
--
-- ПОЧЕМУ SECURITY DEFINER. Прямой записи в историю не выдано никому — ни
-- приложению, ни администратору истории. Иначе тот, кто может переносить,
-- мог бы и дописать себе «прошлый перенос», которого не было. Пишет только
-- функция триггера, от имени владельца схемы; путь поиска у неё закреплён,
-- чтобы подложенная в чужую схему одноимённая таблица её не перехватила.

create table inspection_moves (
    id bigint generated always as identity primary key,
    tenant_code text not null,
    inspection_id uuid not null references inspections (id),
    old_date date not null,
    new_date date not null,
    old_unit_id uuid not null,
    new_unit_id uuid not null,
    reason text not null check (length(btrim(reason)) > 0),
    moved_by text not null check (length(btrim(moved_by)) > 0),
    moved_at timestamptz not null default now(),
    check (old_date <> new_date or old_unit_id <> new_unit_id),
    -- Обе точки — того же арендатора, что и проверка: тем же правилом, что
    -- `inspections_unit_same_tenant` (0002).
    foreign key (tenant_code, old_unit_id) references units (tenant_code, id),
    foreign key (tenant_code, new_unit_id) references units (tenant_code, id)
);

create index inspection_moves_inspection_idx on inspection_moves (inspection_id, moved_at);

comment on table inspection_moves is
    'История переносов проверки по дате и пиццерии (D195). Только на добавление; пишет её триггер inspections_move_logged, прямой записи не выдано никому.';

create function log_inspection_move() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public
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
    insert into inspection_moves
        (tenant_code, inspection_id, old_date, new_date, old_unit_id, new_unit_id, reason, moved_by)
    values
        (old.tenant_code, old.id, old.inspection_date, new.inspection_date,
         old.unit_id, new.unit_id, причина, автор);
    return new;
end;
$$;

revoke all on function log_inspection_move() from public;

-- Только СДАННАЯ проверка: черновик бот правит по ходу обхода, и это ещё не
-- перенос, а запись. `when` же отсекает правку, которая ничего не меняет:
-- пустой перенос не оставляет следа, а не отказывает.
create trigger inspections_move_logged
    before update of unit_id, inspection_date on inspections
    for each row
    when (old.status = 'finalized'
          and (old.unit_id is distinct from new.unit_id
               or old.inspection_date is distinct from new.inspection_date))
    execute function log_inspection_move();

-- Администратор истории переносит — две колонки, и только их. Политика
-- `inspections_finalized_is_frozen` (0010) уже пускает его к сданной
-- неотклонённой проверке; что именно он в ней меняет, держит этот грант.
grant update (unit_id, inspection_date) on inspections to dodo_audit_admin;

grant select on inspection_moves to dodo_audit_app, dodo_audit_admin;
