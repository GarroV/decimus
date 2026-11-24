-- Отложенное удаление человека: 30 дней на отмену, доступ закрывается сразу.
-- История проверок и журнал остаются связаны с обезличенным техническим UUID.
alter table web_users add column delete_after timestamptz;
alter table web_users add column deleted_at timestamptz;
grant select (delete_after, deleted_at) on web_users to dodo_audit_admin;
alter table web_users add constraint web_users_deleted_disabled
    check ((delete_after is null and deleted_at is null) or disabled_at is not null);
create index web_users_deletion_due on web_users (delete_after)
    where delete_after is not null and deleted_at is null;

create function keep_deleted_user_disabled() returns trigger
language plpgsql set search_path = pg_catalog, public, pg_temp as $$
begin
    if (old.delete_after is not null or old.deleted_at is not null)
       and new.disabled_at is null then
        raise exception 'Cancel scheduled deletion before restoring access';
    end if;
    if old.deleted_at is not null then
        raise exception 'Permanently deleted account cannot be changed';
    end if;
    return new;
end $$;
create trigger web_users_deletion_guard before update on web_users
    for each row execute function keep_deleted_user_disabled();

create function schedule_user_deletion(actor uuid, target uuid) returns boolean
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    perform pg_advisory_xact_lock(hashtext('decimus.web_users.superadmin'));
    if actor = target or not exists (
        select 1 from public.web_users where id = actor and tenant_code = 'HQ'
          and role = 'superadmin' and disabled_at is null for share
    ) then
        raise insufficient_privilege;
    end if;
    update public.web_users set delete_after = now() + interval '30 days',
        disabled_at = coalesce(disabled_at, now()), disabled_by = actor
      where id = target and delete_after is null and deleted_at is null;
    if not found then return false; end if;
    -- Also close residual credentials of an account that was already frozen.
    perform public.close_all_access(target);
    return true;
end $$;

create function cancel_user_deletion(actor uuid, target uuid) returns boolean
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
    perform pg_advisory_xact_lock(hashtext('decimus.web_users.superadmin'));
    if not exists (
        select 1 from public.web_users where id = actor and tenant_code = 'HQ'
          and role = 'superadmin' and disabled_at is null for share
    ) then raise insufficient_privilege; end if;
    -- Cancellation does not reopen access or revive old sessions.
    update public.web_users set delete_after = null
      where id = target and deleted_at is null and delete_after > now();
    return found;
end $$;

create function purge_deleted_users() returns integer
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare target uuid; total integer := 0;
begin
    for target in select id from public.web_users
        where delete_after <= now() and deleted_at is null
        order by delete_after limit 100 for update skip locked
    loop
        perform public.close_all_access(target);
        delete from public.web_webauthn_challenges where user_id = target;
        delete from public.web_second_steps where user_id = target;
        delete from public.web_backup_codes where user_id = target;
        delete from public.web_totp where user_id = target;
        delete from public.web_passkeys where user_id = target;
        delete from public.bot_link_tokens where user_id = target;
        delete from public.bot_bindings where user_id = target;
        delete from public.calendar_events where user_id = target;
        delete from public.calendar_grants where user_id = target;
        delete from public.notifications where user_id = target;
        delete from public.oauth_tokens where grant_id in (
            select id from public.oauth_grants where user_id = target);
        delete from public.oauth_codes where user_id = target;
        delete from public.oauth_grants where user_id = target;
        delete from public.mcp_tokens where user_id = target;
        -- Journals retain their own retention period, but not a live session.
        update public.login_journal set session_id = null
          where session_id in (select id from public.web_sessions where user_id = target);
        delete from public.web_sessions where user_id = target;
        update public.web_users set
            login = 'deleted-' || replace(id::text, '-', ''), email = null,
            password_hash = 'scrypt$16384$8$1$' || replace(gen_random_uuid()::text, '-', '')
                || '$' || encode(sha512(convert_to(gen_random_uuid()::text, 'UTF8')), 'hex'),
            google_sub = null, display_name = null, display_name_latin = null,
            avatar = null, avatar_type = null, avatar_etag = null,
            country_filter = null, web_lang = null, disabled_by = null,
            deleted_at = now()
          where id = target;
        total := total + 1;
    end loop;
    return total;
end $$;

revoke all on function keep_deleted_user_disabled() from public;
revoke all on function schedule_user_deletion(uuid, uuid) from public;
revoke all on function cancel_user_deletion(uuid, uuid) from public;
revoke all on function purge_deleted_users() from public;
grant execute on function schedule_user_deletion(uuid, uuid) to dodo_audit_admin;
grant execute on function cancel_user_deletion(uuid, uuid) to dodo_audit_admin;
grant execute on function purge_deleted_users() to dodo_audit_app;

comment on column web_users.deleted_at is
    'Безвозвратно удалённая личность: остался только технический UUID для истории. Восстановления нет.';
