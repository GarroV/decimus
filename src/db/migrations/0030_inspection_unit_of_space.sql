-- 0030_inspection_unit_of_space.sql
--
-- Волна 1 пространств (#340, D284): справочник пиццерий один. Проверка партнёра
-- ссылается на точку справочника УК своей страны; точку своего тенанта у
-- партнёра заводить незачем и нельзя (D234).
--
-- Составная ссылка «точка своего тенанта» (0002, 0025, 0027) заменяется простой
-- ссылкой на точку и сторожем: точка проверки — либо своего тенанта, либо
-- справочника УК, и у партнёра — только из его стран. Сторож в схеме, а не в
-- боте: бот пропускает имя как написано, когда справочник недоступен (#471).
--
-- Прежние проверки партнёров на собственных точках остаются законными (ветка
-- «точка своего тенанта»): накат не трогает данных.
--
-- Синонимы точек (`unit_aliases`) не трогаются: их по-прежнему заводит УК в
-- своём справочнике, и составная ссылка там остаётся.
--
-- Функция сторожа работает с правами ВЛАДЕЛЬЦА (`security definer`) и с
-- закреплённым `search_path`: её ответ не должен зависеть от того, какие права
-- на `units` и `space_countries` есть у роли, которая пишет проверку (роль
-- приложения — слив, администратор истории — перенос), и от того, какие
-- объекты эта роль подложила себе в путь поиска.

alter table inspections drop constraint inspections_unit_same_tenant;
alter table inspections add constraint inspections_unit_id_fkey
    foreign key (unit_id) references units (id);

alter table inspection_moves drop constraint inspection_moves_tenant_code_new_unit_id_fkey;
alter table inspection_moves drop constraint inspection_moves_tenant_code_old_unit_id_fkey;
alter table inspection_moves add constraint inspection_moves_new_unit_id_fkey
    foreign key (new_unit_id) references units (id);
alter table inspection_moves add constraint inspection_moves_old_unit_id_fkey
    foreign key (old_unit_id) references units (id);

create function inspection_unit_of_space() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
declare
    чья text;
    страна text;
begin
    select tenant_code, country into чья, страна from units where id = new.unit_id;
    if чья = new.tenant_code then
        return new;
    end if;
    if чья = 'HQ' and exists (
        select 1 from space_countries s
         where s.tenant_code = new.tenant_code and s.country = страна
    ) then
        return new;
    end if;
    raise exception using message =
        'Пиццерия проверки не из справочника страны этого пространства';
end $$;

create trigger inspections_unit_of_space
    before insert or update of unit_id, tenant_code on inspections
    for each row execute function inspection_unit_of_space();

-- Чтение по охвату (`src/db/reach.py`) идёт без ведущего тенанта: УК читает всю
-- сеть, партнёр — пиццерии своих стран, и условие на тенант приходит массивом
-- (`= any(...)`), под которым Postgres 16 не отдаёт строки индекса
-- `(tenant_code, inspection_date desc, …)` в порядке дат. Без индекса по дате
-- «последние сто проверок» — полный проход и сортировка всей таблицы.
create index inspections_date_idx on inspections (inspection_date desc, pushed_at desc);

comment on index inspections_date_idx is
    'Проверки в охвате читающего за период и в порядке дат обхода (волна 1, #340).';
