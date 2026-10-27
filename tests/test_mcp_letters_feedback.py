"""D663, D664: обратная связь аудитора в письме, которое собирают MCP и веб.

Движок вставляет «сильные стороны» и «зоны роста» по роли пункта (`letter_role`),
а слой `src/report/letters.py` обязан довезти до отправителя две вещи: выбранный
шаблон и предупреждение, что текст записан не на языке письма и потому НЕ
вставлен. Правила самого письма проверяет `test_engine_letter_feedback.py`; здесь
— что слой их не потерял по дороге: ни шаблон, ни перечень невосстановленного.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import ЧЕКЛИСТ, build_methodology

from src.db.models import FindingRow, InfoRow, InspectionDetail, InspectionRow
from src.domain.config import DATA_FILES
from src.domain.version import VERSION_FILE, compose
from src.report import letters
from src.report.letters import LetterError

СИЛЬНЫЕ = "Чистая кухня, вежливая смена"
РОСТ = "Сроки годности на заготовках"

#: Чек-лист синтетической методики с двумя информационными пунктами и ролями.
ЧЕКЛИСТ_С_РОЛЯМИ = (
    ЧЕКЛИСТ.replace("zones,days\n", "zones,days,letter_role\n")
    .replace("D1;D2,fridge,10\n", "D1;D2,fridge,10,\n")
    .replace("D1,*,10\n", "D1,*,10,\n")
    + "INF01,info,Информация,Information,Сильные стороны,Strengths,,,1,strengths\n"
    + "INF06,info,Информация,Information,Зоны роста,Growth areas,,,1,growth\n"
)


def _издание(where: Path, *, roles: bool) -> str:
    """Издание с ролями (или без) и его имя, посчитанное по содержимому."""
    build_methodology(where)
    if roles:
        (where / "checklist.csv").write_text(ЧЕКЛИСТ_С_РОЛЯМИ, encoding="utf-8")
    (where / VERSION_FILE).write_text("feedback 2026-10-27\n", encoding="utf-8")
    return compose(where, DATA_FILES)


def _проверка(version: str, *, speech: str = "", findings_lang: str = "ru") -> InspectionDetail:
    строка = InspectionRow(
        id="11111111-1111-1111-1111-111111111111",
        tenant_code="укашка",
        unit_name="Белград-1",
        chat_id=100500100,
        kind="planned",
        inspection_date=date(2026, 8, 19),
        report_lang="ru",
        checklist_version=version,
        pct=99.5,
        grade="A",
        findings_count=1,
        pushed_at="2026-08-19T18:00:00+02:00",
        auditor="Василий",
        city="Белград",
        partner="Партнёр",
        contact="p@example.com",
        speech_lang=speech,
    )
    находка = FindingRow(
        id="22222222-2222-2222-2222-222222222222",
        inspection_id=строка.id,
        unit_name="Белград-1",
        inspection_date=строка.inspection_date,
        n=1,
        code="CLN01",
        level="D1",
        zone="fridge",
        zone_unusual=False,
        source="comment",
        lang=findings_lang,
        text="Пол в разводах",
        comment="",
    )
    return InspectionDetail(
        inspection=строка,
        deductions=0.5,
        counts={"D1": 1},
        by_zone={},
        findings=(находка,),
        info=(
            InfoRow(code="INF01", text=f"1. {СИЛЬНЫЕ}"),
            InfoRow(code="INF06", text=РОСТ),
            InfoRow(code="INF07", text="30.09.2026"),
        ),
    )


@pytest.fixture
def papers(tmp_path: Path) -> tuple[letters.Papers, str]:
    версия = _издание(tmp_path / "store" / "versions" / "v", roles=True)
    # Каталог версии носит ИМЯ издания: `pinned` сверяет отпечаток с именем.
    (tmp_path / "store" / "versions" / "v").rename(tmp_path / "store" / "versions" / версия)
    build_methodology(tmp_path / "live")
    return letters.Papers(live=tmp_path / "live", store=tmp_path / "store"), версия


def test_шаблон_1_по_умолчанию_и_шаблон_2_доезжают_до_движка(
    papers: tuple[letters.Papers, str],
) -> None:
    хранилище, версия = papers
    проверка = _проверка(версия)
    первый = letters.build(проверка, lang="ru", papers=хранилище)
    assert первый["template"] == 1
    текст = str(первый["letter"])
    # Нумерация срезана, слова аудитора как есть.
    assert f"Что получается хорошо:\n{СИЛЬНЫЕ}\n" in текст
    assert текст.index("Что получается хорошо:") < текст.index("Что отметили:")
    assert текст.index("Над чем стоит поработать:") > текст.index("Что отметили:")
    assert первый["not_restored"] == [] and первый["ready_to_send"] is True

    второй = letters.build(проверка, lang="ru", papers=хранилище, template=2)
    assert второй["template"] == 2
    текст2 = str(второй["letter"])
    assert текст2.index("Что отметили:") < текст2.index("Что получается хорошо:")
    assert текст2.index("Над чем стоит поработать:") < текст2.index("Спасибо за работу")


def test_неизвестный_шаблон_отказ(papers: tuple[letters.Papers, str]) -> None:
    хранилище, версия = papers
    with pytest.raises(LetterError, match="Шаблона письма"):
        letters.build(_проверка(версия), lang="ru", papers=хранилище, template=3)


def test_язык_не_совпал_блока_нет_и_письмо_не_готово(papers: tuple[letters.Papers, str]) -> None:
    """Английское письмо по записи по-русски: ни слова аудитора, и отправитель предупреждён."""
    хранилище, версия = papers
    ответ = letters.build(_проверка(версия), lang="en", papers=хранилище)
    текст = str(ответ["letter"])
    assert СИЛЬНЫЕ not in текст and РОСТ not in текст
    assert "What is going well:" not in текст
    assert letters.FEEDBACK_LANG_FIELD in ответ["not_restored"]  # type: ignore[operator]
    assert ответ["ready_to_send"] is False
    assert "feedback" in str(ответ["status"]) and "NOT inserted" in str(ответ["status"])


def test_язык_речи_проверки_сильнее_языка_находок(papers: tuple[letters.Papers, str]) -> None:
    """Язык записи берётся у проверки (`speech_lang`), а не угадывается по находкам."""
    хранилище, версия = papers
    # Находка записана по-английски, а речь аудитора — русская: обратная связь русская.
    ответ = letters.build(
        _проверка(версия, speech="ru", findings_lang="en"), lang="ru", papers=хранилище
    )
    assert СИЛЬНЫЕ in str(ответ["letter"])
    assert letters.FEEDBACK_LANG_FIELD not in ответ["not_restored"]  # type: ignore[operator]


def test_нет_пометки_у_пунктов_письмо_как_раньше(tmp_path: Path) -> None:
    версия = _издание(tmp_path / "store" / "versions" / "v", roles=False)
    (tmp_path / "store" / "versions" / "v").rename(tmp_path / "store" / "versions" / версия)
    build_methodology(tmp_path / "live")
    хранилище = letters.Papers(live=tmp_path / "live", store=tmp_path / "store")
    проверка = replace(_проверка(версия), info=(InfoRow(code="INF07", text="30.09.2026"),))
    ответ = letters.build(проверка, lang="ru", papers=хранилище)
    assert "Что получается хорошо:" not in str(ответ["letter"])
    assert letters.FEEDBACK_LANG_FIELD not in ответ["not_restored"]  # type: ignore[operator]
