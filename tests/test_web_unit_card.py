"""Карточка точки: полоса движения, слабые блоки и то, что не чинится.

Проверяется ровно то, что ошибается молча. Повтор — вывод, который человек
прочитает как факт («это у них система»), и посчитан он здесь, а не записан
движком; шкала столбиков обрезана, и обрезка обязана возвращаться наружу,
иначе картинка преувеличивает разницу, ничего об этом не говоря.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace

import pytest
from flask.testing import FlaskClient

from src.db.models import FindingRow, InspectionRow
from src.web import app as app_mod
from src.web import unit_card
from tests.web_harness import войти, подменить_двери, собрать

ТЕНАНТ = "default"


def проверка(
    *,
    ид: str,
    когда: date,
    pct: float,
    grade: str = "A",
    издание: str = "2026.09",
    набор: str = "bizdev",
) -> InspectionRow:
    return InspectionRow(
        id=ид,
        tenant_code=ТЕНАНТ,
        unit_name="Белград-1",
        chat_id=1,
        kind="planned",
        inspection_date=когда,
        report_lang="ru",
        checklist_version=издание,
        pct=pct,
        grade=grade,
        findings_count=0,
        pushed_at="2026-09-20T10:00:00+00:00",
        checklist_code=набор,
    )


def запись(
    *,
    ид: str,
    проверки: str,
    код: str,
    зона: str = "fridge",
    текст: str = "Дверь",
    повтор: bool = False,
) -> FindingRow:
    return FindingRow(
        id=ид,
        inspection_id=проверки,
        unit_name="Белград-1",
        inspection_date=date(2026, 9, 20),
        n=1,
        code=код,
        level="D1",
        zone=зона,
        zone_unusual=False,
        source="auditor",
        lang="ru",
        text=текст,
        comment=None,
        repeat=повтор,
    )


class TestШкала:
    def test_шкала_обрезается_снизу_иначе_движения_не_видно(self) -> None:
        ряд = (
            проверка(ид="a", когда=date(2026, 3, 1), pct=89.0),
            проверка(ид="b", когда=date(2026, 9, 1), pct=99.0),
        )
        assert unit_card._floor(ряд) == 85.0

    def test_пустой_ряд_шкалы_не_имеет(self) -> None:
        assert unit_card._floor(()) == 0.0

    def test_худший_столбик_ряда_остаётся_видимым(self) -> None:
        ряд = (
            проверка(ид="a", когда=date(2026, 3, 1), pct=85.0),
            проверка(ид="b", когда=date(2026, 9, 1), pct=100.0),
        )
        столбики = unit_card._bars(ряд, floor=unit_card._floor(ряд), издание=("bizdev", "2026.09"))
        assert столбики[0].height >= unit_card.МИНИМУМ_СТОЛБИКА
        assert столбики[1].height == 100.0

    def test_столбик_другого_издания_помечен_несравнимым(self) -> None:
        ряд = (
            проверка(ид="a", когда=date(2026, 3, 1), pct=90.0, издание="2025.01"),
            проверка(ид="b", когда=date(2026, 9, 1), pct=95.0, издание="2026.09"),
        )
        столбики = unit_card._bars(ряд, floor=80.0, издание=("bizdev", "2026.09"))
        assert [b.comparable for b in столбики] == [False, True]


class TestСлабыеБлоки:
    def test_потери_читаются_ключом_loss_и_идут_тяжёлыми_вперёд(self) -> None:
        снимок = {
            "fridge": {"name_ru": "Холодильник", "name_en": "Fridge", "share": 20.0, "loss": 2.0},
            "hall": {"name_ru": "Зал", "name_en": "Hall", "share": 10.0, "loss": 6.0},
        }
        зоны = unit_card._weak(снимок, lang="ru")
        assert [z.code for z in зоны] == ["hall", "fridge"]
        assert [z.loss for z in зоны] == [6.0, 2.0]

    def test_зона_без_потерь_в_слабые_не_попадает(self) -> None:
        снимок = {"hall": {"name_ru": "Зал", "share": 10.0, "loss": 0.0}}
        assert unit_card._weak(снимок, lang="ru") == ()

    def test_имя_зоны_на_языке_интерфейса(self) -> None:
        снимок = {"hall": {"name_ru": "Зал", "name_en": "Hall", "share": 10.0, "loss": 1.0}}
        assert unit_card._weak(снимок, lang="en")[0].name == "Hall"
        assert unit_card._weak(снимок, lang="ru")[0].name == "Зал"


class TestПовторы:
    def test_повтором_считается_код_из_двух_проверок_и_только_он(self) -> None:
        окно = ("p1", "p2", "p3")
        находки = (
            запись(ид="1", проверки="p1", код="PRD01"),
            запись(ид="2", проверки="p3", код="PRD01"),
            запись(ид="3", проверки="p2", код="HYG07"),
        )
        повторы = unit_card._repeats(находки, окно=окно)
        assert [r.code for r in повторы] == ["PRD01"]
        assert повторы[0].marks == ("seen", "none", "seen")
        assert повторы[0].times == 2

    def test_находка_вне_окна_в_повтор_не_идёт(self) -> None:
        находки = (
            запись(ид="1", проверки="p1", код="PRD01"),
            запись(ид="2", проверки="СТАРАЯ", код="PRD01"),
        )
        assert unit_card._repeats(находки, окно=("p1", "p2")) == ()

    def test_повтор_считается_по_коду_а_не_по_формулировке(self) -> None:
        находки = (
            запись(ид="1", проверки="p1", код="PRD01", текст="Дверь холодильника открыта"),
            запись(ид="2", проверки="p2", код="PRD01", текст="Не закрыта дверь холодильной камеры"),
        )
        повторы = unit_card._repeats(находки, окно=("p1", "p2"))
        assert len(повторы) == 1 and повторы[0].times == 2

    def test_отметка_различает_наблюдение_и_засчитанный_повтор(self) -> None:
        # Совпадение кода — наблюдение («такое уже было»), а удвоение цены —
        # решение аудитора, записанное в проверке. Показывать их одинаково
        # значит выдавать наблюдение за факт расчёта (#359).
        находки = (
            запись(ид="1", проверки="p1", код="PRD01"),
            запись(ид="2", проверки="p2", код="PRD01", повтор=True),
        )

        (повтор,) = unit_card._repeats(находки, окно=("p1", "p2"))

        assert повтор.marks == ("seen", "doubled")

    def test_непроверенная_клетка_остаётся_пустой(self) -> None:
        находки = (
            запись(ид="1", проверки="p1", код="PRD01"),
            запись(ид="2", проверки="p3", код="PRD01"),
        )

        (повтор,) = unit_card._repeats(находки, окно=("p1", "p2", "p3"))

        assert повтор.marks == ("seen", "none", "seen")

    def test_засчитанные_вдвое_считаются_отдельно(self) -> None:
        находки = (
            запись(ид="1", проверки="p1", код="PRD01"),
            запись(ид="2", проверки="p2", код="PRD01", повтор=True),
            запись(ид="3", проверки="p3", код="PRD01", повтор=True),
        )

        (повтор,) = unit_card._repeats(находки, окно=("p1", "p2", "p3"))

        assert повтор.times == 3, "число встреч считается по всем записям окна"
        assert повтор.doubled == 2, "засчитанных вдвое — только отмеченные аудитором"

    def test_вторая_запись_того_же_кода_не_гасит_пометку(self) -> None:
        # Один пункт можно записать дважды в одной проверке — в разных зонах.
        # Если повтором отмечена только одна из них, клетка обязана остаться
        # «засчитано вдвое»: удвоение случилось, и цена проверки это помнит.
        находки = (
            запись(ид="1", проверки="p1", код="PRD01"),
            запись(ид="2", проверки="p2", код="PRD01", зона="fridge", повтор=True),
            запись(ид="3", проверки="p2", код="PRD01", зона="hall"),
        )

        (повтор,) = unit_card._repeats(находки, окно=("p1", "p2"))

        assert повтор.marks == ("seen", "doubled")
        assert повтор.doubled == 1

    def test_чаще_повторяющееся_идёт_первым(self) -> None:
        окно = ("p1", "p2", "p3")
        находки = (
            запись(ид="1", проверки="p1", код="РЕДКО"),
            запись(ид="2", проверки="p2", код="РЕДКО"),
            запись(ид="3", проверки="p1", код="ЧАСТО"),
            запись(ид="4", проверки="p2", код="ЧАСТО"),
            запись(ид="5", проверки="p3", код="ЧАСТО"),
        )
        повторы = unit_card._repeats(находки, окно=окно)
        assert [r.code for r in повторы] == ["ЧАСТО", "РЕДКО"]


class TestЭкран:
    """Экран целиком: маршрут, блоки и честные заглушки.

    Проверяется через приложение, а не через шаблон: маршрут, адресация точки
    идентификатором и порядок блоков — это поведение экрана, а не вёрстка.
    """

    @pytest.fixture
    def стенд(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
        подменить_двери(monkeypatch, tenant=ТЕНАНТ)
        точка = SimpleNamespace(id="ид-точки", name="Белград-1", code="BG1")
        monkeypatch.setattr(app_mod.directory, "list_units", lambda **_: [точка])
        with собрать(tenant=ТЕНАНТ).test_client() as client:
            assert войти(client).status_code == 302
            yield client

    def показать(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, снимок: unit_card.UnitCard
    ) -> str:
        monkeypatch.setattr(app_mod.unit_data, "load", lambda **_: снимок)
        ответ = client.get("/units/ид-точки")
        assert ответ.status_code == 200
        return ответ.get_data(as_text=True)

    def снимок(self, **поля: object) -> unit_card.UnitCard:
        последняя = проверка(ид="p9", когда=date(2026, 9, 20), pct=95.5, grade="B")
        основа: dict[str, object] = {
            "name": "Белград-1",
            "city": "Белград",
            "country": "RS",
            "partner": "Партнёр",
            "audits_count": 3,
            "last": последняя,
            "bars": unit_card._bars((последняя,), floor=85.0, издание=("bizdev", "2026.09")),
            "floor": 85.0,
            "comparable": True,
        }
        основа.update(поля)
        return unit_card.UnitCard(**основа)  # type: ignore[arg-type]

    def test_точка_открывается_идентификатором_а_не_названием(
        self, стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        страница = self.показать(стенд, monkeypatch, self.снимок())
        assert "Белград-1" in страница

    def test_несуществующая_точка_отвечает_404(self, стенд: FlaskClient) -> None:
        assert стенд.get("/units/такой-нет").status_code == 404

    def test_столбик_ведёт_в_отчёт_той_же_проверки(
        self, стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        страница = self.показать(стенд, monkeypatch, self.снимок())
        assert "/inspections/p9" in страница

    def test_обрезанная_шкала_названа_вслух(
        self, стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ось, начатая не с нуля и об этом промолчавшая, преувеличивает
        # разницу: 89 и 99 выглядят падением вдвое.
        страница = self.показать(стенд, monkeypatch, self.снимок())
        assert "85" in страница and "шкала от" in страница

    def test_ряд_разных_изданий_методики_предупреждает(
        self, стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        страница = self.показать(стенд, monkeypatch, self.снимок(comparable=False))
        assert "сравнивать нельзя" in страница

    def test_пустые_блоки_говорят_словами_а_не_исчезают(
        self, стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        страница = self.показать(стенд, monkeypatch, self.снимок(weak=(), repeats=()))
        assert "потерь по зонам не записано" in страница
        assert "Ни одно нарушение не повторялось" in страница

    def test_предписания_и_планы_помечены_разработкой_а_не_нулём(
        self, стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ноль означал бы «проверено, открытых нет». Сущностей в системе ещё
        # нет, и проверять нечего — плитка с нулём соврала бы (T357).
        страница = self.показать(стенд, monkeypatch, self.снимок())
        assert "предписаний в системе пока нет" in страница
        assert "Планов проверок в системе пока нет" in страница
