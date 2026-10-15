-- 0073_inspection_by_process.sql
--
-- D507: «Где сеть теряет проценты» на главной читается по процессам (блокам
-- методики), а не по зонам. Разбивку по процессам движок считает с D120/D121
-- (`by_process` в ответе `audit.py score`), но в базу она не доезжала: рядом с
-- `by_zone` её не было. Колонка её хранит — в том виде, как вернул движок
-- (`{код процесса: {code, name_ru, name_en, scored, d1, d2, d3, loss}}`);
-- сумма `loss` по процессам сходится с `deductions` проверки.
--
-- NULL — разбивки нет: проверка слита до этой миграции и ещё не долита
-- (`tools/backfill_by_process.py`) либо историческая (D332: её оценка перенесена
-- из старого отчёта, движок её не считал, и разбивки по процессам у неё нет и
-- не будет). Экран читает NULL как «числа нет» и в сумму не берёт.
--
-- Запись: слив и правка на приёмке пишут колонку вместе с остальной оценкой
-- (роль приложения, права на таблицу выданы целиком, 0004). Долив принятых
-- проверок идёт под администратором истории, и ему колонка выдана отдельным
-- правом (политика `inspections_finalized_is_frozen`, 0010, пускает его к
-- сданной неотклонённой проверке; что он в ней меняет, держит этот грант).
-- Сторож ниже сужает его ещё: в принятой проверке колонка пишется один раз,
-- из NULL, а у исторической не пишется вовсе.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table inspections
    add column if not exists by_process jsonb;

comment on column inspections.by_process is
    'Разбивка оценки по процессам (блокам методики) как её вернул движок (D120/D121, D507): {код: {code, name_ru, name_en, scored, d1, d2, d3, loss}}. NULL — не долита либо историческая (D332).';

create function guard_inspection_by_process() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.origin = 'legacy' and new.by_process is not null then
        raise exception 'у исторической проверки % разбивки по процессам нет и не будет (D332)', old.id
            using errcode = 'check_violation';
    end if;
    if old.status = 'finalized' and old.by_process is not null then
        raise exception 'разбивку по процессам принятой проверки % нельзя переписать', old.id
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

revoke all on function guard_inspection_by_process() from public;

create trigger inspections_by_process_guarded
    before update of by_process on inspections
    for each row
    when (old.by_process is distinct from new.by_process)
    execute function guard_inspection_by_process();

grant update (by_process) on inspections to dodo_audit_admin;
