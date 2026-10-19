-- 0078_units_merged_into.sql
--
-- D538: название пиццерии — латиницей по справочнику (`unit_profiles`); другие
-- написания («Тбилиси-1») — только синонимы. Часть кириллических дублей на проде
-- удалить нельзя: проверки с них переехали на латинскую точку, но история
-- переносов (`inspection_moves`, только на добавление) на них ссылается.
--
-- 1. `units.merged_into` — точка снята: её место заняла другая точка того же
--    пространства. Снятая точка остаётся строкой (на неё ссылается история), но
--    ни в одном списке не показывается и не считается; поиск по её имени или
--    идентификатору ведёт на ту, в которую она влита. Пишет только
--    `make units-normalize` (`--apply`), под ролью администратора базы.
-- 2. `units_merge_guard` — три правила, которые иначе держались бы на
--    дисциплине кода: снять можно только точку без проверок; цель сама не снята
--    (цепочек нет — переход всегда в один шаг); точку, в которую уже влиты
--    другие, снять нельзя.
--
-- 3. Администратор истории (`dodo_audit_admin`) читает проверки точки по любому
--    написанию её имени — для этого ему нужна карта синонимов. Только чтение:
--    раньше ему была выдана одна `units`, и чтение «по имени» через синонимы
--    под этой ролью упало бы отказом доступа.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table units add column merged_into uuid;

alter table units add constraint units_merged_into_fkey
    foreign key (tenant_code, merged_into) references units (tenant_code, id);

alter table units add constraint units_merged_not_self
    check (merged_into is null or merged_into <> id);

create index units_merged_into_idx on units (merged_into) where merged_into is not null;

comment on column units.merged_into is
    'D538: точка влита в другую (дубль под другим написанием). Строка остаётся — на неё '
    'ссылается история переносов, — но в списках её нет, а её имя и id ведут на цель. '
    'NULL — точка живая.';

create function units_merge_guard() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
    if new.merged_into is null then
        return new;
    end if;
    if exists (select 1 from inspections i where i.unit_id = new.id) then
        raise exception using message =
            'У пиццерии с проверками дубль не снимается: проверки сначала переносят на цель';
    end if;
    if exists (select 1 from units t where t.id = new.merged_into and t.merged_into is not null) then
        raise exception using message =
            'Цель слияния сама снята: пиццерию вливают в живую точку, цепочек не бывает';
    end if;
    if exists (select 1 from units c where c.merged_into = new.id) then
        raise exception using message =
            'В эту пиццерию уже влиты другие: сначала их переводят на живую точку';
    end if;
    return new;
end $$;

create trigger units_merge_guard
    before insert or update of merged_into on units
    for each row execute function units_merge_guard();

grant select on unit_aliases to dodo_audit_admin;
