-- Photo-only answers are real answers; an empty field without photos is not.
-- Info and photo metadata are inserted in the same push transaction, so this
-- invariant is checked at commit rather than before the photo INSERT exists.
-- Existing captions, records, scores and fingerprints are unchanged.
alter table inspection_info
    drop constraint inspection_info_answer_is_not_empty;

-- A single-column info_id FK did not enforce inspection ownership.
alter table inspection_info
    add constraint inspection_info_id_inspection_unique unique (id, inspection_id);
alter table photos
    add constraint photos_info_same_inspection
    foreign key (info_id, inspection_id)
    references inspection_info (id, inspection_id)
    on delete cascade deferrable initially deferred;

create function guard_inspection_info_answer() returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
    owners uuid[];
    owner_id uuid;
    answer_text text;
    owner_inspection uuid;
begin
    if tg_table_name = 'inspection_info' then
        owners := array[new.id];
        if tg_op = 'UPDATE' then
            owners := owners || old.id;
        end if;
    else
        owners := array[]::uuid[];
        if tg_op <> 'INSERT' then
            owners := owners || old.info_id;
        end if;
        if tg_op <> 'DELETE' then
            owners := owners || new.info_id;
        end if;
    end if;
    -- Deterministic parent locking serializes concurrent last-photo removals.
    for owner_id in select distinct x from unnest(owners) x where x is not null order by x loop
        select text, inspection_id into answer_text, owner_inspection
        from public.inspection_info where id = owner_id for no key update;
        if found and btrim(answer_text) = '' and not exists (
            select 1 from public.photos
            where info_id = owner_id and inspection_id = owner_inspection
        ) then
            raise exception 'Information answer requires text or an owned photo'
                using errcode = '23514', constraint = 'inspection_info_answer_is_not_empty';
        end if;
    end loop;
    return null;
end;
$$;

create constraint trigger inspection_info_answer_is_not_empty
    after insert or update of text, id, inspection_id on inspection_info
    deferrable initially deferred for each row
    execute function guard_inspection_info_answer();
create constraint trigger photos_keep_info_answer
    after insert or update of info_id, inspection_id or delete on photos
    deferrable initially deferred for each row
    execute function guard_inspection_info_answer();

comment on trigger inspection_info_answer_is_not_empty on inspection_info is
    'Deferred: a real answer has a caption or at least one photo owned by the same inspection.';
