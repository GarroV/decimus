"""D465: запись и кадры на приёмке — добавить запись, приложить и снять кадр.

Правит только своё пространство (D283) и только ждущую проверку: граница стоит в
запросе (замок `status = 'draft'`) и в политиках базы. Запись и её оценка ложатся
одной транзакцией; объект кадра уходит из хранилища после снятия строки.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import accept_pushed, привязать_страну, точка_справочника

psycopg = pytest.importorskip("psycopg")
Image = pytest.importorskip("PIL.Image")

from src.db.errors import ReviseError, StorageError  # noqa: E402
from src.db.inspection_edits import Editor  # noqa: E402
from src.db.models import InspectionDetail  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import own_reach  # noqa: E402
from src.db.review_edit import (  # noqa: E402
    Addition,
    add_finding,
    attach_photo,
    delete_finding,
    detach_photo,
)
from src.domain import add_finding as walk_add_finding  # noqa: E402
from src.domain import start_inspection  # noqa: E402
from src.domain.models import Score  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
УК = own_reach("HQ")

ОЦЕНКА = Score(
    pct=77.0,
    grade="C",
    label_ru="",
    label_en="",
    counts={"D1": 0, "D2": 2, "D3": 0},
    deductions=23.0,
    by_zone={},
)

ПРАВИТ = Editor(user_id="00000000-0000-0000-0000-0000000000a1", login="kontroling", role="admin")

НОВАЯ = Addition(code="CLN06", level="D2", zone="dining", zone_unusual=False, text="стены в зале")


class Склад:
    """Хранилище в памяти: что положено и что убрано."""

    def __init__(self, *, падает: bool = False) -> None:
        self.объекты: dict[str, bytes] = {}
        self.падает = падает

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        if self.падает:
            raise StorageError("хранилище лежит")
        self.объекты[key] = data
        return f"s3://bucket/{key}"

    def delete(self, key: str) -> None:
        self.объекты.pop(key, None)


def _кадр() -> bytes:
    буфер = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 120, 30)).save(буфер, format="JPEG")
    return буфер.getvalue()


def _по(оценка: Score) -> Callable[[InspectionDetail], Score]:
    return lambda _detail: оценка


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> None:
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")


def _ждущая(chat_id: int, tenant: str = "HQ") -> tuple[str, str]:
    start_inspection(chat_id, unit=ТОЧКА, kind="planned", report_lang="ru", tenant=tenant)
    walk_add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="пол в цехе")
    ident = push_inspection(chat_id)
    detail = get_inspection(ident, reach=own_reach(tenant), include_on_review=True)
    assert detail is not None
    return ident, detail.findings[0].id


# --- добавить запись -----------------------------------------------------------


def test_запись_добавляется_с_оценкой_движка_одной_транзакцией(сеть: None) -> None:
    # Arrange
    ident, _ = _ждущая(701)
    увиденное: list[int] = []

    def движок(current: InspectionDetail) -> Score:
        увиденное.append(len(current.findings))
        return ОЦЕНКА

    # Act
    новая = add_finding(ident, tenant="HQ", addition=НОВАЯ, editor=ПРАВИТ, score_of=движок)

    # Assert — движок видел обе записи, в базе обе и оценка движка
    assert увиденное == [2]
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert после is not None
    assert sorted(f.n for f in после.findings) == [1, 2]
    добавленная = next(f for f in после.findings if f.id == новая)
    assert (добавленная.code, добавленная.zone, добавленная.text) == (
        "CLN06",
        "dining",
        "стены в зале",
    )
    assert (после.inspection.pct, после.inspection.grade) == (77.0, "C")


def test_упавший_движок_ничего_не_оставляет(сеть: None) -> None:
    ident, _ = _ждущая(702)

    def сломан(_detail: InspectionDetail) -> Score:
        raise RuntimeError("движок упал")

    with pytest.raises(RuntimeError):
        add_finding(ident, tenant="HQ", addition=НОВАЯ, editor=ПРАВИТ, score_of=сломан)
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert after_count(после) == 1


def after_count(detail: InspectionDetail | None) -> int:
    assert detail is not None
    return len(detail.findings)


def test_занятая_пара_пункт_зона_отклоняется(сеть: None) -> None:
    ident, _ = _ждущая(703)
    в_занятую = Addition(
        code="CLN05", level="D1", zone="hot_kitchen", zone_unusual=False, text="ещё раз"
    )
    with pytest.raises(ReviseError, match="уже записан"):
        add_finding(ident, tenant="HQ", addition=в_занятую, editor=ПРАВИТ, score_of=_по(ОЦЕНКА))
    assert after_count(get_inspection(ident, reach=УК, include_on_review=True)) == 1


def test_у_принятой_запись_не_добавляется(сеть: None, db_env: str) -> None:
    ident, _ = _ждущая(704)
    accept_pushed(ident, dsn=db_env)
    with pytest.raises(ReviseError, match="уже принята"):
        add_finding(ident, tenant="HQ", addition=НОВАЯ, editor=ПРАВИТ, score_of=_по(ОЦЕНКА))
    assert after_count(get_inspection(ident, reach=УК)) == 1


@pytest.mark.parametrize(("владелец", "правит"), [("GE", "HQ"), ("HQ", "GE")])
def test_в_чужую_проверку_запись_не_добавляется(сеть: None, владелец: str, правит: str) -> None:
    ident, _ = _ждущая(705, tenant=владелец)
    with pytest.raises(ReviseError, match="нет"):
        add_finding(ident, tenant=правит, addition=НОВАЯ, editor=ПРАВИТ, score_of=_по(ОЦЕНКА))
    assert (
        after_count(get_inspection(ident, reach=own_reach(владелец), include_on_review=True)) == 1
    )


def test_пустая_формулировка_отклоняется(сеть: None) -> None:
    ident, _ = _ждущая(706)
    пустая = Addition(code="CLN06", level="D2", zone="dining", zone_unusual=False, text="  ")
    with pytest.raises(ReviseError, match="пуста"):
        add_finding(ident, tenant="HQ", addition=пустая, editor=ПРАВИТ, score_of=_по(ОЦЕНКА))


# --- кадры ---------------------------------------------------------------------


def _кадры_записи(ident: str, запись: str) -> list[str]:
    from src.db.previews import finding_previews

    показ = finding_previews(ident, reach=УК).get(запись)
    return list(показ.shown) if показ is not None else []


def test_кадр_прикладывается_в_хранилище_и_виден_в_записи(сеть: None) -> None:
    # Arrange
    ident, запись = _ждущая(711)
    склад = Склад()

    # Act
    кадр = attach_photo(ident, запись, tenant="HQ", data=_кадр(), storage=склад)

    # Assert — объект в хранилище, кадр показывается у записи
    assert any(кадр in ключ for ключ in склад.объекты)
    assert _кадры_записи(ident, запись) == [кадр]


def test_кадр_снимается_строка_и_объект(сеть: None) -> None:
    ident, запись = _ждущая(712)
    склад = Склад()
    кадр = attach_photo(ident, запись, tenant="HQ", data=_кадр(), storage=склад)

    detach_photo(ident, кадр, tenant="HQ", storage=склад)

    assert _кадры_записи(ident, запись) == []
    assert склад.объекты == {}


def test_не_изображение_и_лежащее_хранилище_кадра_не_заводят(сеть: None) -> None:
    ident, запись = _ждущая(713)
    with pytest.raises(ReviseError, match="не читается"):
        attach_photo(ident, запись, tenant="HQ", data=b"not an image", storage=Склад())
    with pytest.raises(ReviseError, match="не приняло"):
        attach_photo(ident, запись, tenant="HQ", data=_кадр(), storage=Склад(падает=True))
    assert _кадры_записи(ident, запись) == []


def test_у_принятой_кадры_не_меняются(сеть: None, db_env: str) -> None:
    ident, запись = _ждущая(714)
    склад = Склад()
    кадр = attach_photo(ident, запись, tenant="HQ", data=_кадр(), storage=склад)
    accept_pushed(ident, dsn=db_env)

    with pytest.raises(ReviseError, match="уже принята"):
        attach_photo(ident, запись, tenant="HQ", data=_кадр(), storage=склад)
    with pytest.raises(ReviseError, match="уже принята"):
        detach_photo(ident, кадр, tenant="HQ", storage=склад)
    assert _кадры_записи(ident, запись) == [кадр]
    assert len(склад.объекты) == 1


@pytest.mark.parametrize(("владелец", "правит"), [("GE", "HQ"), ("HQ", "GE")])
def test_чужие_кадры_не_меняются(сеть: None, владелец: str, правит: str) -> None:
    ident, запись = _ждущая(715, tenant=владелец)
    склад = Склад()
    кадр = attach_photo(ident, запись, tenant=владелец, data=_кадр(), storage=склад)

    with pytest.raises(ReviseError, match="нет"):
        attach_photo(ident, запись, tenant=правит, data=_кадр(), storage=склад)
    with pytest.raises(ReviseError, match="нет"):
        detach_photo(ident, кадр, tenant=правит, storage=склад)
    assert len(склад.объекты) == 1


def test_кадр_чужой_записи_другой_проверки_не_снимается(сеть: None) -> None:
    первая, запись = _ждущая(716)
    вторая, _ = _ждущая(717)
    склад = Склад()
    кадр = attach_photo(первая, запись, tenant="HQ", data=_кадр(), storage=склад)

    with pytest.raises(ReviseError, match="нет"):
        detach_photo(вторая, кадр, tenant="HQ", storage=склад)
    assert len(склад.объекты) == 1


# --- снять запись (#1164) ------------------------------------------------------


def _журнал_правок(pg_dsn: str, ident: str) -> list[tuple[str, str, dict[str, object]]]:
    """Вид, запись и изменения из журнала правок — под владельцем: роль приложения не читает."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select kind, finding_id::text, changes from inspection_edits "
            "where inspection_id = %s order by id",
            (ident,),
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def test_запись_снимается_номера_не_сдвигаются_оценка_от_движка_след_в_журнале(
    сеть: None, pg_dsn: str
) -> None:
    # Arrange — две записи, у первой кадр
    ident, первая = _ждущая(721)
    вторая = add_finding(ident, tenant="HQ", addition=НОВАЯ, editor=ПРАВИТ, score_of=_по(ОЦЕНКА))
    склад = Склад()
    attach_photo(ident, первая, tenant="HQ", data=_кадр(), storage=склад)
    увиденное: list[list[str]] = []

    def движок(current: InspectionDetail) -> Score:
        увиденное.append([f.id for f in current.findings])
        return ОЦЕНКА

    # Act
    delete_finding(ident, первая, tenant="HQ", editor=ПРАВИТ, score_of=движок, storage=склад)

    # Assert — движок видел проверку без снятой записи, у оставшейся прежний номер
    assert увиденное == [[вторая]]
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert после is not None
    assert [(f.id, f.n) for f in после.findings] == [(вторая, 2)]
    assert (после.inspection.pct, после.inspection.grade) == (77.0, "C")
    assert склад.объекты == {}
    # след в журнале: вид, запись, прежние значения полей и оценка до и после
    *_, (вид, запись, изменения) = _журнал_правок(pg_dsn, ident)
    assert (вид, запись) == ("delete", первая)
    assert изменения["code"] == {"old": "CLN05", "new": None}
    assert изменения["text"] == {"old": "пол в цехе", "new": None}
    assert "score_pct" in изменения


@pytest.mark.parametrize("класс", ["D0", "R"])
def test_запись_без_вычета_снимается_так_же_и_оценку_кладёт_движок(
    сеть: None, pg_dsn: str, класс: str
) -> None:
    # Arrange — D1 и запись без вычета (D0 или совет R): дверь базы не смотрит на класс (D624)
    chat_id = 731 if класс == "D0" else 732
    start_inspection(chat_id, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ")
    walk_add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="пол в цехе")
    walk_add_finding(chat_id, code="CLN06", level=класс, zone="dining", text="стены в зале")
    ident = push_inspection(chat_id)
    до = get_inspection(ident, reach=УК, include_on_review=True)
    assert до is not None
    снимаемая = next(f for f in до.findings if f.level == класс)
    оставшаяся = next(f for f in до.findings if f.level == "D1")
    увиденное: list[list[str]] = []

    def движок(current: InspectionDetail) -> Score:
        увиденное.append([f.id for f in current.findings])
        return ОЦЕНКА

    # Act
    delete_finding(
        ident, снимаемая.id, tenant="HQ", editor=ПРАВИТ, score_of=движок, storage=Склад()
    )

    # Assert — движок видел проверку без записи, оценка от него, след в журнале
    assert увиденное == [[оставшаяся.id]]
    после = get_inspection(ident, reach=УК, include_on_review=True)
    assert после is not None
    assert [f.id for f in после.findings] == [оставшаяся.id]
    assert (после.inspection.pct, после.inspection.grade) == (77.0, "C")
    *_, (вид, запись, _) = _журнал_правок(pg_dsn, ident)
    assert (вид, запись) == ("delete", снимаемая.id)


def test_несуществующая_запись_не_снимается(сеть: None) -> None:
    ident, _ = _ждущая(722)
    with pytest.raises(ReviseError, match="записи в этой проверке нет"):
        delete_finding(
            ident,
            "99999999-9999-9999-9999-999999999999",
            tenant="HQ",
            editor=ПРАВИТ,
            score_of=_по(ОЦЕНКА),
            storage=Склад(),
        )


def test_у_принятой_запись_не_снимается(сеть: None, db_env: str) -> None:
    ident, запись = _ждущая(723)
    accept_pushed(ident, dsn=db_env)
    with pytest.raises(ReviseError, match="уже принята"):
        delete_finding(
            ident, запись, tenant="HQ", editor=ПРАВИТ, score_of=_по(ОЦЕНКА), storage=Склад()
        )
    assert after_count(get_inspection(ident, reach=УК)) == 1


@pytest.mark.parametrize(("владелец", "правит"), [("GE", "HQ"), ("HQ", "GE")])
def test_чужая_запись_не_снимается(сеть: None, владелец: str, правит: str) -> None:
    ident, запись = _ждущая(724, tenant=владелец)
    with pytest.raises(ReviseError, match="нет"):
        delete_finding(
            ident, запись, tenant=правит, editor=ПРАВИТ, score_of=_по(ОЦЕНКА), storage=Склад()
        )
    assert (
        after_count(get_inspection(ident, reach=own_reach(владелец), include_on_review=True)) == 1
    )


def test_упавший_движок_запись_не_снимает(сеть: None) -> None:
    ident, запись = _ждущая(725)

    def сломан(_detail: InspectionDetail) -> Score:
        raise RuntimeError("движок упал")

    with pytest.raises(RuntimeError):
        delete_finding(ident, запись, tenant="HQ", editor=ПРАВИТ, score_of=сломан, storage=Склад())
    assert after_count(get_inspection(ident, reach=УК, include_on_review=True)) == 1
