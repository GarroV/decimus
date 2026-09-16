"""T034: модель недоступна — деградация до ручного выбора кнопками.

Контракт блока: «блок деградирует: при недоступной модели бот предлагает
выбрать пункт кнопками вручную». `manual_candidates` — то, чем блок это
исполняет: без сети, без ранжирования по словам комментария (комментарий тут
взять неоткуда — модель как раз недоступна), с пунктами `MGM22`/`MGM23`,
которые модели не показывают никогда, и с ПОЛНОЙ базой перечня: зона его
упорядочивает, но не режет (T265, #218).
"""

from __future__ import annotations

from pathlib import Path

from src.domain import allowed_levels, list_items
from src.recognize.config import NO_CHAT
from src.recognize.manual import manual_candidates
from src.recognize.shortlist import MANUAL_ONLY


def test_база_перечня_это_весь_чек_лист_а_зона_его_упорядочивает(domain_env: Path) -> None:
    """Зона задаёт порядок перечня и не задаёт его состав (T265, #218).

    До задачи базой был перечень одной зоны, и пункт чужой зоны исчезал из
    кнопок вовсе: последний рубеж выбора отказывал ровно в том случае, ради
    которого он и существует. Поэтому проверяется и полнота базы, и порядок —
    пункты названной зоны идут первыми.
    """
    все = {i.code for i in list_items() if i.kind == "violation"}
    зональные = {i.code for i in list_items(zone="hot_kitchen") if i.kind == "violation"}

    итог = [c.code for c in manual_candidates("hot_kitchen", chat_id=NO_CHAT)]

    assert set(итог) == все, "перечень обрезан зоной"
    свои = [место for место, code in enumerate(итог) if code in зональные]
    чужие = [место for место, code in enumerate(итог) if code not in зональные]
    assert свои and чужие, "предпосылка теста: в чек-листе есть пункты обеих половин"
    assert max(свои) < min(чужие), "пункты названной зоны обязаны идти первыми"


def test_ручные_пункты_аудитора_доступны(domain_env: Path) -> None:
    итог = manual_candidates("dining", chat_id=NO_CHAT)

    assert set(MANUAL_ONLY) <= {c.code for c in итог}


def test_служебные_пункты_не_предлагаются(domain_env: Path) -> None:
    служебные = {i.code for i in list_items() if i.kind in ("aggregate", "info")}

    итог = manual_candidates("fridge", chat_id=NO_CHAT)

    assert not (служебные & {c.code for c in итог})


def test_без_зоны_отдаются_все_нарушения(domain_env: Path) -> None:
    все = {i.code for i in list_items() if i.kind == "violation"}

    итог = manual_candidates(None, chat_id=NO_CHAT)

    assert {c.code for c in итог} == все


def test_каждый_пункт_несёт_допустимые_классы_и_текст(domain_env: Path) -> None:
    итог = manual_candidates("hot_kitchen", chat_id=NO_CHAT)

    cln05 = next(c for c in итог if c.code == "CLN05")
    assert cln05.levels == tuple(allowed_levels("CLN05"))
    assert cln05.title  # текст пункта из методики, не пустая строка


def test_порядок_как_в_чек_листе_а_не_по_словам(domain_env: Path) -> None:
    # Без слов аудитора карте кадров нечего поднимать наверх — вызов
    # `shortlist("", ...)` внутри не находит подсказок. Порядок задаёт одна
    # только зона: свои пункты вперёд, и внутри каждой половины сохраняется
    # порядок чек-листа (сортировка устойчива, T265).
    нарушения = [i.code for i in list_items() if i.kind == "violation"]
    зональные = {i.code for i in list_items(zone="hot_kitchen") if i.kind == "violation"}
    ожидание = [c for c in нарушения if c in зональные] + [
        c for c in нарушения if c not in зональные
    ]

    итог = manual_candidates("hot_kitchen", chat_id=NO_CHAT)

    assert [c.code for c in итог] == ожидание


def test_язык_по_умолчанию_русский(domain_env: Path) -> None:
    ru = manual_candidates("hot_kitchen", chat_id=NO_CHAT)
    en = manual_candidates("hot_kitchen", lang="en", chat_id=NO_CHAT)

    cln05_ru = next(c for c in ru if c.code == "CLN05").title
    cln05_en = next(c for c in en if c.code == "CLN05").title

    assert cln05_ru != cln05_en
