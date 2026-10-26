"""Когда подключение оповещает владельца (D641): правила, без базы и сети.

Оповещение — только о СМЕНЕ состояния: сломалось — одно сообщение `alert`, снова зелёное —
одно `done`, пока состояние то же — тишина. Состояние подключения для оповещений — один из
трёх уровней (`OK`, `YELLOW`, `RED`) или «не знаю» (`None`: серое и неопределённое не меняют
ничего — ни тревоги, ни отбоя).

**Пробы ключей и служб оповещают только красным.** Жёлтое «не удалось проверить» — шум лимитов
и сети, а не сломанный ключ. Сборы и входы Dodo IS оповещают и жёлтым: «не пришёл в срок»,
«открыто не всё».

**Первый заход молчит.** Пока в базе нет ни одного записанного состояния, заход только
фиксирует текущее (`baseline`) — иначе выкатка присылала бы пачку тревог по уже известному.
"""

from __future__ import annotations

from .health import GREEN, RED, YELLOW

OK = "ok"
LEVEL_YELLOW = "yellow"
LEVEL_RED = "red"

#: Что сделать с подключением на этом заходе.
SEND_ALERT = "alert"
SEND_DONE = "done"


def level_of(light: str, *, red_only: bool) -> str | None:
    """Уровень для оповещений из цвета плитки; `None` — по этому цвету сказать нечего.

    `red_only` — пробы: жёлтое там «не удалось проверить», состояния оно не меняет.
    """
    if light == GREEN:
        return OK
    if light == RED:
        return LEVEL_RED
    if light == YELLOW and not red_only:
        return LEVEL_YELLOW
    return None


def decide(previous: str | None, current: str, *, baseline: bool) -> str | None:
    """`SEND_ALERT`, `SEND_DONE` или `None` — молчать.

    `previous` — последнее оповещённое состояние; `None` у кода, которого в базе нет, значит
    «был в порядке». `baseline` — первый заход после выкатки: только зафиксировать.
    """
    if baseline:
        return None
    before = previous or OK
    if before == current:
        return None
    return SEND_DONE if current == OK else SEND_ALERT
