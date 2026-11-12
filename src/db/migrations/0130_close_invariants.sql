-- 0130_close_invariants.sql
--
-- Три красных инварианта базы на main (проверки `test_db_definer_search_path` и
-- `test_db_space_isolation`), закрываются новым файлом: применённые `0123` и `0128` заморожены.
--
-- 1. `set_session_acting_tenant` (`0123`) — функция владельца с путём поиска без `pg_temp`:
--    временная таблица вызвавшего могла бы подменить настоящую (правило `0033`). Путь
--    выправляется на `pg_catalog, public, pg_temp`; тело функции не меняется.
--
-- 2. `batch_letters` и `batch_letter_inspections` (`0128`): роли приложения выдан `select`, а
--    политика пространства не заведена — разрешающая `using (true)` пускала читать письма ВСЕХ
--    пространств. Сами запросы (`src/db/batch_letters.py`) отбирают по `tenant_code`, но на
--    одном условии охвата изоляция не держится (`0062`). Добавляются ограничивающие политики
--    пространства: письмо видит и пишет только то пространство, чьё оно (`*` — служебное, всё);
--    состав письма — вслед за видимым письмом.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter function set_session_acting_tenant(text, text)
    set search_path = pg_catalog, public, pg_temp;

create policy batch_letters_space on batch_letters as restrictive
    for all to dodo_audit_app
    using (decimus_space_writes(tenant_code))
    with check (decimus_space_writes(tenant_code));

create policy batch_letter_inspections_space on batch_letter_inspections as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from batch_letters b where b.id = batch_letter_inspections.batch_letter_id))
    with check (exists (select 1 from batch_letters b where b.id = batch_letter_inspections.batch_letter_id));
