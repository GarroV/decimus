-- Тенант управляющей компании называется `HQ`, а не `default` (D234, #439).
--
-- Код тенанта — ключ, а не подпись: он стоит в восьми таблицах, и в четырёх
-- из них — внутри составной ссылки на точку `(tenant_code, unit_id)`. Ссылки
-- заведены без `on update cascade`, поэтому переименование идёт так: снять
-- составные ссылки, переписать код везде, вернуть ссылки теми же словами,
-- убрать старую строку тенанта. Всё — одной транзакцией раннера миграций:
-- оборвись на середине, и база останется целиком на `default`.
--
-- Накат идёт под владельцем схемы, который обходит RLS, поэтому политики
-- заморозки принятых проверок (0004) переписывание кода не останавливают.
-- Триггер `inspections_move_logged` смотрит только на точку и дату и здесь
-- не срабатывает.
--
-- Отсутствие тенанта `default` не ошибка: на свежей базе строки тенантов
-- заводятся по факту первой записи, и тогда переименовывать нечего.

insert into tenants (code, name)
select 'HQ', name from tenants where code = 'default'
on conflict (code) do nothing;

alter table inspections drop constraint inspections_unit_same_tenant;
alter table inspection_moves drop constraint inspection_moves_tenant_code_new_unit_id_fkey;
alter table inspection_moves drop constraint inspection_moves_tenant_code_old_unit_id_fkey;
alter table unit_aliases drop constraint unit_aliases_tenant_code_unit_id_fkey;

update units set tenant_code = 'HQ' where tenant_code = 'default';
update unit_aliases set tenant_code = 'HQ' where tenant_code = 'default';
update inspections set tenant_code = 'HQ' where tenant_code = 'default';
update inspection_moves set tenant_code = 'HQ' where tenant_code = 'default';
update phrase_aliases set tenant_code = 'HQ' where tenant_code = 'default';
update web_users set tenant_code = 'HQ' where tenant_code = 'default';
update web_login_attempts set tenant_code = 'HQ' where tenant_code = 'default';
update mcp_tokens set tenant_code = 'HQ' where tenant_code = 'default';

alter table inspections add constraint inspections_unit_same_tenant
    foreign key (tenant_code, unit_id) references units (tenant_code, id);
alter table inspection_moves add constraint inspection_moves_tenant_code_new_unit_id_fkey
    foreign key (tenant_code, new_unit_id) references units (tenant_code, id);
alter table inspection_moves add constraint inspection_moves_tenant_code_old_unit_id_fkey
    foreign key (tenant_code, old_unit_id) references units (tenant_code, id);
alter table unit_aliases add constraint unit_aliases_tenant_code_unit_id_fkey
    foreign key (tenant_code, unit_id) references units (tenant_code, id) on delete cascade;

delete from tenants where code = 'default';

comment on table tenants is
    'Арендаторы. Тенант управляющей компании — `HQ` (D234): только он заводит '
    'новые пиццерии (D233). Строки заводятся по факту первой записи.';
