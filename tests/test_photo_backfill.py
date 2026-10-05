"""#459: хранилище кадров лежит на сдаче — кадры не теряются и доливаются потом.

Хранилище прода живёт на MUSPELHEIM, а тот засыпает (D259). Здесь проверяется
ровно то, что от этого не должно пострадать:

* кадр, не легший на сдаче, остаётся в базе «невыгруженным» и виден дозагрузке,
  а вызывающий получает отдельный тип отказа — тот, после которого бот вправе
  пообещать «догрузится само»;
* дозагрузка возвращает его в хранилище, и повторный проход ничего не делает
  второй раз;
* два выгрузчика одного кадра (сдача и дозагрузка) не переписывают ссылку друг
  друга и не считают чужой кадр своим;
* кадр, которого телеграм не отдал, остаётся ждать, а не пропадает из списка.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.bot import photo_backfill  # noqa: E402
from src.bot.photo_backfill import STALE_AFTER_SEC, backfill_once  # noqa: E402
from src.db.errors import ConfigError, PhotosDeferredError, PushError, StorageError  # noqa: E402
from src.db.photos import pending_photo_uploads, upload_photos  # noqa: E402
from src.db.push import push_inspection  # noqa: E402
from src.domain import add_finding, attach_photo, start_inspection  # noqa: E402

pytestmark = requires_db

КОРЗИНА = "inspection-frames"
КАДРЫ = {
    "tg-file-001": b"\xff\xd8\xff\xe0 frame one",
    "tg-file-002": b"\xff\xd8\xff\xe0 frame two",
}


def _кадр(file_id: str) -> bytes | None:
    return КАДРЫ.get(file_id)


async def _телеграм(file_id: str) -> bytes | None:
    return КАДРЫ.get(file_id)


def _проверка(chat_id: int, *, кадры: tuple[str, ...] = tuple(КАДРЫ)) -> str:
    start_inspection(chat_id, unit="Белград-1", kind="planned", report_lang="ru")
    add_finding(chat_id, code="CLN05", level="D1", zone="hot_kitchen", text="нагар на печи")
    for file_id in кадры:
        attach_photo(chat_id, 1, file_id)
    return push_inspection(chat_id)


def _ссылки(dsn: str, inspection_id: str) -> dict[str, str | None]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select telegram_file_id, storage_path from photos where inspection_id = %s",
            (inspection_id,),
        )
        return {str(f): (None if p is None else str(p)) for f, p in cur.fetchall()}


class Склад:
    """Хранилище-двойник: помнит, что клали. `лежит=True` — недоступно."""

    def __init__(self, *, лежит: bool = False) -> None:
        self.лежит = лежит
        self.положено: dict[str, bytes] = {}
        self.вызовов = 0

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        if self.лежит:
            raise StorageError(f"хранилище недоступно, объект {key} не принят")
        self.вызовов += 1
        self.положено[key] = data
        return f"s3://{КОРЗИНА}/{key}"

    def delete(self, key: str) -> None:
        self.положено.pop(key, None)

    def ping(self) -> None:
        if self.лежит:
            raise StorageError("хранилище не ответило")


# --- сдача при лежащем хранилище -------------------------------------------


def test_лежащее_хранилище_откладывает_кадры_а_не_теряет_их(domain_env: Path, db_env: str) -> None:
    inspection_id = _проверка(41)

    with pytest.raises(PhotosDeferredError):
        upload_photos(inspection_id, fetch=_кадр, storage=Склад(лежит=True))

    assert _ссылки(db_env, inspection_id) == dict.fromkeys(КАДРЫ), "кадр помечен выгруженным"
    ждут = pending_photo_uploads(min_age_sec=0)
    assert [(one.inspection_id, set(one.file_ids)) for one in ждут] == [
        (inspection_id, set(КАДРЫ))
    ], "невыгруженный кадр не виден дозагрузке — он потерян молча"


def test_свежий_кадр_дозагрузка_не_трогает(domain_env: Path, db_env: str) -> None:
    """Его прямо сейчас выгружает сама сдача — качать у телеграма второй раз незачем."""
    _проверка(42)

    assert pending_photo_uploads(min_age_sec=3600) == []


# --- дозагрузка -------------------------------------------------------------


@pytest.mark.asyncio
async def test_дозагрузка_возвращает_кадры_и_второй_проход_пуст(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(43)
    склад = Склад()

    первый = await backfill_once(_телеграм, min_age_sec=0, storage=склад)
    второй = await backfill_once(_телеграм, min_age_sec=0, storage=склад)

    assert (первый.pending, первый.uploaded, первый.storage_down) == (2, 2, False)
    ссылки = _ссылки(db_env, inspection_id)
    assert all(ссылки.values()), f"после дозагрузки остались кадры без ссылки: {ссылки}"
    assert set(склад.положено.values()) == set(КАДРЫ.values()), "в хранилище легли не те байты"
    assert (второй.pending, второй.uploaded) == (0, 0)
    assert склад.вызовов == len(КАДРЫ), "повторный проход положил кадры второй раз"


@pytest.mark.asyncio
async def test_хранилище_всё_ещё_лежит_проход_останавливается_и_кадры_ждут(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(44)

    итог = await backfill_once(_телеграм, min_age_sec=0, storage=Склад(лежит=True))

    assert итог.storage_down
    assert итог.uploaded == 0
    assert _ссылки(db_env, inspection_id) == dict.fromkeys(КАДРЫ)
    assert pending_photo_uploads(min_age_sec=0), "после неудачного прохода кадры пропали из очереди"


@pytest.mark.asyncio
async def test_кадр_не_отданный_телеграмом_остаётся_ждать(domain_env: Path, db_env: str) -> None:
    inspection_id = _проверка(45, кадры=("tg-file-001", "tg-потерян"))

    итог = await backfill_once(_телеграм, min_age_sec=0, storage=Склад())

    assert (итог.uploaded, итог.missing) == (1, 1)
    assert _ссылки(db_env, inspection_id)["tg-потерян"] is None
    (ждёт,) = pending_photo_uploads(min_age_sec=0)
    assert ждёт.file_ids == ("tg-потерян",), "кадр, которого не отдал телеграм, выпал из очереди"


# --- два выгрузчика одного кадра --------------------------------------------


class ОбгоняемыйСклад(Склад):
    """На первом же кадре другой выгрузчик успевает выгрузить и записать всё."""

    def __init__(self, inspection_id: str) -> None:
        super().__init__()
        self.inspection_id = inspection_id
        self.соперник = Склад()
        self.обогнали = 0

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        if not self.обогнали:
            self.обогнали = upload_photos(self.inspection_id, fetch=_кадр, storage=self.соперник)
        return super().put(key, data, content_type=content_type).replace(КОРЗИНА, "чужая")


def test_кадр_записанный_другим_выгрузчиком_не_переписывается_и_не_считается(
    domain_env: Path, db_env: str
) -> None:
    inspection_id = _проверка(46)
    склад = ОбгоняемыйСклад(inspection_id)

    свои = upload_photos(inspection_id, fetch=_кадр, storage=склад)

    assert склад.обогнали == len(КАДРЫ)
    assert свои == 0, "выгрузчик посчитал своими кадры, ссылку на которые записал другой"
    ссылки = _ссылки(db_env, inspection_id)
    assert all(str(p).startswith(f"s3://{КОРЗИНА}/") for p in ссылки.values()), (
        f"ссылку первого выгрузчика переписал второй: {ссылки}"
    )


# --- ревью #514 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_лежащее_хранилище_проверяется_до_телеграма(domain_env: Path, db_env: str) -> None:
    """Хранилище лежит — у телеграма не качаем ничего: всё равно класть некуда."""
    _проверка(47)
    запрошено: list[str] = []

    async def телеграм(file_id: str) -> bytes | None:
        запрошено.append(file_id)
        return КАДРЫ.get(file_id)

    итог = await backfill_once(телеграм, min_age_sec=0, storage=Склад(лежит=True))

    assert итог.storage_down
    assert запрошено == [], "кадры качались у телеграма при лежащем хранилище"


def _состарить(pg_dsn: str, inspection_id: str, дней: int) -> None:
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "update photos set created_at = now() - make_interval(days => %s) "
            "where inspection_id = %s",
            (дней, inspection_id),
        )


@pytest.mark.asyncio
async def test_застарелый_кадр_не_занимает_частый_проход_а_берётся_редким(
    domain_env: Path, db_env: str, pg_dsn: str
) -> None:
    старая = _проверка(48)
    _состарить(pg_dsn, старая, 5)
    свежая = _проверка(49)
    склад = Склад()

    частый = await backfill_once(_телеграм, min_age_sec=0, storage=склад)

    assert частый.pending == len(КАДРЫ), "застарелые кадры попали в частый проход"
    assert all(_ссылки(db_env, свежая).values())
    assert not any(_ссылки(db_env, старая).values())

    редкий = await backfill_once(
        _телеграм, min_age_sec=STALE_AFTER_SEC, max_age_sec=None, storage=склад
    )

    assert (редкий.pending, редкий.uploaded) == (len(КАДРЫ), len(КАДРЫ))
    assert редкий.oldest is not None
    assert all(_ссылки(db_env, старая).values()), "редкий проход не долил застарелые кадры"


@pytest.mark.asyncio
async def test_отказ_одной_проверки_не_обрывает_проход(
    domain_env: Path, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    первая = _проверка(50)
    вторая = _проверка(51)
    настоящая = photo_backfill.db.upload_photos

    def выгрузка(inspection_id: str, **kw: object) -> int:
        if inspection_id == первая:
            raise PushError("база не приняла отметку")
        return настоящая(inspection_id, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(photo_backfill.db, "upload_photos", выгрузка)

    итог = await backfill_once(_телеграм, min_age_sec=0, storage=Склад())

    assert итог.failed == 1
    assert all(_ссылки(db_env, вторая).values()), "вторая проверка не долита после отказа первой"


@pytest.mark.asyncio
async def test_ненастроенное_хранилище_при_непустой_очереди_это_ошибка_вслух(
    domain_env: Path, db_env: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _проверка(52)
    for имя in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_ENDPOINT_URL"):
        monkeypatch.delenv(имя, raising=False)

    with caplog.at_level(logging.ERROR), pytest.raises(ConfigError):
        await backfill_once(_телеграм, min_age_sec=0)

    assert any(
        r.levelno >= logging.ERROR and "кадров ждёт 2" in r.getMessage() for r in caplog.records
    ), "очередь стоит, а журнал молчит"
