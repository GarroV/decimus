-- Срок хранения журнала шагов обхода (D712): 180 → 30 дней.
--
-- Владелец, 05.11.2026: «Хранить 180 дней нет смысла. Давай месяц, я думаю достаточно».
-- Журнал нужен, чтобы разобраться с ошибкой по свежей проверке; через месяц он уже не помогает.
-- 0119 не правится (применена на площадках): функция переопределяется, права и защита те же —
-- security definer, фиксированный search_path, execute только роли приложения.

create or replace function purge_walk_log() returns integer
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    убрано integer;
begin
    delete from public.walk_log where occurred_at < now() - interval '30 days';
    get diagnostics убрано = row_count;
    return убрано;
end $$;

revoke all on function purge_walk_log() from public;
grant execute on function purge_walk_log() to dodo_audit_app;

comment on function purge_walk_log() is
    'Срок хранения журнала шагов обхода (D712): 30 дней. Зовёт периодическая уборка бота '
    '(src/bot/upload_sweeper.py).';

comment on table walk_log is
    'Журнал шагов обхода (D710): одна строка на шаг записи нарушения в мини-аппе. Роль '
    'приложения только дописывает; читает функция walk_log_read (главный админ и админ УК), '
    'срок хранения 30 дней (purge_walk_log, D712).';
