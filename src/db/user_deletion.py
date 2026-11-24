"""Удаление аккаунта с 30-дневным сроком отмены; сроки назначает только БД."""

from .web_access import _connected, _managing


def schedule(actor: str, target: str) -> bool:
    """Главный админ закрывает доступ и назначает удаление через 30 дней."""
    return _change("schedule_user_deletion", actor, target)


def cancel(actor: str, target: str) -> bool:
    """Отменить таймер до срока. Учётка остаётся замороженной."""
    return _change("cancel_user_deletion", actor, target)


def _change(function: str, actor: str, target: str) -> bool:
    # Function is an internal constant, never request input.
    with _managing("изменить удаление учётки") as conn, conn.cursor() as cur:
        cur.execute(f"select {function}(%s::uuid, %s::uuid)", (actor, target))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("account deletion did not return its result")
        return bool(row[0])


def purge_due() -> int:
    """Не более 100 просроченных учёток, с блокировкой от параллельной отмены."""
    with _connected("удалить просроченные учётки") as conn, conn.cursor() as cur:
        cur.execute("select purge_deleted_users()")
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("account purge did not return its result")
        return int(row[0])
