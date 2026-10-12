"""Кадры мини-аппа: чей кадр, сколько их можно прислать и когда брошенные убираются.

F-034 (аудит 12.10.2026): приложить к записи можно только свой кадр. F-033:
квота кадров на чат за сутки и уборка кадров, не попавших ни в одну проверку.
Ядро — права и доказательство: чужой кадр не должен становиться своим, а
уборка не должна снимать кадр проверки.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import (  # noqa: F401
    JPEG,
    ДРУГОЙ_JPEG,
    Клиент,
    _jpeg,
    _нарушение,
    _совет,
    клиент,
)

from src.bot import upload_sweeper
from src.db.errors import PushError
from src.domain import check_environment, get_state, start_inspection
from src.domain import uploads as uploads_mod
from src.domain.upload_sweep import UNATTACHED_TTL_SEC, sweep_uploads
from src.domain.uploads import save_upload, upload_file
from src.web import walk_suggest

ЧУЖОЙ = 777


def _чужой(клиент: Клиент) -> Клиент:  # noqa: F811
    start_inspection(ЧУЖОЙ, unit="Белград-2", kind="planned", report_lang="ru", ui_lang="ru")
    return Клиент(клиент.c, user_id=ЧУЖОЙ)


# ── F-034: только свой кадр ─────────────────────────────────────────────


def test_чужой_кадр_по_ссылке_не_прикладывается_и_не_показывается(клиент: Клиент) -> None:  # noqa: F811
    ref = клиент.ссылка()
    assert клиент.запись(**_нарушение(ref)).status_code == 200
    чужой = _чужой(клиент)

    добавление = чужой.запись(**_нарушение(ref))
    assert добавление.status_code == 422, "чужая ссылка не годится для новой записи"
    assert "не дошло" in добавление.get_json()["message"], "ответ как у пропавшего кадра"

    свой = чужой.ссылка(ДРУГОЙ_JPEG)
    assert чужой.запись(**_нарушение(свой)).status_code == 200
    assert чужой.запись(op="attach", n=1, ref=ref).status_code == 422
    assert get_state(ЧУЖОЙ).findings[0].photos == [свой]  # type: ignore[union-attr]
    assert чужой.показ(ref).status_code == 404


def test_пропавший_и_чужой_кадр_отвечают_одинаково(клиент: Клиент) -> None:  # noqa: F811
    ref = клиент.ссылка()
    чужой = _чужой(клиент)
    чужой_ответ = чужой.запись(**_нарушение(ref))
    пропавший = чужой.запись(**_нарушение("walk:" + "0" * 32))
    assert (чужой_ответ.status_code, чужой_ответ.get_json()) == (
        пропавший.status_code,
        пропавший.get_json(),
    ), "ответ не выдаёт, присылал ли кто-нибудь такой кадр"


def test_те_же_байты_от_второго_чата_становятся_и_его(клиент: Клиент) -> None:  # noqa: F811
    ref = клиент.ссылка()
    чужой = _чужой(клиент)
    assert чужой.ссылка() == ref, "одинаковые байты — одна ссылка"
    assert чужой.запись(**_нарушение(ref)).status_code == 200, "прислал сам — значит свой"


def test_кадр_из_своей_проверки_прикладывается_и_без_метки(
    клиент: Клиент,  # noqa: F811
    domain_env: Path,
) -> None:
    ref = клиент.ссылка()
    клиент.запись(**_нарушение(ref))
    assert клиент.запись(**_совет(text="проверить уплотнитель")).status_code == 200
    for mark in uploads_mod.owners_dir(check_environment()).glob("*/*"):
        mark.unlink()  # метки просрочены и убраны уборкой

    assert клиент.запись(op="attach", n=2, ref=ref).status_code == 200


def test_поиск_пункта_не_смотрит_чужой_кадр(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = клиент.ссылка()
    чужой = _чужой(клиент)
    monkeypatch.setattr(
        walk_suggest, "propose", lambda *a, **k: pytest.fail("чужой кадр ушёл в модель")
    )
    ответ = чужой.c.post(
        walk_suggest.SUGGEST_PATH,
        data=json.dumps({"words": "грязь", "photos": [ref]}),
        content_type="application/json",
        headers={"X-Telegram-Init-Data": чужой.init},
    )
    assert ответ.status_code == 422


# ── F-033: квота ────────────────────────────────────────────────────────


def test_квота_кадров_за_сутки_отказывает_словами(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uploads_mod, "QUOTA_FRAMES", 2)
    первый = клиент.ссылка(_jpeg((10, 20, 30)))
    клиент.ссылка(_jpeg((40, 50, 60)))

    третий = клиент.кадр(_jpeg((70, 80, 90)))
    assert третий.status_code == 422
    assert "Лимит фото" in третий.get_json()["message"]

    assert клиент.ссылка(_jpeg((10, 20, 30))) == первый, "досылка своего кадра — не новый кадр"


def test_квота_по_байтам(клиент: Клиент, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(uploads_mod, "QUOTA_BYTES", len(JPEG) + 10)
    клиент.ссылка()
    assert клиент.кадр(ДРУГОЙ_JPEG).status_code == 422


def test_квота_считает_только_сутки(клиент: Клиент, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(uploads_mod, "QUOTA_FRAMES", 1)
    клиент.ссылка()
    вчера = time.time() - uploads_mod.QUOTA_WINDOW_SEC - 1
    for mark in uploads_mod.owners_dir(check_environment()).glob(f"{АУДИТОР}/*"):
        os.utime(mark, (вчера, вчера))
    assert клиент.кадр(ДРУГОЙ_JPEG).status_code == 201


def test_квота_у_каждого_чата_своя(клиент: Клиент, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(uploads_mod, "QUOTA_FRAMES", 1)
    клиент.ссылка()
    assert _чужой(клиент).кадр(ДРУГОЙ_JPEG).status_code == 201


# ── F-033: уборка ───────────────────────────────────────────────────────


def _состарить(path: Path, сек: float) -> None:
    давно = time.time() - сек
    os.utime(path, (давно, давно))


def test_уборка_снимает_брошенный_и_не_трогает_привязанные(клиент: Клиент) -> None:  # noqa: F811
    settings = check_environment()
    в_записи = клиент.ссылка()
    клиент.запись(**_нарушение(в_записи))
    в_базе = save_upload(_jpeg((1, 2, 3)), settings, owner=АУДИТОР)
    брошенный = save_upload(_jpeg((4, 5, 6)), settings, owner=АУДИТОР)
    свежий = save_upload(_jpeg((7, 8, 9)), settings, owner=АУДИТОР)
    for ref in (в_записи, в_базе, брошенный):
        _состарить(upload_file(ref, settings), UNATTACHED_TTL_SEC + 60)  # type: ignore[arg-type]

    итог = sweep_uploads(settings, keep={в_базе})

    assert upload_file(брошенный, settings) is None, "брошенный старше срока убран"
    assert upload_file(в_записи, settings) is not None, "кадр открытой проверки цел"
    assert upload_file(в_базе, settings) is not None, "кадр сданной проверки цел"
    assert upload_file(свежий, settings) is not None, "свежий кадр черновика цел"
    assert итог.frames == 1


def test_уборка_снимает_просроченные_метки_и_обрывки(domain_env: Path) -> None:
    settings = check_environment()
    ref = save_upload(JPEG, settings, owner=АУДИТОР)
    метка = next(uploads_mod.owners_dir(settings).glob("*/*"))
    _состарить(метка, UNATTACHED_TTL_SEC + 60)
    обрывок = upload_file(ref, settings).with_name("x.part")  # type: ignore[union-attr]
    обрывок.write_bytes(b"\xff")
    _состарить(обрывок, 2 * 60 * 60)

    итог = sweep_uploads(settings, keep={ref})

    assert not метка.exists() and not обрывок.exists()
    assert (итог.marks, итог.parts) == (1, 1)


def test_без_базы_уборка_не_удаляет_ничего(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = check_environment()
    ref = save_upload(JPEG, settings, owner=АУДИТОР)
    _состарить(upload_file(ref, settings), UNATTACHED_TTL_SEC + 60)  # type: ignore[arg-type]

    def молчит() -> set[str]:
        raise PushError("база недоступна")

    monkeypatch.setattr(upload_sweeper, "walk_photo_refs", молчит)

    assert upload_sweeper.sweep_once() is None
    assert upload_file(ref, settings) is not None, "не зная базы, кадр сданной проверки не трогаем"
