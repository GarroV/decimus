"""Подтверждение проверки на приёмке (D199).

После обхода проверка лежит в базе `draft` — на приёмке: её вычитывают и,
пока она не подтверждена, правят (D200). Подтверждение переводит её в
`finalized`: с этого момента она часть истории сети, а тело документа
заморожено политиками `0004`.

Идёт под ролью администратора истории (`DATABASE_RETRACTION_URL`). Что
подтверждает только она, держит не эта функция, а база (миграция `0034`):
триггер `inspections_acceptance_guarded` не даёт роли приложения перевести
ждущую в `finalized` и не даёт никому подтвердить отклонённую, а триггер
`inspections_insert_on_review` не даёт ей вставить проверку сразу принятой
(явным статусом или умолчанием колонки) — бот обойти приёмку не может, даже
минуя этот модуль. Владелец таблицы этими триггерами не держится: он может их
и выключить.

Подтверждение берёт замок строки (`for update`) — тот же, что берёт правка
записи (`revise.py`), поэтому правка и подтверждение одной проверки идут по
очереди.

Подтверждение обойдённой проверки с D2/D3 тем же движением открывает запрос
экшн-плана (D272). Загруженная историческая (`origin = 'import'`, D305) его не
открывает (D310) — решает строка базы, а не тот, кто подтверждает.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from .action_plans import open_auto_request, today
from .config import load_retraction_settings
from .errors import AcceptError, ActionPlanError, ConfigError
from .models import ORIGIN_IMPORT
from .queries import _require_inspection_id, _require_tenant

logger = logging.getLogger(__name__)

_SELECT_HEAD_SQL = """
select status, retracted_at, origin
from inspections
where id = %(id)s and tenant_code = %(tenant)s
for update
"""

# Условие `status = 'draft'` не украшение: подтвердить можно только ждущую, и
# число затронутых строк ниже проверяется, а не считается заведомо единицей.
_ACCEPT_SQL = """
update inspections
set status = 'finalized', accepted_at = now(), accepted_by = %(actor)s
where id = %(id)s and tenant_code = %(tenant)s and status = 'draft' and retracted_at is null
"""


def accept_inspection(inspection_id: str, *, tenant: str, actor: str) -> None:
    """Подтвердить проверку на приёмке.

    Отказ — `AcceptError` с объяснением: нет проверки, она уже принята,
    отклонена, не назван подтверждающий.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    автор = (actor or "").strip()
    if not автор:
        raise AcceptError(
            "Не назван подтверждающий. Подтверждение подписывается (D199): без имени "
            "принятая проверка неотличима от принятой никем"
        )
    settings = load_retraction_settings()
    try:
        with psycopg.connect(settings.dsn) as conn:
            происхождение = _apply(conn, ident, tenant_code, автор)
            # Загруженная историческая проверка (D305) запроса экшн-плана не
            # открывает и никому ничего не шлёт (D310): проверка трёхлетней
            # давности не может требовать от партнёра план сегодня. Решает
            # строка базы, а не вызывающий, поэтому подтверждение из веба
            # («Ждут приёмки») и из MCP ведут себя одинаково, а переписать
            # происхождение не даёт триггер `inspections_origin_fixed` (0038).
            if происхождение != ORIGIN_IMPORT:
                _open_plan_request(conn, ident, автор)
            conn.commit()
    except AcceptError:
        raise
    except psycopg.Error as exc:
        # Тип, а не текст драйвера: в тексте бывает адрес базы, а отказ
        # печатается на карточке.
        raise AcceptError(
            f"Подтвердить проверку {ident} не удалось ({type(exc).__name__}). Проверка "
            f"осталась на приёмке"
        ) from exc


def _apply(conn: psycopg.Connection[Any], ident: str, tenant: str, автор: str) -> str:
    """Перевести ждущую в принятые; вернуть происхождение проверки (0038)."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_HEAD_SQL, {"id": ident, "tenant": tenant})
        шапка = cur.fetchone()
        if шапка is None:
            raise AcceptError(f"Проверки {ident} у арендатора {tenant} нет — подтверждать нечего")
        статус, отклонена, происхождение = шапка
        if отклонена is not None:
            raise AcceptError(f"Проверка {ident} отклонена — отклонённую не подтверждают")
        if статус != "draft":
            raise AcceptError(f"Проверка {ident} уже принята — подтверждать второй раз нечего")
        cur.execute(_ACCEPT_SQL, {"id": ident, "tenant": tenant, "actor": автор})
        if cur.rowcount != 1:
            raise AcceptError(
                f"Проверку {ident} подтвердить не удалось: обновлено строк — {cur.rowcount}, "
                f"ожидалась одна. Так выглядит отказ построчной политики: подключение "
                f"обязано идти под ролью администратора истории"
            )
    return str(происхождение)


def _open_plan_request(conn: psycopg.Connection[Any], ident: str, автор: str) -> None:
    """Запрос экшн-плана при D2/D3 (D272) — в ТОЙ ЖЕ транзакции, что подтверждение.

    Проверка не может оказаться принятой без запроса, которого ждёт партнёр,
    поэтому сбой запроса — отказ подтверждения. Настройку срока читает сама
    `open_auto_request` и только когда запрос нужен: кривая
    `ACTION_PLAN_DUE_DAYS` не мешает принять проверку без D2/D3. Подробности
    сбоя — в журнал, на карточку — понятный отказ без текста драйвера.
    """
    try:
        with conn.cursor() as cur:
            open_auto_request(cur, ident, actor=автор, on=today())
    except (ActionPlanError, ConfigError, psycopg.Error) as exc:
        logger.error("запрос экшн-плана по проверке %s не завёлся: %r", ident, exc)
        raise AcceptError(
            f"Проверка {ident} не подтверждена: в ней есть D2 или D3, и вместе с ней "
            f"должен завестись запрос экшн-плана, а он не завёлся. Проверка осталась на "
            f"приёмке; причина записана в журнал"
        ) from exc
